"""Edit feedback learning — tracks user corrections in PlanReview.

Feedback events are append-only JSONL per job. Aggregation across jobs
produces a summary of which effects users keep vs replace, caption length
preferences, and segment duration adjustments.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from engine.schema import PROJECT_ROOT

log = logging.getLogger(__name__)

JOBS_ROOT = PROJECT_ROOT / "jobs"
FEEDBACK_SUMMARY_PATH = JOBS_ROOT / "style-library" / "learned" / "feedback_summary.json"
FEEDBACK_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
_feedback_lock = threading.Lock()


def log_feedback(job_dir: Path, events: list[dict]) -> int:
    """Append feedback events to the job's feedback.jsonl. Returns count written."""
    if not events:
        return 0
    path = job_dir / "feedback.jsonl"
    payload = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
    with _feedback_lock:
        # A process may have stopped during its last append. Add a separator so
        # the next valid event cannot be concatenated onto a truncated JSONL row.
        if path.is_file() and path.stat().st_size:
            with path.open("rb+") as existing:
                existing.seek(-1, 2)
                if existing.read(1) != b"\n":
                    existing.seek(0, 2)
                    existing.write(b"\n")
                    existing.flush()
        with path.open("a", encoding="utf-8") as f:
            f.write(payload)
    return len(events)


def load_job_feedback(job_dir: Path) -> list[dict]:
    """Load all feedback events for a job."""
    path = job_dir / "feedback.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def compute_plan_diff(original: dict, edited: dict) -> list[dict]:
    """Compute diff between AI-generated plan and user-edited plan.

    Returns a list of feedback events with change_type and details.
    """
    events: list[dict] = []

    orig_segs = {s["id"]: s for s in original.get("segments", [])}
    edit_segs = {s["id"]: s for s in edited.get("segments", [])}

    # Removed segments
    for sid in set(orig_segs) - set(edit_segs):
        events.append({"change_type": "segment_removed", "segment_id": sid})

    # Added segments
    for sid in set(edit_segs) - set(orig_segs):
        events.append({"change_type": "segment_added", "segment_id": sid})

    # Trimmed segments
    for sid in set(orig_segs) & set(edit_segs):
        o, e = orig_segs[sid], edit_segs[sid]
        o_in = o.get("in", o.get("in_", 0))
        o_out = o.get("out", 0)
        e_in = e.get("in", e.get("in_", 0))
        e_out = e.get("out", 0)
        if abs(o_in - e_in) > 0.05 or abs(o_out - e_out) > 0.05:
            events.append({
                "change_type": "segment_trimmed",
                "segment_id": sid,
                "original_duration": round(o_out - o_in, 3),
                "edited_duration": round(e_out - e_in, 3),
            })

    # Effect changes
    orig_effects = {e["segment_id"]: e["type"] for e in original.get("visual_effects", [])}
    edit_effects = {e["segment_id"]: e["type"] for e in edited.get("visual_effects", [])}
    for sid in set(orig_effects) | set(edit_effects):
        old_eff = orig_effects.get(sid)
        new_eff = edit_effects.get(sid)
        if old_eff != new_eff and old_eff and new_eff:
            events.append({
                "change_type": "effect_changed",
                "segment_id": sid,
                "old_effect": old_eff,
                "new_effect": new_eff,
            })

    # Caption edits
    orig_caps = original.get("captions", [])
    edit_caps = edited.get("captions", [])
    cap_diff = len(edit_caps) - len(orig_caps)
    if cap_diff > 0:
        events.append({"change_type": "captions_added", "count": cap_diff})
    elif cap_diff < 0:
        events.append({"change_type": "captions_removed", "count": -cap_diff})

    for i, (oc, ec) in enumerate(zip(orig_caps, edit_caps)):
        if oc.get("text") != ec.get("text"):
            events.append({
                "change_type": "caption_edited",
                "index": i,
                "old_text": oc.get("text", ""),
                "new_text": ec.get("text", ""),
            })

    # Zoom changes
    for sid in set(orig_segs) & set(edit_segs):
        oz = orig_segs[sid].get("zoom", {})
        ez = edit_segs[sid].get("zoom", {})
        if oz != ez:
            events.append({"change_type": "zoom_changed", "segment_id": sid})

    # B-roll changes
    orig_broll = original.get("broll", [])
    edit_broll = edited.get("broll", [])
    if len(orig_broll) != len(edit_broll):
        events.append({
            "change_type": "broll_changed",
            "original_count": len(orig_broll),
            "edited_count": len(edit_broll),
        })

    # Music changes
    if original.get("music") != edited.get("music"):
        events.append({"change_type": "music_changed"})

    return events


