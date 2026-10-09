"""Helpers for enforcing ownership on job scoped API routes."""
from __future__ import annotations

from fastapi import HTTPException, Request

from app import jobs as jobstore


def verify_job_owner(request: Request, job) -> None:
    """Allow legacy unowned jobs, and reject jobs owned by another user."""
    owner_id = getattr(job, "user_id", None)
    if owner_id is None:
        return
    user = getattr(request.state, "user", None)
    if user is None or str(getattr(user, "id", "")) != str(owner_id):
        raise HTTPException(403, "You do not have access to this job")


def get_job_for_request(request: Request, job_id: str, *, missing: str = "job not found"):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, missing)
    verify_job_owner(request, job)
    return job


def require_job_access(request: Request, job_id: str) -> None:
    """FastAPI dependency for routers whose every route is job scoped."""
    get_job_for_request(request, job_id)
