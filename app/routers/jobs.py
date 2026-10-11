"""Jobs API routes."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app import jobs as jobstore
from app.job_access import get_job_for_request
from .music import AUDIO_EXTENSIONS

log = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = str(request.state.user.id)
    result = []
    for job in jobstore.list_jobs(db=db):
        if job.user_id is not None and str(job.user_id) != user_id:
            continue
        item = job.to_dict()
        # Legacy rows can outlive local media artifacts. Keep the list response
        # shape intact, but don't advertise a poster for a missing render.
        output = item.get("render", {}).get("output")
        poster = Path(output).with_name(f"{Path(output).stem}_poster.jpg") if output else None
        if output and not (job.dir / "exports" / poster.name).is_file():
            item["render"]["output"] = None
        result.append(item)
    return result


@router.post("", status_code=201)
async def create_job(
    request: Request,
    video: UploadFile = File(...),
    plan: Optional[UploadFile] = File(None),
    plan_text: Optional[str] = Form(None),
    music: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    # Reject empty uploads before allocating a persistent job directory.
    try:
        video.file.seek(0, 2)
        video_size = video.file.tell()
        video.file.seek(0)
    except (AttributeError, OSError):
        video_size = None
    if video_size == 0:
        raise HTTPException(422, "Video upload is empty")
    # Allocate a media directory, but keep the database row out of the registry
    # until the complete source file has been streamed and verified.
    job = jobstore.create_job(user_id=request.state.user.id, db=db, persist=False)
    try:
        # UploadFile is a spooled temp file: stream it to disk, never .read() it whole.
        raw_path = jobstore.save_raw(
            job, video.filename or "raw.mp4", video.file, expected_size=video_size
        )
        if not raw_path.is_file() or (video_size is not None and raw_path.stat().st_size != video_size):
            raise OSError("upload file is incomplete")
    except BaseException as e:
        (job.dir / "raw" / Path(video.filename or "raw.mp4").name).unlink(missing_ok=True)
        with jobstore._lock:
            jobstore._jobs.pop(job.id, None)
        # A completed upload write is the only operation that can have inserted
        # this row; remove its directory when that write itself failed.
        import shutil
        shutil.rmtree(job.dir, ignore_errors=True)
        log.error("upload failed for job %s", job.id)
        if not isinstance(e, Exception):
            raise
        raise HTTPException(500, "Could not save upload") from e

    if music is not None:
        fname = music.filename or "music.mp3"
        ext = Path(fname).suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
            raise HTTPException(422, f"Music format not supported: {ext}. Use mp3, wav, ogg, aac, or m4a.")
        try:
            music.file.seek(0, 2)
            music_size = music.file.tell()
            music.file.seek(0)
        except (AttributeError, OSError):
            music_size = None
        if music_size == 0:
            raise HTTPException(422, "Music upload is empty")
        if music_size is not None and music_size > 100_000_000:
            raise HTTPException(413, "Music file must be at most 100 MB")
        jobstore.save_music(job, fname, music.file)

    plan_data: Optional[dict] = None
    try:
        if plan is not None:
            plan_data = json.loads((await plan.read()).decode("utf-8"))
        elif plan_text:
            plan_data = json.loads(plan_text)
    except ValueError as e:
        log.warning("invalid plan JSON for job %s", job.id)
        raise HTTPException(422, f"Plan is not valid JSON: {e}")

    errors: list[str] = []
    if plan_data is not None:
        _, errors = jobstore.save_plan(job, plan_data)

    return {"job": job.to_dict(), "errors": errors}


@router.get("/{job_id}")
def get_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    d = job.to_dict()
    if job.plan_data is not None:
        d["plan"] = job.plan_data
    transcript_path = job.dir / "transcript.json"
    if transcript_path.exists():
        d["has_transcript"] = True
    return d


@router.get("/{job_id}/raw")
def get_raw(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id, missing="no raw video")
    if not job.raw_name:
        # Generated jobs have a source clip but deliberately have no raw upload.
        plan = job.plan_data
        if plan:
            if plan.get("source_type") == "generated" and plan.get("source"):
                source = Path(plan["source"])
                source = (source if source.is_absolute() else job.dir / source).resolve()
                if source.is_relative_to(job.dir.resolve()) and source.is_file():
                    return FileResponse(source)
        raise HTTPException(404, "Source media missing")
    source = job.dir / "raw" / Path(job.raw_name).name
    if not source.is_file():
        raise HTTPException(404, "Source media missing")
    return FileResponse(source)
