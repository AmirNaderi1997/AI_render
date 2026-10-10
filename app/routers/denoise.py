"""Denoise API routes."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from typing import Literal, Optional
from pydantic import BaseModel, Field
from app import jobs as jobstore
from app.job_access import require_job_access

router = APIRouter(prefix="/jobs", tags=["denoise"], dependencies=[Depends(require_job_access)])


class DenoiseStartBody(BaseModel):
    strength: float = Field(default=0.5, ge=0.0, le=1.0, allow_inf_nan=False)


class DenoiseTriggerBody(BaseModel):
    strength: Literal["light", "medium", "heavy"] = "medium"
    preserve_voice: bool = True


class DenoiseBypassBody(BaseModel):
    bypass: bool


class DenoiseAdjustBody(BaseModel):
    strength: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


def _sync_denoise_plan(job, state) -> None:
    """Persist the user's denoise decision in the plan consumed by MLT/Premiere."""
    if job.plan_data is None:
        return
    data = jobstore.load_plan(job)
    if state.approved:
        cleaned = Path(state.cleaned_audio or "").resolve()
        job_root = job.dir.resolve()
        if not cleaned.is_file():
            raise ValueError("approved cleaned audio file is missing")
        try:
            relative_audio = cleaned.relative_to(job_root).as_posix()
        except ValueError as exc:
            raise ValueError("cleaned audio must remain inside the job directory") from exc
        data["denoise"] = {
            "enabled": True,
            "strength": state.strength,
            "audio_file": relative_audio,
        }
    else:
        data.pop("denoise", None)
    _, errors = jobstore.save_plan(job, data)
    if errors:
        raise ValueError("could not save denoise choice: " + "; ".join(errors))


def _require_render_idle(job) -> None:
    if getattr(getattr(job, "render", None), "status", None) in {"queued", "running"}:
        raise HTTPException(409, "wait for the current render before reprocessing audio")


def _require_source_media(job) -> None:
    source = jobstore.source_media_path(job)
    if source is None or not source.is_file():
        raise HTTPException(404, "Source media missing")


@router.post("/{job_id}/denoise", status_code=202)
def denoise_trigger(job_id: str, body: DenoiseTriggerBody = DenoiseTriggerBody()):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    _require_source_media(job)
    _require_render_idle(job)
    from brain.denoise_manager import DenoiseState, get_state, start_denoise
    try:
        if get_state(job_id, job.dir).status != "processing":
            _sync_denoise_plan(job, DenoiseState())
        state = start_denoise(job_id, job.dir, level=body.strength,
                              preserve_voice=body.preserve_voice)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": state.status}


@router.get("/{job_id}/denoise/compare")
def denoise_compare(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    from brain.denoise_manager import get_state
    state = get_state(job_id, job.dir)
    if state.status != "ready" or not state.samples:
        raise HTTPException(404, "no denoised audio available yet")
    return {
        "original_url": f"/api/jobs/{job_id}/denoise/sample/original",
        "denoised_url": f"/api/jobs/{job_id}/denoise/sample/cleaned",
    }


@router.post("/{job_id}/denoise/apply")
def denoise_apply(job_id: str):
    return denoise_approve(job_id)


@router.post("/{job_id}/denoise/start")
def denoise_start(job_id: str, body: DenoiseStartBody = DenoiseStartBody()):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    _require_source_media(job)
    _require_render_idle(job)
    from brain.denoise_manager import DenoiseState, get_state, start_denoise
    try:
        if get_state(job_id, job.dir).status != "processing":
            _sync_denoise_plan(job, DenoiseState())
        state = start_denoise(job_id, job.dir, strength=body.strength)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"status": state.status}


@router.get("/{job_id}/denoise/status")
def denoise_status(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    from brain.denoise_manager import get_state
    state = get_state(job_id, job.dir)
    return state.to_dict()


@router.get("/{job_id}/denoise/samples")
def denoise_samples(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    from brain.denoise_manager import get_state
    state = get_state(job_id, job.dir)
    if not state.samples:
        raise HTTPException(404, "no samples available yet")
    return {
        "original_url": f"/api/jobs/{job_id}/denoise/sample/original",
        "cleaned_url": f"/api/jobs/{job_id}/denoise/sample/cleaned",
        "offset_s": state.samples.get("offset_s"),
        "duration_s": state.samples.get("duration_s"),
    }


@router.get("/{job_id}/denoise/sample/{which}")
def denoise_sample(job_id: str, which: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    from brain.denoise_manager import get_state
    state = get_state(job_id, job.dir)
    if not state.samples:
        raise HTTPException(404, "no samples available")
    if which == "original":
        path = state.samples.get("original_sample")
    elif which == "cleaned":
        path = state.samples.get("cleaned_sample")
    else:
        raise HTTPException(400, "which must be 'original' or 'cleaned'")
    if not path or not Path(path).is_file():
        raise HTTPException(404, "sample file not found")
    return FileResponse(Path(path), media_type="audio/wav")


@router.post("/{job_id}/denoise/approve")
def denoise_approve(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    from brain.denoise_manager import approve_cleaned
    try:
        state = approve_cleaned(job_id, job.dir)
        _sync_denoise_plan(job, state)
    except ValueError as exc:
        from brain.denoise_manager import set_bypass
        set_bypass(job_id, job.dir, True)
        raise HTTPException(400, str(exc)) from exc
    return state.to_dict()


@router.post("/{job_id}/denoise/bypass")
def denoise_bypass(job_id: str, body: DenoiseBypassBody):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    from brain.denoise_manager import set_bypass
    state = set_bypass(job_id, job.dir, body.bypass)
    try:
        _sync_denoise_plan(job, state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return state.to_dict()


@router.post("/{job_id}/denoise/adjust")
def denoise_adjust(job_id: str, body: DenoiseAdjustBody):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    _require_render_idle(job)
    from brain.denoise_manager import DenoiseState, get_state, adjust_strength
    try:
        if get_state(job_id, job.dir).status != "processing":
            _sync_denoise_plan(job, DenoiseState())
        state = adjust_strength(job_id, job.dir, body.strength)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": state.status}


@router.get("/{job_id}/audio/{filename}")
def get_audio_file(job_id: str, filename: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    safe_name = Path(filename).name
    path = job.dir / "audio" / safe_name
    if not path.is_file():
        raise HTTPException(404, "audio file not found")
    return FileResponse(path)
