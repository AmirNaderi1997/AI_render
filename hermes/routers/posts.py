"""Owner-scoped post management and local media intake."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from hermes.config import settings
from hermes.database import delete_row, list_rows, save_row
from hermes.schemas import PostCreate, PostUpdate
from hermes.security import current_user, owned_account, owned_post, utcnow
from hermes.services.instagram_api import InstagramError
from hermes.services.scheduler_service import publish_post

router = APIRouter(prefix="/api/hermes/posts", tags=["hermes-posts"])


def _scheduled(value):
    if value and value <= datetime.now(timezone.utc):
        raise HTTPException(422, detail={"code": "SCHEDULE_MUST_BE_FUTURE"})


@router.post("/")
async def create(body: PostCreate, user=Depends(current_user)):
    await owned_account(body.account_id, user)
    _scheduled(body.scheduled_at)
    post = {
        "id": uuid4().hex, **body.model_dump(mode="json"),
        "posted_at": None, "status": "scheduled" if body.scheduled_at else "draft",
        "ig_post_id": None, "error_message": None, "created_at": utcnow(),
    }
    return await save_row("posts", post)


@router.get("/")
async def list_posts(status: str | None = None, start: datetime | None = None, end: datetime | None = None,
                     user=Depends(current_user)):
    if status and status not in ("draft", "scheduled", "publishing", "posted", "failed"):
        raise HTTPException(422, detail={"code": "INVALID_STATUS"})
    if (start and start.tzinfo is None) or (end and end.tzinfo is None):
        raise HTTPException(422, detail={"code": "TIMEZONE_REQUIRED"})
    accounts = {row["id"] for row in await list_rows("accounts") if str(row["user_id"]) == str(user.id)}
    posts = [row for row in await list_rows("posts") if row["account_id"] in accounts]
    if status:
        posts = [row for row in posts if row["status"] == status]
    if start:
        posts = [row for row in posts if row.get("scheduled_at") and datetime.fromisoformat(row["scheduled_at"]) >= start]
    if end:
        posts = [row for row in posts if row.get("scheduled_at") and datetime.fromisoformat(row["scheduled_at"]) <= end]
    return sorted(posts, key=lambda row: row.get("scheduled_at") or row["created_at"])


@router.post("/media")
async def upload_media(file: UploadFile = File(...), user=Depends(current_user)):
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "video/mp4": ".mp4"}
    if file.content_type not in allowed:
        raise HTTPException(422, detail={"code": "UNSUPPORTED_MEDIA_TYPE"})
    directory = Path(settings.HERMES_DATA_DIR) / "media" / str(user.id)
    directory.mkdir(parents=True, exist_ok=True)
    name = uuid4().hex + allowed[file.content_type]
    path = directory / name
    size = 0
    try:
        with path.open("xb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 100 * 1024 * 1024:
                    raise HTTPException(413, detail={"code": "MEDIA_TOO_LARGE"})
                target.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    base = settings.HERMES_PUBLIC_MEDIA_BASE_URL.rstrip("/")
    media_base = base if base.endswith("/media/hermes") else f"{base}/media/hermes"
    return {"media_id": name, "bytes": size,
            "media_url": f"{media_base}/{user.id}/{name}" if base.startswith("https://") else None,
            "requires_public_url": not base.startswith("https://")}


@router.get("/{post_id}")
async def detail(post_id: str, user=Depends(current_user)):
    return await owned_post(post_id, user)


@router.put("/{post_id}")
async def update(post_id: str, body: PostUpdate, user=Depends(current_user)):
    post = await owned_post(post_id, user)
    if post["status"] in ("posted", "publishing"):
        raise HTTPException(409, detail={"code": "POST_NOT_EDITABLE"})
    values = body.model_dump(mode="json", exclude_unset=True)
    if "scheduled_at" in values:
        _scheduled(body.scheduled_at)
    post.update(values)
    if post.get("scheduled_at") and not post.get("media_urls"):
        raise HTTPException(422, detail={"code": "MEDIA_REQUIRED"})
    post["status"] = "scheduled" if post.get("scheduled_at") else "draft"
    post["error_message"] = None
    return await save_row("posts", post)


@router.delete("/{post_id}")
async def delete(post_id: str, user=Depends(current_user)):
    post = await owned_post(post_id, user)
    if post["status"] in ("posted", "publishing"):
        raise HTTPException(409, detail={"code": "POST_NOT_DELETABLE"})
    await delete_row("posts", post_id)
    return {"deleted": True}


@router.post("/{post_id}/publish")
async def publish(post_id: str, user=Depends(current_user)):
    await owned_post(post_id, user)
    try:
        return await publish_post(post_id)
    except InstagramError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code}) from exc
    except ValueError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(502, detail={"code": "PUBLISH_FAILED"}) from exc
