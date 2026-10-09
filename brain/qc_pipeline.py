"""QC Pipeline — orchestrate sample → review → patch → re-render."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

from engine.schema import EditPlan, validate_plan
from engine.qc_sampler import sample_keyframes, sample_audio_clips

from .qc_review import QCIssue, deterministic_checks, vision_review
from .qc_patch import patch_plan

log = logging.getLogger(__name__)

MAX_ROUNDS = 2


@dataclass
class QCRound:
    round_number: int
    issues: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class QCResult:
    status: str = "idle"  # idle | sampling | reviewing | patching | rendering | done | error
    message: str = ""
    current_round: int = 0
    rounds: list[QCRound] = field(default_factory=list)
    total_issues: int = 0
    fixed_issues: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def run_qc(
    job_dir: Path,
    video_path: Path,
    plan_data: dict,
    on_status: Optional[Callable[[str, str], None]] = None,
    skip_vision: bool = False,
) -> QCResult:
    """Run the full QC pipeline. Returns QCResult with all rounds.

    on_status(status, message) is called at each stage change.
    """
    result = QCResult(status="sampling", started_at=time.time())
    _notify(on_status, result)

    qc_dir = job_dir / "qc"
    qc_dir.mkdir(exist_ok=True)

    plan, errs = validate_plan(plan_data, base_dir=job_dir, check_media=False)
    if errs or not plan:
        result.status = "error"
        result.message = f"Plan validation failed: {'; '.join(errs)}"
        result.finished_at = time.time()
        return result

    current_plan_data = plan_data
    current_video = video_path

    for round_num in range(1, MAX_ROUNDS + 1):
        rd = QCRound(round_number=round_num, started_at=time.time())
        result.current_round = round_num

        # Sample
        result.status = "sampling"
        result.message = f"Round {round_num}: extracting keyframes…"
        _notify(on_status, result)

        frames_dir = qc_dir / f"round{round_num}" / "frames"
        audio_dir = qc_dir / f"round{round_num}" / "audio"

        plan, _ = validate_plan(current_plan_data, base_dir=job_dir, check_media=False)
        if not plan:
            result.status = "error"
            result.message = "Plan became invalid during QC"
            result.finished_at = time.time()
            return result

        try:
            frames = sample_keyframes(current_video, plan, frames_dir)
            audio_clips = sample_audio_clips(current_video, plan, audio_dir)
        except Exception as e:
            result.status = "error"
            result.message = f"Sampling failed: {e}"
            result.finished_at = time.time()
            return result

        # Review
        result.status = "reviewing"
        result.message = f"Round {round_num}: running checks…"
        _notify(on_status, result)

        issues = deterministic_checks(plan, frames, audio_clips)

        if not issues and not skip_vision:
            result.message = f"Round {round_num}: vision review…"
            _notify(on_status, result)
            try:
                vision_issues = vision_review(plan, frames)
                issues.extend(vision_issues)
            except Exception as e:
                log.warning("Vision QC review failed (continuing with deterministic checks): %s", e)

        rd.issues = [iss.to_dict() for iss in issues]
        result.total_issues += len(issues)

        if not issues:
            rd.finished_at = time.time()
            result.rounds.append(rd)
            result.status = "done"
            provider = (current_plan_data.get("generation_meta") or {}).get("provider", "")
            if provider.startswith("local_fixture"):
                result.message = (
                    f"Round {round_num}: technical checks passed; placeholder visuals "
                    "are not customer-ready"
                )
            else:
                result.message = f"Round {round_num}: no issues found — QC passed"
            result.finished_at = time.time()
            _save_result(qc_dir, result)
            _notify(on_status, result)
            return result

        # Patch
        result.status = "patching"
        result.message = f"Round {round_num}: applying {len(issues)} fix(es)…"
        _notify(on_status, result)

        patched_data, changes = patch_plan(
            current_plan_data, issues, base_dir=str(job_dir),
        )
        rd.changes = changes
        result.fixed_issues += len(changes)

        if not changes:
            rd.finished_at = time.time()
            result.rounds.append(rd)
            result.status = "done"
            result.message = f"Round {round_num}: {len(issues)} issue(s) found but no auto-fixes available"
            result.finished_at = time.time()
            _save_result(qc_dir, result)
            _notify(on_status, result)
            return result

        current_plan_data = patched_data
        rd.finished_at = time.time()
        result.rounds.append(rd)

        # If this is the last round, don't re-render here — caller handles it
        if round_num == MAX_ROUNDS:
            break

    result.status = "done"
    result.message = f"QC complete after {result.current_round} round(s): {result.total_issues} issue(s), {result.fixed_issues} fixed"
    result.finished_at = time.time()
    _save_result(qc_dir, result)
    _notify(on_status, result)
    return result


def get_patched_plan(job_dir: Path, plan_data: dict, issues_dicts: list[dict]) -> tuple[dict, list[dict]]:
    """Apply specific QC issues to a plan. Used by the apply endpoint."""
    issues = [
        QCIssue(
            segment_id=d.get("segment_id"),
            timestamp=d.get("timestamp", 0),
            type=d.get("type", ""),
            severity=d.get("severity", "warning"),
            description=d.get("description", ""),
            suggested_fix=d.get("suggested_fix", ""),
        )
        for d in issues_dicts
    ]
    return patch_plan(plan_data, issues, base_dir=str(job_dir))


def _notify(cb: Optional[Callable], result: QCResult) -> None:
    if cb:
        try:
            cb(result.status, result.message)
        except Exception:
            pass


def _save_result(qc_dir: Path, result: QCResult) -> None:
    (qc_dir / "result.json").write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
    )
