"""QC Plan Patcher — turn QC issues into EditOperations and apply them.

Each auto-fix is expressed as a typed operation (engine.operations) applied as
an AI edit, so user-locked effects, captions and music are never changed. A fix
that does not apply cleanly is skipped; if the final plan fails validation the
original plan is returned unchanged.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from engine.effects import EFFECT_CATALOG
from engine.operations import (
    AddDuck, MoveCaptions, OpContext, OperationError, SetEffect, SetMusicVolume,
    apply_operations, output_duration,
)
from engine.schema import validate_plan

from .qc_review import QCIssue

log = logging.getLogger(__name__)

QC_CONTEXT = OpContext(actor="ai", respect_locks=True)
# Motions that read as "aggressive" framing and their gentler replacement.
_GENTLER_MOTION = {"punch": "slow_push", "hold_close": "steady", "pan_left": "steady", "pan_right": "steady",
                   "tilt_up": "steady", "tilt_down": "steady", "drift_diag": "steady"}


def patch_plan(
    plan_data: dict,
    issues: list[QCIssue],
    base_dir: Optional[str] = None,
) -> tuple[dict, list[dict]]:
    """Apply QC fixes to a plan dict. Returns (patched_plan_dict, changes_list).

    Each change is {type, segment_id, description, operation}.
    Only applies fixes that produce a valid plan.
    """
    patched = plan_data
    changes: list[dict] = []

    for issue in issues:
        proposal = _operation_for(patched, issue)
        if proposal is None:
            continue
        op, change_type, description = proposal
        try:
            patched = apply_operations(patched, [op], QC_CONTEXT).plan
        except OperationError as exc:
            log.info("QC fix %s skipped: %s", change_type, exc)
            continue
        changes.append({"type": change_type, "segment_id": issue.segment_id, "description": description,
                        "operation": op.model_dump(exclude_none=True)})

    if not changes:
        return plan_data, []
    bd = Path(base_dir) if base_dir else None
    _, errs = validate_plan(patched, base_dir=bd, check_media=bool(bd))
    if errs:
        log.warning("patched plan has validation errors, reverting: %s", errs)
        return plan_data, []
    return patched, changes


def _operation_for(plan: dict, issue: QCIssue):
    fix, seg_id, ts = issue.suggested_fix, issue.segment_id, issue.timestamp

    if fix == "shift_caption_timing" and issue.type == "caption_on_face":
        return (MoveCaptions(t_start=ts, t_end=ts + 1e-3, position="top"), "caption_shifted",
                f"Shifted caption away from face at {ts:.1f}s")

    if fix == "lower_music_volume" and issue.type == "music_too_loud" and plan.get("music"):
        old = plan["music"].get("volume_db", -14)
        new = max(-80.0, old - 4)
        return (SetMusicVolume(volume_db=new), "music_volume_lowered",
                f"Lowered music from {old} dB to {new} dB")

    if fix == "adjust_music_volume" and issue.type == "speech_too_quiet" and plan.get("music") and seg_id:
        start = round(max(0.0, ts - 1.5), 2)
        end = round(min(ts + 1.5, output_duration(plan)), 2)
        if end <= start:
            return None
        return (AddDuck(start=start, end=end, volume_db=-24), "duck_range_added",
                f"Added music duck at {ts:.1f}s for speech clarity")

    if fix == "add_zoom_effect" and issue.type == "frozen_frame" and seg_id:
        effect = _current_effect(plan, seg_id)
        if effect is None:
            if not _legacy_zoom_is_flat(plan, seg_id):
                return None
            target = "slow_push__neutral"
        else:
            spec = EFFECT_CATALOG.get(effect)
            if spec is None or spec["motion"] not in {"steady", "hold_close"}:
                return None  # already moving (or an extended effect)
            target = f"slow_push__{spec['light']}"
        return (SetEffect(segment_id=seg_id, effect=target), "zoom_added",
                f"Added slow zoom to frozen segment {seg_id}")

    if fix == "adjust_zoom_params" and issue.type == "bad_framing" and seg_id:
        effect = _current_effect(plan, seg_id)
        if effect is None:
            seg = next((s for s in plan.get("segments", []) if s["id"] == seg_id), None)
            if not seg or (seg.get("zoom") or {}).get("to", 1.0) <= 1.3:
                return None
            target = "slow_push__neutral"
        else:
            spec = EFFECT_CATALOG.get(effect)
            if spec is None or spec["motion"] not in _GENTLER_MOTION:
                return None
            target = f"{_GENTLER_MOTION[spec['motion']]}__{spec['light']}"
        return (SetEffect(segment_id=seg_id, effect=target), "zoom_adjusted",
                f"Adjusted zoom on segment {seg_id} for better framing")

    # black_frame / trim_segment: too risky to auto-trim; left for manual review.
    return None


def _current_effect(plan: dict, seg_id: str) -> Optional[str]:
    effect = next((e for e in plan.get("visual_effects") or [] if e.get("segment_id") == seg_id), None)
    if effect is None:
        return None
    from engine.effects import canonical_effect
    try:
        return canonical_effect(effect["type"])
    except ValueError:
        return effect["type"]  # extended (effects_v4) effect


def _legacy_zoom_is_flat(plan: dict, seg_id: str) -> bool:
    seg = next((s for s in plan.get("segments", []) if s["id"] == seg_id), None)
    if seg is None:
        return False
    zoom = seg.get("zoom") or {}
    return zoom.get("from", 1.0) == 1.0 and zoom.get("to", 1.0) == 1.0
