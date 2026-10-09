"""Style API routes."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from app import jobs as jobstore
from app.job_access import get_job_for_request

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
    try: return remove_profile(style_id, version)
    except KeyError: raise HTTPException(404, "approved style version not found")


@legacy_router.get("/style-library/evidence/{asset}")
def get_style_evidence(asset: str):
    from engine.style_library import evidence_path
    try: path = evidence_path(asset)
    except KeyError: raise HTTPException(404, "style evidence not found")
    return FileResponse(path)


@router.post("/analyze")
async def analyze_reference_reel(file: UploadFile = File(...)):
    """Upload a reference reel, run analysis, return StyleProfile."""
    from brain.style_learner import analyze_reference
    from brain.style_profile import LEARNED_PROFILES_DIR

    content = await file.read()
    if not content:
        raise HTTPException(422, "Reference reel upload is empty")
    if len(content) > 500_000_000:
        raise HTTPException(413, "reference reel must be at most 500 MB")
    suffix = Path(file.filename or "reel.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        raise HTTPException(422, f"unsupported video format: {suffix}")

    refs_dir = LEARNED_PROFILES_DIR / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)

    import hashlib
    digest = hashlib.sha256(content).hexdigest()[:16]
    reel_path = refs_dir / f"ref-{digest}{suffix}"
    reel_path.write_bytes(content)

    try:
        profile = analyze_reference(reel_path)
    except Exception as exc:
        raise HTTPException(500, f"analysis failed: {exc}")

    # Save individual analysis
    analysis_path = refs_dir / f"ref-{digest}.json"
    import json as _json
    analysis_path.write_text(_json.dumps(profile, ensure_ascii=False, indent=2))
    return profile


@router.get("/profile")
def get_learned_style_profile():
    """Get current merged profile with confidence per metric."""
    from brain.style_profile import load_learned_profile, LEARNED_PROFILES_DIR
    import json as _json

    refs_dir = LEARNED_PROFILES_DIR / "references"
    sample_count = len(list(refs_dir.glob("ref-*.json"))) if refs_dir.exists() else 0
    profile = load_learned_profile()
    if not profile:
        return {"active": False, "enabled": False, "metrics": {}, "confidence": {}, "sample_count": sample_count,
                "few_shot_examples": [], "preset_overrides": {}}

    return {
        "active": profile.get("learned_metrics", {}).get("sufficient", False),
        "enabled": profile.get("enabled", True),
        "metrics": profile.get("learned_metrics", {}).get("metrics", {}),
        "confidence": profile.get("learned_metrics", {}).get("confidence", {}),
        "sample_count": sample_count,
        "few_shot_examples": profile.get("few_shot_examples", []),
        "preset_overrides": profile.get("preset_overrides", {}),
        "source_files": profile.get("learned_metrics", {}).get("source_files", []),
    }


@router.put("/profile")
def update_learned_profile(body: dict):
    """Manual override of any metric in the learned profile."""
    from brain.style_profile import load_learned_profile, save_learned_profile

    profile = load_learned_profile() or {
        "preset_overrides": {}, "learned_metrics": {}, "few_shot_examples": []
    }
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
    save_learned_profile(profile)
    return {"ok": True}


@router.post("/rebuild")
def rebuild_learned_profile():
    """Rebuild the learned profile from all reference analyses."""
    from brain.style_profile import (
        LEARNED_PROFILES_DIR, build_learned_profile, save_learned_profile,
    )
    import json as _json

    refs_dir = LEARNED_PROFILES_DIR / "references"
    if not refs_dir.exists():
        raise HTTPException(400, "no reference reels analyzed yet")

    analyses = []
    for p in sorted(refs_dir.glob("ref-*.json")):
        try:
            analyses.append(_json.loads(p.read_text()))
        except Exception:
            continue

    if not analyses:
        raise HTTPException(400, "no valid reference analyses found")

    from brain.style_profile import load_learned_profile
    previous = load_learned_profile()
    profile = build_learned_profile(analyses)
    profile["enabled"] = previous.get("enabled", True) if previous else True
    save_learned_profile(profile)
    return {
        "ok": True,
        "sample_count": len(analyses),
        "sufficient": profile["learned_metrics"]["sufficient"],
        "preset_overrides": profile["preset_overrides"],
    }


@router.post("/reset")
def reset_learned_profile():
    """Reset to default rafiei_reel.yaml — removes learned profile."""
    from brain.style_profile import LEARNED_PROFILES_DIR
    profile_path = LEARNED_PROFILES_DIR / "learned.json"
    if profile_path.exists():
        profile_path.unlink()
    return {"ok": True}


@router.get("/feedback")
def get_feedback_summary():
    """Aggregated feedback summary across all jobs."""
    from brain.style_feedback import aggregate_all_feedback
    return aggregate_all_feedback()


@router.get("/examples")
def get_few_shot_examples():
    """Current few-shot examples from learned profile."""
    from brain.style_profile import load_learned_profile
    profile = load_learned_profile()
    if not profile:
        return {"examples": []}
    return {"examples": profile.get("few_shot_examples", [])}


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
def list_reference_analyses():
    """List all individual reference reel analyses."""
    from brain.style_profile import LEARNED_PROFILES_DIR
    import json as _json

    refs_dir = LEARNED_PROFILES_DIR / "references"
    if not refs_dir.exists():
        return {"analyses": []}

    analyses = []
    for p in sorted(refs_dir.glob("ref-*.json")):
        try:
            data = _json.loads(p.read_text())
            data["_file"] = p.name
            analyses.append(data)
        except Exception:
            continue
    return {"analyses": analyses}


@router.delete("/analyses/{filename}")
def delete_reference_analysis(filename: str):
    """Delete a single reference analysis and its video."""
    from brain.style_profile import LEARNED_PROFILES_DIR

    refs_dir = LEARNED_PROFILES_DIR / "references"
    path = (refs_dir / Path(filename).name).resolve()
    if path.parent != refs_dir.resolve() or path.suffix != ".json" or not path.name.startswith("ref-") or not path.is_file():
        raise HTTPException(404, "analysis not found")
    path.unlink()
    # Also remove corresponding video files
    stem = path.stem
    for vf in refs_dir.glob(f"{stem}.*"):
        if vf.suffix in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
            vf.unlink(missing_ok=True)
    return {"ok": True}
