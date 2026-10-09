"""Qc API routes."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from app import jobs as jobstore
from app.job_access import get_job_for_request
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["qc"])


@router.post("/{job_id}/qc/run", status_code=202)
def run_qc(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    try:
        jobstore.start_qc(job)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": job.qc.status}


@router.get("/{job_id}/qc/status")
def qc_status(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    q = job.qc
    return {
        "status": q.status,
        "message": q.message,
        "current_round": q.current_round,
        "total_issues": q.total_issues,
        "fixed_issues": q.fixed_issues,
        "issues": q.issues,
        "changes": q.changes,
    }


class QCApplyBody(BaseModel):
    issue_indices: Optional[list[int]] = None


@router.post("/{job_id}/qc/apply")
def qc_apply(job_id: str, request: Request, body: QCApplyBody = QCApplyBody()):
    job = get_job_for_request(request, job_id)
    if not job.qc.issues:
        raise HTTPException(400, "no QC issues to apply")
    patched, changes = jobstore.apply_qc_fixes(job, body.issue_indices)
    return {"ok": True, "changes": changes, "plan": patched}
