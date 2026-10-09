"""Persisted, one-hour Instagram insights cache."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from hermes.database import list_rows, save_row
from hermes.security import decrypt_token, utcnow
from hermes.services.instagram_api import InstagramAPI


def fresh(row):
    return datetime.fromisoformat(row["fetched_at"]) > datetime.now(timezone.utc) - timedelta(hours=1)


async def account_insights(account, force=False):
    rows = [row for row in await list_rows("account_insights") if row["account_id"] == account["id"]]
    rows.sort(key=lambda row: row["fetched_at"], reverse=True)
    if rows and fresh(rows[0]) and not force:
        return rows[0]
    api = InstagramAPI(account["ig_user_id"], decrypt_token(account["access_token"]))
    profile = await api.profile()
    metrics = await api.insights(account["ig_user_id"], ("impressions", "reach", "profile_views", "website_clicks"), period="day")
    row = {
        "id": uuid4().hex, "account_id": account["id"], "date": datetime.now(timezone.utc).date().isoformat(),
        "followers": profile.get("followers_count"), "follows": profile.get("follows_count"),
        **metrics, "fetched_at": utcnow(),
    }
    return await save_row("account_insights", row)


async def post_insights(account, force=False):
    posts = [post for post in await list_rows("posts") if post["account_id"] == account["id"] and post.get("ig_post_id")]
    cached = await list_rows("post_analytics")
    api = InstagramAPI(account["ig_user_id"], decrypt_token(account["access_token"]))
    output = []
    for post in posts:
        rows = sorted((row for row in cached if row["post_id"] == post["id"]), key=lambda row: row["fetched_at"], reverse=True)
        if rows and fresh(rows[0]) and not force:
            output.append(rows[0]); continue
        metrics = await api.insights(post["ig_post_id"], ("impressions", "reach", "likes", "comments", "shares", "saved"))
        reach = metrics.get("reach") or 0
        interactions = sum(metrics.get(name) or 0 for name in ("likes", "comments", "shares", "saved"))
        row = {
            "id": uuid4().hex, "post_id": post["id"], "ig_post_id": post["ig_post_id"],
            "impressions": metrics.get("impressions"), "reach": metrics.get("reach"),
            "likes": metrics.get("likes"), "comments": metrics.get("comments"),
            "shares": metrics.get("shares"), "saves": metrics.get("saved"),
            "engagement_rate": round(interactions / reach * 100, 2) if reach else None,
            "fetched_at": utcnow(),
        }
        output.append(await save_row("post_analytics", row))
    return output
