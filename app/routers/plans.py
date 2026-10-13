"""Plans API routes."""
from __future__ import annotations

import json
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from engine.schema import validate_plan
from app import jobs as jobstore
from app.job_access import get_job_for_request, require_job_access
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["plans"])


class PlanBody(BaseModel):
    plan: dict


@router.put("/{job_id}/plan", dependencies=[Depends(require_job_access)])
def put_plan(job_id: str, body: PlanBody, request: Request, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    _, errors = jobstore.save_plan(job, body.plan)
    if errors:
        return JSONResponse({"ok": False, "errors": errors}, status_code=422)
    return {"ok": True}


class OperationsBody(BaseModel):
    operations: list[dict]
    dry_run: bool = False
    # Reject the batch if the plan moved past this version (optimistic locking).
    base_version: Optional[int] = None
    # Who is editing: user edits may change locked items, chat edits may not.
    source: Literal["user_ui", "chat"] = "user_ui"


@router.post("/{job_id}/operations", dependencies=[Depends(require_job_access)])
def post_operations(job_id: str, body: OperationsBody, request: Request):
    from pydantic import ValidationError
    from engine.operations import LockedError, OperationError
    job = get_job_for_request(request, job_id)
    try:
        return jobstore.apply_plan_operations(job, body.operations, source=body.source,
                                              dry_run=body.dry_run, base_version=body.base_version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        return JSONResponse({"ok": False, "errors": [e["msg"] for e in exc.errors()]}, status_code=422)
    except LockedError as exc:
        return JSONResponse({"ok": False, "errors": [str(exc)], "index": exc.index}, status_code=423)
    except OperationError as exc:
        return JSONResponse({"ok": False, "errors": [str(exc)], "index": exc.index}, status_code=422)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{job_id}/plan/versions", dependencies=[Depends(require_job_access)])
def get_plan_versions(job_id: str, request: Request):
    from app import plan_versions
    job = get_job_for_request(request, job_id)
    versions = plan_versions.list_versions(job)
    return {"current": versions[-1]["version"] if versions else None, "versions": versions}


@router.post("/{job_id}/plan/undo", dependencies=[Depends(require_job_access)])
def undo_plan(job_id: str, request: Request):
    job = get_job_for_request(request, job_id)
    try:
        return jobstore.undo_plan(job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{job_id}/validate")
def validate(job_id: str, body: PlanBody, request: Request):
    job = get_job_for_request(request, job_id)
    _, errors = validate_plan(body.plan, base_dir=job.dir, check_media=True)
    return {"ok": not errors, "errors": errors}


class GenerateBody(BaseModel):
    style: str = "rafiei_reel"
    instruction: str = ""
    whisper_model: Optional[str] = None
    language: Optional[str] = "fa"
    use_saved_transcript: bool = False
    transcribe_only: bool = False
    transcription_hint: str = ""
    asr_engine: Optional[str] = None
    caption_font: Optional[str] = None
    caption_font_id: Optional[str] = None
    style_id: Optional[str] = None
    style_version: Optional[int] = None
    output_kind: Literal["reel", "story", "post"] = "reel"
    transition_style: Literal["auto", "none", "crossfade", "directional", "zoom"] = "auto"
    transition_request: str = ""


@router.post("/{job_id}/generate-plan")
def generate_plan(job_id: str, request: Request, body: GenerateBody = GenerateBody(), db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    if not job.raw_name:
        raise HTTPException(400, "no raw video uploaded")
    try:
        jobstore.start_generate(
            job,
            style=body.style,
            instruction=body.instruction,
            whisper_model=body.whisper_model,
            language=body.language,
            use_saved_transcript=body.use_saved_transcript,
            transcribe_only=body.transcribe_only,
            transcription_hint=body.transcription_hint,
            asr_engine=body.asr_engine,
            caption_font=body.caption_font,
            caption_font_id=body.caption_font_id,
            style_id=body.style_id,
            style_version=body.style_version,
            output_kind=body.output_kind,
            transition_style=body.transition_style,
            transition_request=body.transition_request.strip(),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": job.generate.status, "stage": job.generate.stage}


@router.get("/{job_id}/generate-plan/status")
def generate_status(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    job = get_job_for_request(request, job_id)
    g = job.generate
    return {
        "status": g.status,
        "stage": g.stage,
        "message": g.message,
        "cost_usd": g.cost_usd,
        "input_tokens": g.input_tokens,
        "output_tokens": g.output_tokens,
        "model": g.model,
        "asr_engine": g.asr_engine,
        "asr_fallback_reason": g.asr_fallback_reason,
        "asr_audio_seconds": g.asr_audio_seconds,
        "asr_cost_usd": g.asr_cost_usd,
        "correction_model": g.correction_model,
    }


@router.get("/{job_id}/transcript")
def get_transcript(job_id: str, request: Request):
    job = get_job_for_request(request, job_id)
    p = job.dir / "transcript.json"
    if not p.exists():
        raise HTTPException(404, "transcript not generated yet")
    from brain.transcribe import effective_transcript
    return effective_transcript(job.dir)


class WordCorrection(BaseModel):
    index: int
    text: str
    start: Optional[float] = None
    end: Optional[float] = None


class CorrectionsBody(BaseModel):
    base_key: str
    words: list[WordCorrection]


@router.put("/{job_id}/transcript/corrections")
def put_transcript_corrections(job_id: str, body: CorrectionsBody, request: Request):
    job = get_job_for_request(request, job_id)
    if not (job.dir / "transcript.json").exists():
        raise HTTPException(404, "transcript not generated yet")
    from brain.transcribe import save_corrections
    try:
        return save_corrections(job.dir, body.base_key,
                                [item.model_dump() for item in body.words])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{job_id}/corrections")
def get_corrections(job_id: str, request: Request):
    """Return auto-correction suggestions from the last generate-plan run."""
    job = get_job_for_request(request, job_id)
    p = job.dir / "corrections.json"
    if not p.exists():
        return {"auto_applied": [], "suggestions": []}
    return json.loads(p.read_text())


class AcceptCorrectionBody(BaseModel):
    base_key: str
    index: int
    old: str
    new: str
    start: Optional[float] = None
    end: Optional[float] = None
    save_to_glossary: bool = True


@router.post("/{job_id}/corrections/accept")
def accept_correction(job_id: str, body: AcceptCorrectionBody, request: Request):
    """Accept one correction: save to transcript and optionally to glossary.yaml."""
    job = get_job_for_request(request, job_id)
    if not (job.dir / "transcript.json").exists():
        raise HTTPException(404, "transcript not generated yet")
    from brain.transcribe import save_corrections
    from brain.glossary import save_correction_to_glossary
    item: dict = {"index": body.index, "text": body.new}
    if body.start is not None:
        item["start"] = body.start
    if body.end is not None:
        item["end"] = body.end
    try:
        result = save_corrections(job.dir, body.base_key, [item])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if body.save_to_glossary:
        save_correction_to_glossary(body.old, body.new)
    return result


class RejectCorrectionBody(BaseModel):
    index: int
    old: str


@router.post("/{job_id}/corrections/reject")
def reject_correction(job_id: str, body: RejectCorrectionBody, request: Request):
    """Reject a correction — marks the word as reviewed so it won't be flagged again."""
    job = get_job_for_request(request, job_id)
    # Return 200 with an acknowledgement — the UI removes it from the list.
    # The word keeps its original text; we don't write to the transcript.
    return {"ok": True, "index": body.index, "word": body.old}


@router.get("/{job_id}/plan.json")
def download_plan(job_id: str, request: Request):
    job = get_job_for_request(request, job_id)
    if job.plan_data is None:
        raise HTTPException(404, "no plan")
    return JSONResponse(job.plan_data, headers={"Content-Disposition": 'attachment; filename="plan.json"'})
