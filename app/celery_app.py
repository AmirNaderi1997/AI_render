"""Celery application — available only when REDIS_URL is configured."""
from __future__ import annotations

import logging

from logging_config import configure_structured_logging

logger = logging.getLogger(__name__)

CELERY_AVAILABLE = False
celery = None


def _init_celery() -> None:
    global celery, CELERY_AVAILABLE
    try:
        from app.config import settings

        if not settings.REDIS_URL:
            logger.info("REDIS_URL not set — Celery disabled, using threading fallback")
            return

        from celery import Celery
        from celery.signals import setup_logging

        setup_logging.connect(lambda **kwargs: configure_structured_logging(), weak=False)

        celery = Celery(
            "airender",
            broker=settings.REDIS_URL,
            backend=settings.REDIS_URL,
            include=["app.tasks", "hermes.services.scheduler_service"],
        )
        celery.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            task_track_started=True,
            task_acks_late=True,
            task_reject_on_worker_lost=True,
            worker_prefetch_multiplier=1,
            result_expires=3600,
            task_default_queue="default",
            timezone="UTC",
            beat_schedule={
                "hermes-publish-due": {
                    "task": "hermes.publish_due",
                    "schedule": 30.0,
                },
            },
        )
        from hermes.services.scheduler_service import _publish_due_task

        celery.task(name="hermes.publish_due")(_publish_due_task)
        CELERY_AVAILABLE = True
        logger.info("Celery initialized with configured Redis broker")
    except Exception as exc:
        logger.warning(
            "CRITICAL: Celery initialization failed (%s); background jobs are falling back to in-process threading. "
            "Check Redis connectivity and Celery configuration.",
            type(exc).__name__,
        )


_init_celery()
