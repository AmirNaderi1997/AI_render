"""JSON advice through the main application's configured LLM provider."""
import asyncio
import json
import os
from uuid import uuid4

from brain.llm import chat_json
from hermes.database import list_rows, save_row
from hermes.security import utcnow


PROMPTS = {
    "best_time": "Return JSON with times: a list of weekday, local_time HH:MM, timezone, and reason. Use the supplied account insights when available. Do not invent measured data.",
    "hashtags": "Return JSON with hashtags: a list of relevant hashtag strings. Avoid spam and unrelated tags.",
    "caption": "Return JSON with captions: a list of 3 distinct caption strings suitable for Instagram.",
    "content_plan": "Return JSON with days: a list of weekday, topic, format, caption_idea, and local_time. Fit the requested number of posts.",
}


async def advise(account_id, kind, input_data):
    if kind not in PROMPTS:
        raise ValueError("INVALID_ADVICE_TYPE")
    input_data = dict(input_data)
    if kind == "best_time":
        insights = [row for row in await list_rows("account_insights") if row["account_id"] == account_id]
        posts = {row["id"]: row for row in await list_rows("posts") if row["account_id"] == account_id}
        analytics = [
            {"posted_at": posts[row["post_id"]].get("posted_at"), "reach": row.get("reach"),
             "engagement_rate": row.get("engagement_rate")}
            for row in await list_rows("post_analytics") if row["post_id"] in posts
        ]
        input_data["recent_account_insights"] = sorted(insights, key=lambda row: row["fetched_at"], reverse=True)[:7]
        input_data["recent_post_performance"] = sorted(analytics, key=lambda row: row.get("posted_at") or "", reverse=True)[:30]
    hermes_model = os.environ.get("HERMES_LLM_MODEL")
    result, _usage = await asyncio.to_thread(chat_json, PROMPTS[kind], json.dumps(input_data, ensure_ascii=False), max_tokens=1500, model=hermes_model)
    if not isinstance(result, dict):
        raise ValueError("ADVISOR_INVALID_RESPONSE")
    await save_row("advisor_logs", {
        "id": uuid4().hex, "account_id": account_id, "request_type": kind,
        "input_data": input_data, "recommendation": result, "created_at": utcnow(),
    })
    return result
