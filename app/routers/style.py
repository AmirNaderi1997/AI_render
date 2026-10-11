"""Style API routes."""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from app import jobs as jobstore
from app import style_store
from app import plan_style_store
from app.job_access import get_job_for_request

log = logging.getLogger(__name__)
MAX_REEL_BYTES = 500_000_000

router = APIRouter(prefix="/style", tags=["style"])
legacy_router = APIRouter(tags=["style"])


@legacy_router.get("/style-library")
def get_style_library():
    from engine.style_library import list_library
    return list_library()


@legacy_router.post("/style-library/snapshots")
async def import_style_snapshots(files: list[UploadFile] = File(...), name: str = Form("Snapshot style")):
    from engine.style_library import import_snapshots
    payloads = []
    for item in files:
        content = await item.read()
        if len(content) > 15_000_000:
            raise HTTPException(413, "each snapshot must be at most 15 MB")
        payloads.append((item.filename or "snapshot.jpg", content))
    try:
        return import_snapshots(payloads, name)
    except ValueError as exc: raise HTTPException(422, str(exc))
    except RuntimeError as exc: raise HTTPException(503, str(exc))


@legacy_router.post("/style-library/video")
async def import_style_video(file: UploadFile = File(...), name: str = Form("Video reference")):
    from engine.style_library import import_reference_video
    content = await file.read()
    if len(content) > 500_000_000: raise HTTPException(413, "reference video must be at most 500 MB")
    try: return import_reference_video(file.filename or "reference.mp4", content, name)
    except ValueError as exc: raise HTTPException(422, str(exc))
    except RuntimeError as exc: raise HTTPException(503, str(exc))


@legacy_router.post("/style-library/file")
async def import_style_file(file: UploadFile = File(...), name: str = Form("")):
    from engine.style_library import import_style_file as import_file
    content = await file.read()
    try: return import_file(file.filename or "style.yaml", content, name or None)
    except ValueError as exc: raise HTTPException(422, str(exc))


@legacy_router.put("/style-library/drafts/{draft_id}")
def update_style_draft(draft_id: str, body: dict):
    from engine.style_library import update_draft
    try: return update_draft(draft_id, body)
    except KeyError as exc: raise HTTPException(404, "style draft not found")
    except ValueError as exc: raise HTTPException(422, str(exc))


@legacy_router.post("/style-library/drafts/{draft_id}/approve")
def approve_style_draft(draft_id: str):
    from engine.style_library import approve_draft
    try: return approve_draft(draft_id)
    except KeyError: raise HTTPException(404, "style draft not found")
    except ValueError as exc: raise HTTPException(422, str(exc))


@legacy_router.post("/style-library/profiles/{style_id}/versions/{version}/draft")
def fork_style_profile(style_id: str, version: int):
    from engine.style_library import fork_profile
    try: return fork_profile(style_id, version)
    except KeyError: raise HTTPException(404, "approved style version not found")


@legacy_router.delete("/style-library/drafts/{draft_id}")
def delete_style_draft(draft_id: str):
    from engine.style_library import remove_draft
    try: return remove_draft(draft_id)
    except KeyError: raise HTTPException(404, "style draft not found")
    except ValueError as exc: raise HTTPException(409, str(exc))


@legacy_router.delete("/style-library/profiles/{style_id}/versions/{version}")
def delete_style_profile(style_id: str, version: int):
    from engine.style_library import remove_profile
    try:
        result = remove_profile(style_id, version)
        plan_style_store.clear_removed_style(style_id, version)
        return result
    except KeyError: raise HTTPException(404, "approved style version not found")


@router.get("/plan-selection")
def get_plan_style_selection(request: Request):
    """Get the signed-in user's default approved style for new plans."""
    selection = plan_style_store.get_selection(_uid(request))
    hidden = plan_style_store.get_default_hidden(_uid(request))
    if selection["style_id"] is None:
        return {**selection, "name": None, "default_hidden": hidden}
    from engine.style_library import get_profile
    try:
        profile = get_profile(selection["style_id"], selection["version"])
    except KeyError:
        selection = plan_style_store.clear_selection(_uid(request))
        return {**selection, "name": None, "default_hidden": hidden}
    return {**selection, "name": profile["name"], "default_hidden": hidden}