def aggregate_all_feedback(job_dirs: Optional[list[Path]] = None, *, persist: bool = True) -> dict:
    """Aggregate feedback across jobs (all jobs by default). Returns a summary dict.

    Only the all-jobs summary is cached to disk; scoped summaries pass persist=False.
    """
    all_events: list[dict] = []
    jobs_with_feedback = 0

    if job_dirs is None:
        job_dirs = sorted(JOBS_ROOT.iterdir())
    for job_dir in job_dirs:
        if not job_dir.is_dir():
            continue
        feedback_path = job_dir / "feedback.jsonl"
        if feedback_path.is_file():
            events = load_job_feedback(job_dir)
            if events:
                all_events.extend(events)
                jobs_with_feedback += 1

    if not all_events:
        return {
            "total_events": 0,
            "jobs_with_feedback": 0,
            "change_frequency": {},
            "effect_corrections": {},
            "segment_duration_bias": 0.0,
        }

    # Change frequency by type
    type_counts = Counter(e["change_type"] for e in all_events)

    # Effect corrections: which effects get replaced and with what
    effect_corrections: dict = defaultdict(lambda: Counter())
    for e in all_events:
        if e["change_type"] == "effect_changed":
            old = e.get("old_effect", "")
            new = e.get("new_effect", "")
            if old and new:
                effect_corrections[old][new] += 1

    # Segment duration bias: do users tend to shorten or lengthen?
    trim_deltas = []
    for e in all_events:
        if e["change_type"] == "segment_trimmed":
            orig = e.get("original_duration", 0)
            edited = e.get("edited_duration", 0)
            if orig > 0:
                trim_deltas.append(edited - orig)

    avg_delta = round(sum(trim_deltas) / len(trim_deltas), 3) if trim_deltas else 0.0

    # Caption edit frequency
    caption_edits = sum(1 for e in all_events if e["change_type"] == "caption_edited")
    total_captions = sum(1 for e in all_events if e["change_type"] in ("caption_edited", "captions_added", "captions_removed"))

    summary = {
        "total_events": len(all_events),
        "jobs_with_feedback": jobs_with_feedback,
        "change_frequency": dict(type_counts.most_common()),
        "effect_corrections": {
            old: dict(replacements.most_common(5))
            for old, replacements in effect_corrections.items()
        },
        "segment_duration_bias": avg_delta,
        "caption_edit_count": caption_edits,
    }

    if persist:
        FEEDBACK_SUMMARY_PATH.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return summary


def load_feedback_summary() -> Optional[dict]:
    """Load cached feedback summary."""
    if FEEDBACK_SUMMARY_PATH.is_file():
        return json.loads(FEEDBACK_SUMMARY_PATH.read_text(encoding="utf-8"))
    return None


def apply_feedback_to_effect_scores(scores: dict[str, float], summary: Optional[dict]) -> dict[str, float]:
    """Bias effect affinity scores based on feedback data.

    Boost families users keep, penalize ones they always replace.
    """
    if not summary or not summary.get("effect_corrections"):
        return scores

    corrections = summary["effect_corrections"]
    adjusted = dict(scores)

    for old_effect, replacements in corrections.items():
        family = old_effect.split("__")[0] if "__" in old_effect else old_effect
        total_replaced = sum(replacements.values())

        if total_replaced >= 3:
            if family in adjusted:
                adjusted[family] = max(0, adjusted[family] - 2.0)

        for new_effect, count in replacements.items():
            new_family = new_effect.split("__")[0] if "__" in new_effect else new_effect
            if count >= 2 and new_family in adjusted:
                adjusted[new_family] = adjusted[new_family] + 1.0

    return adjusted
