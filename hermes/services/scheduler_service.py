"""Local polling and Celery beat entry point for due posts."""
import asyncio
import logging
from datetime import datetime, timezone

from hermes.config import settings
from hermes.database import claim_post, get_row, list_rows, save_row
from hermes.security import decrypt_token, utcnow
from hermes.services.instagram_api import InstagramAPI, InstagramError
from logging_config import configure_structured_logging

log = logging.getLogger(__name__)


async def publish_post(post_id, *, allowed=("draft", "scheduled", "failed")):
    if not await claim_post(post_id, allowed):
        raise ValueError("POST_NOT_PUBLISHABLE")
    post = await get_row("posts", post_id)
    account = await get_row("accounts", post["account_id"])
    if not account:
        post.update(status="failed", error_message="ACCOUNT_NOT_FOUND")
        await save_row("posts", post)
        raise ValueError("ACCOUNT_NOT_FOUND")
    try:
        if datetime.fromisoformat(account["token_expires_at"]) <= datetime.now(timezone.utc):
            raise InstagramError("INSTAGRAM_TOKEN_EXPIRED", 409)
        api = InstagramAPI(account["ig_user_id"], decrypt_token(account["access_token"]))
        caption = post["caption"] + ("\n\n" + " ".join("#" + tag.lstrip("#") for tag in post["hashtags"]) if post["hashtags"] else "")
        ig_id = await api.publish(account["ig_user_id"], post["media_urls"], caption)
    except Exception as exc:
        code = exc.code if isinstance(exc, InstagramError) else "PUBLISH_FAILED"
        post.update(status="failed", error_message=code)
        await save_row("posts", post)
        raise
    post.update(status="posted", posted_at=utcnow(), ig_post_id=ig_id, error_message=None)
    return await save_row("posts", post)


async def publish_due():
    now = datetime.now(timezone.utc)
    for post in await list_rows("posts"):
        if post["status"] == "scheduled" and post.get("scheduled_at") and datetime.fromisoformat(post["scheduled_at"]) <= now:
            try:
                await publish_post(post["id"], allowed=("scheduled",))
            except Exception as exc:
                log.warning("Hermes scheduled post %s failed: %s", post["id"], type(exc).__name__)


async def local_schedule_loop():
    while True:
        try:
            await publish_due()
        except Exception:
            log.exception("Hermes schedule poll failed")
        await asyncio.sleep(30)


celery_app = None


def _publish_due_task():
    async def run():
        try:
            await publish_due()
        finally:
            from hermes import database
            if database._engine:
                await database._engine.dispose()
    asyncio.run(run())


if settings.REDIS_URL:
    from celery import Celery
    from celery.signals import setup_logging

    setup_logging.connect(lambda **kwargs: configure_structured_logging(), weak=False)
    celery_app = Celery("hermes", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
    celery_app.conf.beat_schedule = {"hermes-publish-due": {"task": "hermes.publish_due", "schedule": 30.0}}
    celery_app.conf.timezone = "UTC"

    publish_due_task = celery_app.task(name="hermes.publish_due")(_publish_due_task)
