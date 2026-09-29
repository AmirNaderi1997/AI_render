"""FastAPI backend for Rafiei AI Editor Stage 1.

Run: uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from engine.kdenlive import open_in_kdenlive
from engine.schema import validate_plan
from . import jobs as jobstore


log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Rafiei AI Editor", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _rescan_jobs_on_startup() -> None:
    n = jobstore.rescan()
    log.info("job registry rescan: loaded %d job(s) from %s", n, jobstore.JOBS_ROOT)


@app.get("/")
def health():
    return {"ok": True, "service": "rafiei-ai-editor", "stage": 1}


@app.get("/jobs")
def list_jobs():
    return [j.to_dict() for j in jobstore.list_jobs()]


@app.post("/jobs")
async def create_job(
    video: UploadFile = File(...),
    plan: Optional[UploadFile] = File(None),
    plan_text: Optional[str] = Form(None),
):
    job = jobstore.create_job()
    try:
        # UploadFile is a spooled temp file: stream it to disk, never .read() it whole.
        jobstore.save_raw(job, video.filename or "raw.mp4", video.file)
    except Exception as e:
        log.exception("upload failed for %r", video.filename)
        raise HTTPException(500, f"Could not save upload: {e}")

    plan_data: Optional[dict] = None
    try:
        if plan is not None:
            plan_data = json.loads((await plan.read()).decode("utf-8"))
        elif plan_text:
            plan_data = json.loads(plan_text)
    except ValueError as e:
        log.warning("invalid plan JSON: %s", e)
        raise HTTPException(422, f"Plan is not valid JSON: {e}")

    errors: list[str] = []
    if plan_data is not None:
        _, errors = jobstore.save_plan(job, plan_data)

    return {"job": job.to_dict(), "errors": errors}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    d = job.to_dict()
    plan_path = job.dir / "plan.json"
    if plan_path.exists():
        d["plan"] = json.loads(plan_path.read_text())
    return d


class PlanBody(BaseModel):
    plan: dict


@app.put("/jobs/{job_id}/plan")
def put_plan(job_id: str, body: PlanBody):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    _, errors = jobstore.save_plan(job, body.plan)
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=422)
    return {"ok": True}


@app.post("/jobs/{job_id}/validate")
def validate(job_id: str, body: PlanBody):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    _, errors = validate_plan(body.plan, base_dir=job.dir, check_media=True)
    return {"ok": not errors, "errors": errors}


@app.post("/jobs/{job_id}/render")
def render(job_id: str, preview: bool = False, loudnorm: bool = False):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if not (job.dir / "plan.json").exists():
        raise HTTPException(400, "no plan.json for this job")
    jobstore.start_render(job, preview=preview, loudnorm=loudnorm)
    return {"status": job.render.status}


@app.get("/jobs/{job_id}/render/status")
def render_status(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {
        "status": job.render.status,
        "progress": job.render.progress,
        "message": job.render.message,
        "output": job.render.output,
        "preview": job.render.preview,
        "versions": job.versions,
    }


@app.get("/jobs/{job_id}/raw")
def get_raw(job_id: str):
    job = jobstore.get(job_id)
    if not job or not job.raw_name:
        raise HTTPException(404, "no raw video")
    return FileResponse(job.dir / "raw" / job.raw_name)


@app.get("/jobs/{job_id}/exports/{fname}")
def get_export(job_id: str, fname: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    p = job.dir / "exports" / fname
    if not p.exists():
        raise HTTPException(404, "export not found")
    return FileResponse(p, filename=fname)


@app.get("/jobs/{job_id}/plan.json")
def download_plan(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    p = job.dir / "plan.json"
    if not p.exists():
        raise HTTPException(404, "no plan")
    return FileResponse(p, filename="plan.json", media_type="application/json")


@app.post("/jobs/{job_id}/open-kdenlive")
def open_kdenlive(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    mlt = job.dir / "project.mlt"
    if not mlt.exists():
        raise HTTPException(400, "project.mlt not built yet — render first")
    try:
        open_in_kdenlive(mlt)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "path": str(mlt)}
