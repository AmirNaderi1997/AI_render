"""QC Plan Patcher — apply suggested fixes from QC issues to an EditPlan."""
from __future__ import annotations

import copy
import logging
from typing import Optional

from engine.schema import EditPlan, validate_plan

from .qc_review import QCIssue

log = logging.getLogger(__name__)


def patch_plan(
    plan_data: dict,
    issues: list[QCIssue],
    base_dir: Optional[str] = None,
) -> tuple[dict, list[dict]]:
    """Apply QC fixes to a plan dict. Returns (patched_plan_dict, changes_list).

    Each change is {type, segment_id, description}.
    Only applies fixes that produce a valid plan.
    """
    patched = copy.deepcopy(plan_data)
    changes: list[dict] = []

    for issue in issues:
        fix = issue.suggested_fix
        seg_id = issue.segment_id

        if fix == "shift_caption_timing" and issue.type == "caption_on_face":
            _shift_caption_at(patched, issue.timestamp)
            changes.append({
                "type": "caption_shifted",
                "segment_id": seg_id,
                "description": f"Shifted caption away from face at {issue.timestamp:.1f}s",
            })

        elif fix == "lower_music_volume" and issue.type == "music_too_loud":
            if patched.get("music"):
                old_vol = patched["music"].get("volume_db", -14)
                patched["music"]["volume_db"] = old_vol - 4
                changes.append({
                    "type": "music_volume_lowered",
                    "segment_id": None,
                    "description": f"Lowered music from {old_vol} dB to {old_vol - 4} dB",
                })

        elif fix == "adjust_music_volume" and issue.type == "speech_too_quiet":
            if patched.get("music") and seg_id:
                _add_duck_range(patched, issue.timestamp)
                changes.append({
                    "type": "duck_range_added",
                    "segment_id": seg_id,
                    "description": f"Added music duck at {issue.timestamp:.1f}s for speech clarity",
                })

        elif fix == "add_zoom_effect" and issue.type == "frozen_frame":
            if seg_id:
                _add_zoom_to_segment(patched, seg_id)
                changes.append({
                    "type": "zoom_added",
                    "segment_id": seg_id,
                    "description": f"Added slow zoom to frozen segment {seg_id}",
                })

        elif fix == "trim_segment" and issue.type == "black_frame":
            pass  # Too risky to auto-trim; leave for manual review

        elif fix == "adjust_zoom_params" and issue.type == "bad_framing":
            if seg_id:
                _adjust_zoom(patched, seg_id)
                changes.append({
                    "type": "zoom_adjusted",
                    "segment_id": seg_id,
                    "description": f"Adjusted zoom on segment {seg_id} for better framing",
                })

    # Validate the patched plan
    from pathlib import Path
    bd = Path(base_dir) if base_dir else None
    result, errs = validate_plan(patched, base_dir=bd, check_media=bool(bd))
    if errs:
        log.warning("patched plan has validation errors, reverting: %s", errs)
        return plan_data, []

    return patched, changes


def _shift_caption_at(plan_data: dict, timestamp: float) -> None:
    """Move captions that overlap the timestamp to avoid face area."""
    for cap in plan_data.get("captions", []):
        if cap.get("start", 0) <= timestamp <= cap.get("end", 0):
            cap["position"] = "top"


def _add_duck_range(plan_data: dict, timestamp: float, window: float = 3.0) -> None:
    music = plan_data.get("music")
    if not music:
        return
    duck = music.setdefault("duck", [])
    start = max(0, timestamp - window / 2)
    end = timestamp + window / 2
    # Don't add overlapping duck ranges
    for d in duck:
        if not (end <= d["start"] or start >= d["end"]):
            return
    duck.append({"start": round(start, 2), "end": round(end, 2), "volume_db": -24})


def _add_zoom_to_segment(plan_data: dict, seg_id: str) -> None:
    segments = plan_data.get("segments", [])
    seg = next((s for s in segments if s["id"] == seg_id), None)
    if not seg:
        return
    zoom = seg.get("zoom", {})
    if zoom.get("from", 1.0) == 1.0 and zoom.get("to", 1.0) == 1.0:
        seg["zoom"] = {"from": 1.0, "to": 1.15}


def _adjust_zoom(plan_data: dict, seg_id: str) -> None:
    segments = plan_data.get("segments", [])
    seg = next((s for s in segments if s["id"] == seg_id), None)
    if not seg:
        return
    zoom = seg.get("zoom", {})
    # Pull back zoom if it's too aggressive
    if zoom.get("to", 1.0) > 1.3:
        seg["zoom"] = {"from": zoom.get("from", 1.0), "to": 1.2}
