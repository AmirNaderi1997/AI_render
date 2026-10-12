"""Render API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from engine.kdenlive import open_in_kdenlive
from app import jobs as jobstore
from app.job_access import get_job_for_request
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["render"])


@router.post("/{job_id}/render", status_code=202)
def render(job_id: str, request: Request, preview: bool = False, loudnorm: bool = True, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    if job.plan_data is None:
        raise HTTPException(400, "no plan.json for this job")
    try:
        jobstore.start_render(job, preview=preview, loudnorm=loudnorm)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": job.render.status}


@router.get("/{job_id}/render/status")
def render_status(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    return {
        "status": job.render.status,
        "progress": job.render.progress,
        "message": job.render.message,
        "output": job.render.output,
        "preview": job.render.preview,
        "technical_qc": job.render.technical_qc,
        "versions": job.versions,
    }


@router.get("/{job_id}/exports/{fname}")
def get_export(job_id: str, fname: str, request: Request):
    job = get_job_for_request(request, job_id)
    p = job.dir / "exports" / fname
    if not p.exists():
        raise HTTPException(404, "export not found")
    return FileResponse(p, filename=fname)


@router.post("/{job_id}/open-kdenlive")
def open_kdenlive(job_id: str, request: Request):
    job = get_job_for_request(request, job_id)
    mlt = job.dir / "project.mlt"
    if not mlt.exists():
        raise HTTPException(400, "project.mlt not built yet — render first")
    try:
        open_in_kdenlive(mlt)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "path": str(mlt)}
