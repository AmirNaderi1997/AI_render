from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from hermes.database import list_rows, save_row
from hermes.schemas import BulkSchedule
from hermes.security import current_user, owned_post

router = APIRouter(prefix="/api/hermes/schedule", tags=["hermes-schedule"])


@router.get("/")
async def calendar(start: datetime | None = None, end: datetime | None = None, user=Depends(current_user)):
    if (start and start.tzinfo is None) or (end and end.tzinfo is None):
        raise HTTPException(422, detail={"code": "TIMEZONE_REQUIRED"})
    accounts = {row["id"] for row in await list_rows("accounts") if str(row["user_id"]) == str(user.id)}
    posts = [row for row in await list_rows("posts") if row["account_id"] in accounts and row.get("scheduled_at")]
    if start:
        posts = [row for row in posts if datetime.fromisoformat(row["scheduled_at"]) >= start]
    if end:
        posts = [row for row in posts if datetime.fromisoformat(row["scheduled_at"]) <= end]
    return sorted(posts, key=lambda row: row["scheduled_at"])


@router.post("/bulk")
async def bulk(body: BulkSchedule, user=Depends(current_user)):
    ids = [item.post_id for item in body.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, detail={"code": "DUPLICATE_POST"})
    posts = [await owned_post(row_id, user) for row_id in ids]
    if any(post["status"] in ("posted", "publishing") for post in posts):
        raise HTTPException(409, detail={"code": "POST_NOT_EDITABLE"})
    if any(not post.get("media_urls") for post in posts):
        raise HTTPException(422, detail={"code": "MEDIA_REQUIRED"})
    if any(item.scheduled_at <= datetime.now(timezone.utc) for item in body.items):
        raise HTTPException(422, detail={"code": "SCHEDULE_MUST_BE_FUTURE"})
    result = []
    for post, item in zip(posts, body.items):
        post.update(scheduled_at=item.scheduled_at.isoformat(), status="scheduled", error_message=None)
        result.append(await save_row("posts", post))
    return result