@router.put("/plan-default-visibility")
def update_plan_default_visibility(body: dict, request: Request):
    hidden = body.get("hidden")
    if not isinstance(hidden, bool):
        raise HTTPException(422, "hidden must be a boolean")
    uid = _uid(request)
    plan_style_store.set_default_hidden(uid, hidden)
    if hidden:
        selection = plan_style_store.get_selection(uid)
        if selection["style_id"] is None:
            plan_style_store.clear_selection(uid)
    return {"ok": True, "default_hidden": hidden}


@router.put("/plan-selection")
def update_plan_style_selection(body: dict, request: Request):
    """Set or clear the signed-in user's default approved style for new plans."""
    style_id = body.get("style_id")
    version = body.get("version")
    if style_id is None and version is None:
        selection = (plan_style_store.clear_selection(_uid(request)) if body.get("selected") is False
                     else plan_style_store.set_selection(_uid(request), None, None))
        return {"ok": True, **selection, "name": None, "default_hidden": plan_style_store.get_default_hidden(_uid(request))}
    if (not isinstance(style_id, str) or not re.fullmatch(r"[a-f0-9]{16}", style_id)
            or not isinstance(version, int) or isinstance(version, bool) or version < 1):
        raise HTTPException(422, "style_id and a positive version are required")
    from engine.style_library import get_profile
    try:
        profile = get_profile(style_id, version)
    except KeyError as exc:
        raise HTTPException(404, "approved style version not found") from exc
    selection = plan_style_store.set_selection(_uid(request), style_id, version)
    return {"ok": True, **selection, "name": profile["name"], "default_hidden": plan_style_store.get_default_hidden(_uid(request))}


@legacy_router.get("/style-library/evidence/{asset}")
def get_style_evidence(asset: str):
    from engine.style_library import evidence_path
    try: path = evidence_path(asset)
    except KeyError: raise HTTPException(404, "style evidence not found")
    return FileResponse(path)


