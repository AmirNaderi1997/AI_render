"""Celery wrappers for the existing background job functions."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from app.celery_app import CELERY_AVAILABLE, celery
from app.config import settings
from request_context import request_id_var

logger = logging.getLogger(__name__)
_NON_RETRYABLE = (ValueError, KeyError, FileNotFoundError)


def _execute(task, name: str, job_id: str, operation, on_error=None) -> None:
    headers = getattr(task.request, "headers", None) or {}
    token = request_id_var.set(headers.get("request_id"))
    logger.info("%s started for job %s", name, job_id)
    try:
        operation()
    except Exception as exc:
        logger.error("task_failed name=%s job=%s error_type=%s", name, job_id, type(exc).__name__)
        if on_error is not None:
            on_error(exc)
        if isinstance(exc, _NON_RETRYABLE):
            raise
        raise task.retry(exc=exc, countdown=min(30 * (2 ** task.request.retries), 300))
    else:
        logger.info("%s completed for job %s", name, job_id)
    finally:
        request_id_var.reset(token)


def _job(job_id: str):
    from app.jobs import get

    job = get(job_id)
    if job is None:
        raise FileNotFoundError(f"job not found: {job_id}")
    return job


def _mark_job_error(job_id: str, state_name: str, exc: Exception) -> None:
    from app.jobs import get, _write_status

    job = get(job_id)
    if job is None:
        return
    state = getattr(job, state_name)
    state.status = "error"
    state.message = "Processing failed. Check the worker logs and dead letter record."
    state.finished_at = time.time()
    _write_status(job)


if CELERY_AVAILABLE:
    from celery.signals import task_failure

    @task_failure.connect(weak=False)
    def record_dead_letter(sender=None, task_id=None, args=None, exception=None, **kwargs):
        """Persist exhausted and non-retryable tasks without arguments or exception text."""
        if not task_id or sender is None:
            return
        directory = Path(settings.JOBS_DIR).expanduser() / "dead_letters"
        directory.mkdir(parents=True, exist_ok=True)
        record = {"task_id": task_id, "task": sender.name,
                  "job_id": args[0] if args and isinstance(args[0], str) else None,
                  "error_type": type(exception).__name__, "failed_at": time.time()}
        target = directory / f"{task_id}.json"
        temporary = directory / f".{task_id}.{os.getpid()}.tmp"
        temporary.write_text(json.dumps(record))
        temporary.replace(target)

    @celery.task(bind=True, name="airender.run_render", max_retries=2, default_retry_delay=30)
    def task_run_render(self, job_id: str, preview: bool, loudnorm: bool) -> None:
        from app.jobs import _run_job

        _execute(
            self, "render", job_id,
            lambda: _run_job(_job(job_id), preview, loudnorm, raise_errors=True),
            lambda exc: _mark_job_error(job_id, "render", exc),
        )


    @celery.task(bind=True, name="airender.mix_music", max_retries=2, default_retry_delay=30)
    def task_mix_music(self, job_id: str) -> None:
        from app.jobs import _run_mix

        _execute(
            self, "music mix", job_id,
            lambda: _run_mix(_job(job_id), raise_errors=True),
            lambda exc: _mark_job_error(job_id, "music", exc),
        )


    @celery.task(bind=True, name="airender.generate_plan", max_retries=2, default_retry_delay=30)
    def task_generate_plan(self, job_id: str) -> None:
        from app.jobs import _run_generate

        def run() -> None:
            job = _job(job_id)
            request = json.loads((job.dir / "generation_request.json").read_text())
            _run_generate(job, **request, raise_errors=True)

        _execute(
            self, "plan generation", job_id, run,
            lambda exc: _mark_job_error(job_id, "generate", exc),
        )


    @celery.task(bind=True, name="airender.run_qc", max_retries=2, default_retry_delay=30)
    def task_run_qc(self, job_id: str) -> None:
        from app.jobs import _run_qc

        _execute(
            self, "QC", job_id,
            lambda: _run_qc(_job(job_id), raise_errors=True),
            lambda exc: _mark_job_error(job_id, "qc", exc),
        )


    @celery.task(bind=True, name="airender.denoise_audio", max_retries=2, default_retry_delay=30)
    def task_denoise_audio(self, job_id: str, settings_dict: dict) -> None:
        from brain.denoise_manager import get_state, _run_denoise

        def run() -> None:
            job_dir = Path(settings_dict["job_dir"])
            get_state(job_id, job_dir)
            _run_denoise(
                job_id, job_dir, float(settings_dict["strength"]), raise_errors=True,
                level=settings_dict.get("level"),
                preserve_voice=settings_dict.get("preserve_voice", True),
            )

        _execute(self, "denoise", job_id, run)


    @celery.task(bind=True, name="airender.generate_content", max_retries=2, default_retry_delay=30)
    def task_generate_content(self, job_id: str, params: dict) -> None:
        from brain.content_creator import _run_generation

        def run() -> None:
            _job(job_id)
            _run_generation(job_id, params["provider_name"], raise_errors=True)

        _execute(
            self, "content generation", job_id, run,
        )