def _uid(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return str(user.id)


def _rebuild(uid: str) -> dict | None:
    """Rebuild the user's learned profile from stored analyses; remove it when none remain."""
    from brain.style_profile import build_learned_profile
    analyses = style_store.list_references(uid)
    if not analyses:
        style_store.delete_profile(uid)
        return None
    previous = style_store.load_profile(uid)
    profile = build_learned_profile([{k: v for k, v in a.items() if k != "_file"} for a in analyses])
    profile["enabled"] = previous.get("enabled", True) if previous else True
    style_store.save_profile(uid, profile)
    return profile


def _analyze_and_store(uid: str, content: bytes, suffix: str, original_name: str) -> dict:
    from brain.style_learner import analyze_reference
    digest = hashlib.sha256(content).hexdigest()[:16]
    reel_path = style_store.refs_dir(uid) / f"ref-{digest}{suffix}"
    existed = reel_path.exists()
    reel_path.write_bytes(content)
    try:
        analysis = analyze_reference(reel_path)
        analysis["source_file"] = Path(original_name).name[:200] or reel_path.name
        style_store.add_reference(uid, digest, analysis)
    except BaseException:
        if not existed:
            reel_path.unlink(missing_ok=True)
        raise
    return {**analysis, "_file": digest}


@router.post("/analyze")
async def analyze_reference_reel(request: Request, file: UploadFile = File(...)):
    """Upload a reference reel, analyze it, and store the analysis for the current user."""
    uid = _uid(request)
    suffix = Path(file.filename or "reel.mp4").suffix.lower()
    if suffix not in style_store.VIDEO_SUFFIXES:
        raise HTTPException(422, f"unsupported video format: {suffix or 'none'}")
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_REEL_BYTES:
            raise HTTPException(413, "reference reel must be at most 500 MB")
        chunks.append(chunk)
    if not size:
        raise HTTPException(422, "Reference reel upload is empty")
    try:
        return await run_in_threadpool(_analyze_and_store, uid, b"".join(chunks), suffix, file.filename or "reel")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception:
        log.exception("reference reel analysis failed")
        raise HTTPException(500, "analysis failed; check that the file is a valid video")


@router.get("/profile")
def get_learned_style_profile(request: Request):
    """Current merged profile with confidence per metric."""
    uid = _uid(request)
    sample_count = len(style_store.list_references(uid))
    profile = style_store.load_profile(uid)
    if not profile:
        return {"exists": False, "active": False, "enabled": False, "metrics": {}, "confidence": {}, "sample_count": sample_count,
                "few_shot_examples": [], "preset_overrides": {}}
    learned = profile.get("learned_metrics", {})
    return {
        "exists": True,
        "active": learned.get("sufficient", False),
        "enabled": profile.get("enabled", True),
        "metrics": learned.get("metrics", {}),
        "confidence": learned.get("confidence", {}),
        "sample_count": sample_count,
        "few_shot_examples": profile.get("few_shot_examples", []),
        "preset_overrides": profile.get("preset_overrides", {}),
        "source_files": learned.get("source_files", []),
    }


@router.put("/profile")
def update_learned_profile(body: dict, request: Request):
    """Manual override of any metric in the learned profile."""
    uid = _uid(request)
    profile = style_store.load_profile(uid) or {
        "preset_overrides": {}, "learned_metrics": {}, "few_shot_examples": []
    }
    for key in ("preset_overrides", "metrics"):
        if key in body and not isinstance(body[key], dict):
            raise HTTPException(422, f"{key} must be an object")
    if "preset_overrides" in body:
        profile["preset_overrides"] = body["preset_overrides"]
    if "metrics" in body:
        profile.setdefault("learned_metrics", {})["metrics"] = body["metrics"]
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise HTTPException(422, "enabled must be a boolean")
        if body["enabled"] and not profile.get("learned_metrics", {}).get("sufficient", False):
            raise HTTPException(409, "at least 3 references are required to enable learned style")
        profile["enabled"] = body["enabled"]
    style_store.save_profile(uid, profile)
    return {"ok": True}


@router.post("/rebuild")
def rebuild_learned_profile(request: Request):
    """Rebuild the learned profile from all of the user's reference analyses."""
    profile = _rebuild(_uid(request))
    if profile is None:
        raise HTTPException(400, "no reference reels analyzed yet")
    return {
        "ok": True,
        "sample_count": profile["learned_metrics"]["sample_count"],
        "sufficient": profile["learned_metrics"]["sufficient"],
        "preset_overrides": profile["preset_overrides"],
    }


@router.post("/reset")
def reset_learned_profile(request: Request):
    """Remove the learned profile (reference analyses are kept for rebuilding)."""
    style_store.delete_profile(_uid(request))
    return {"ok": True}


@router.get("/feedback")
def get_feedback_summary(request: Request):
    """Feedback summary across the current user's jobs."""
    from brain.style_feedback import aggregate_all_feedback
    uid = _uid(request)
    dirs = [job.dir for job in jobstore.list_jobs() if str(job.user_id) == uid]
    return aggregate_all_feedback(dirs, persist=False)


@router.get("/examples")
def get_few_shot_examples(request: Request):
    """Current few-shot examples from the user's learned profile."""
    profile = style_store.load_profile(_uid(request))
    return {"examples": profile.get("few_shot_examples", []) if profile else []}


@legacy_router.post("/jobs/{job_id}/feedback")
def post_plan_feedback(job_id: str, body: dict, request: Request):
    """Log user edit feedback for a job."""
    job = get_job_for_request(request, job_id)
    from brain.style_feedback import log_feedback
    events = body.get("events", [])
    if not events:
        raise HTTPException(422, "no feedback events provided")
    count = log_feedback(job.dir, events)
    return {"ok": True, "logged": count}


@router.get("/analyses")
def list_reference_analyses(request: Request):
    """List the current user's reference reel analyses."""
    return {"analyses": style_store.list_references(_uid(request))}


@router.get("/analyses/{ref_id}/video")
def get_reference_video(ref_id: str, request: Request):
    """Stream a reference video only to the user who uploaded it."""
    path = style_store.reference_video_path(_uid(request), ref_id)
    if path is None:
        raise HTTPException(404, "reference video not found")
    return FileResponse(path, media_type="video/mp4" if path.suffix.lower() == ".mp4" else None)


@router.delete("/analyses/{ref_id}")
def delete_reference_analysis(ref_id: str, request: Request):
    """Delete one reference analysis and its video, then refresh the learned profile."""
    uid = _uid(request)
    if not style_store.delete_reference(uid, ref_id):
        raise HTTPException(404, "analysis not found")
    _rebuild(uid)
    return {"ok": True}
