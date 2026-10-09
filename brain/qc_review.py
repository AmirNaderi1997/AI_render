"""QC Analyzer — deterministic checks + optional vision LLM review."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal, Optional

import numpy as np

from engine.schema import EditPlan

log = logging.getLogger(__name__)

Severity = Literal["error", "warning", "info"]

QC_ISSUE_TYPES = (
    "caption_on_face", "music_too_loud", "speech_too_quiet",
    "frozen_frame", "black_frame", "aspect_mismatch",
    "bad_framing", "low_quality", "caption_readability",
)


@dataclass
class QCIssue:
    segment_id: Optional[str]
    timestamp: float
    type: str
    severity: Severity
    description: str
    suggested_fix: str

    def to_dict(self) -> dict:
        return asdict(self)


def _load_image(path: str):
    """Load image as numpy array via Pillow (no cv2 dependency for basic ops)."""
    from PIL import Image
    return np.array(Image.open(path).convert("RGB"))


def _ssim_gray(a, b) -> float:
    """Simplified SSIM on grayscale numpy arrays."""
    from PIL import Image
    ga = np.array(Image.fromarray(a).convert("L"), dtype=np.float64)
    gb = np.array(Image.fromarray(b).convert("L"), dtype=np.float64)
    if ga.shape != gb.shape:
        return 0.0
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu_a, mu_b = ga.mean(), gb.mean()
    sig_a, sig_b = ga.var(), gb.var()
    sig_ab = ((ga - mu_a) * (gb - mu_b)).mean()
    num = (2 * mu_a * mu_b + c1) * (2 * sig_ab + c2)
    den = (mu_a**2 + mu_b**2 + c1) * (sig_a + sig_b + c2)
    return float(num / den)


def _detect_faces(image_path: str) -> list[dict]:
    """Detect faces using opencv-python-headless Haar cascade."""
    try:
        import cv2
        if not all(hasattr(cv2, name) for name in ("imread", "cvtColor", "CascadeClassifier", "data")):
            log.warning("OpenCV face detection API is unavailable; skipping face detection")
            return []
        img = cv2.imread(image_path)
        if img is None:
            return []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        h, w = img.shape[:2]
        return [{"x": int(x) / w, "y": int(y) / h,
                 "w": int(fw) / w, "h": int(fh) / h}
                for (x, y, fw, fh) in faces]
    except (ImportError, AttributeError):
        log.warning("OpenCV face detection is unavailable; skipping face detection")
        return []


def _caption_overlaps_face(
    plan: EditPlan,
    timestamp: float,
    faces: list[dict],
) -> bool:
    """Check if any caption at this timestamp overlaps with detected faces."""
    active_captions = [
        c for c in plan.captions
        if c.start <= timestamp <= c.end
    ]
    if not active_captions or not faces:
        return False

    for face in faces:
        face_bottom = face["y"] + face["h"]
        face_top = face["y"]
        for cap in active_captions:
            pos = getattr(cap, "position", "bottom")
            if pos == "bottom" and face_bottom > 0.75:
                return True
            if pos == "top" and face_top < 0.25:
                return True
    return False


def _find_segment_at_time(plan: EditPlan, t: float) -> Optional[str]:
    cursor = 0.0
    fps = plan.canvas.fps
    trans_map = {(tr.from_segment_id, tr.to_segment_id): tr for tr in plan.transitions}
    for i, seg in enumerate(plan.segments):
        seg_dur = round(seg.duration * fps) / fps
        if cursor <= t < cursor + seg_dur:
            return seg.id
        cursor += seg_dur
        if i < len(plan.segments) - 1:
            pair = (seg.id, plan.segments[i + 1].id)
            tr = trans_map.get(pair)
            if tr:
                cursor -= tr.duration_frames / fps
    return plan.segments[-1].id if plan.segments else None


def deterministic_checks(
    plan: EditPlan,
    frames: list[dict],
    audio_clips: list[dict],
) -> list[QCIssue]:
    """Run free deterministic QC checks."""
    issues: list[QCIssue] = []

    # 1. Caption-over-face detection
    for frame in frames:
        faces = _detect_faces(frame["path"])
        if _caption_overlaps_face(plan, frame["time"], faces):
            seg_id = _find_segment_at_time(plan, frame["time"])
            issues.append(QCIssue(
                segment_id=seg_id,
                timestamp=frame["time"],
                type="caption_on_face",
                severity="warning",
                description=f"Caption may overlap face at {frame['time']:.1f}s",
                suggested_fix="shift_caption_timing",
            ))

    # 2. Frozen frame detection (consecutive frames with SSIM > 0.99)
    sorted_frames = sorted(frames, key=lambda f: f["time"])
    for i in range(len(sorted_frames) - 1):
        a = _load_image(sorted_frames[i]["path"])
        b = _load_image(sorted_frames[i + 1]["path"])
        ssim = _ssim_gray(a, b)
        if ssim > 0.99:
            t = sorted_frames[i]["time"]
            seg_id = _find_segment_at_time(plan, t)
            issues.append(QCIssue(
                segment_id=seg_id,
                timestamp=t,
                type="frozen_frame",
                severity="warning",
                description=f"Possible frozen frame at {t:.1f}s (SSIM={ssim:.3f})",
                suggested_fix="add_zoom_effect",
            ))

    # 3. Black frame detection
    for frame in frames:
        img = _load_image(frame["path"])
        if img.mean() < 10:
            seg_id = _find_segment_at_time(plan, frame["time"])
            issues.append(QCIssue(
                segment_id=seg_id,
                timestamp=frame["time"],
                type="black_frame",
                severity="error",
                description=f"Black frame detected at {frame['time']:.1f}s",
                suggested_fix="trim_segment",
            ))

    # 4. Aspect ratio check
    if frames:
        img = _load_image(frames[0]["path"])
        h, w = img.shape[:2]
        expected_ratio = plan.canvas.width / plan.canvas.height
        actual_ratio = w / h
        if abs(actual_ratio - expected_ratio) > 0.05:
            issues.append(QCIssue(
                segment_id=None,
                timestamp=0,
                type="aspect_mismatch",
                severity="error",
                description=f"Aspect ratio mismatch: expected {expected_ratio:.2f}, got {actual_ratio:.2f}",
                suggested_fix="check_canvas_settings",
            ))

    # 5. Loudness checks on audio clips
    from engine.qc_sampler import measure_clip_lufs
    for clip in audio_clips:
        lufs = measure_clip_lufs(Path(clip["path"]))
        if lufs is not None and lufs < -30:
            seg_id = _find_segment_at_time(plan, clip["time"])
            # Only suggest music adjustment if music is present
            if plan.music:
                issues.append(QCIssue(
                    segment_id=seg_id,
                    timestamp=clip["time"],
                    type="speech_too_quiet",
                    severity="warning",
                    description=f"Audio very quiet at {clip['time']:.1f}s ({lufs:.1f} LUFS)",
                    suggested_fix="adjust_music_volume",
                ))

    # 6. Music vs speech loudness (if music present)
    if plan.music and audio_clips:
        speech_lufs = []
        for clip in audio_clips:
            lufs = measure_clip_lufs(Path(clip["path"]))
            if lufs is not None:
                speech_lufs.append(lufs)
        if speech_lufs:
            avg_speech = sum(speech_lufs) / len(speech_lufs)
            music_vol = plan.music.volume_db
            if music_vol > avg_speech + 3:
                issues.append(QCIssue(
                    segment_id=None,
                    timestamp=0,
                    type="music_too_loud",
                    severity="warning",
                    description=f"Music volume ({music_vol} dB) may overpower speech (avg {avg_speech:.1f} LUFS)",
                    suggested_fix="lower_music_volume",
                ))

    return issues


def vision_review(
    plan: EditPlan,
    frames: list[dict],
    max_frames: int = 8,
) -> list[QCIssue]:
    """Send keyframes to vision LLM for quality review."""
    from .llm import chat_vision

    selected = frames[:max_frames]
    if not selected:
        return []

    image_paths = [f["path"] for f in selected]
    time_labels = ", ".join(f"{f['time']:.1f}s ({f['label']})" for f in selected)

    system = (
        "You are a video quality reviewer. Analyze each frame and report issues.\n"
        "For each issue found, output a JSON object with:\n"
        '  frame_index (0-based), type (one of: bad_framing, low_quality, caption_readability),\n'
        '  severity ("error" or "warning"), description (brief), suggested_fix (brief)\n'
        "Output a JSON array of issues. Empty array if all frames look good."
    )
    user = (
        f"Review these {len(selected)} keyframes from a {plan.canvas.width}x{plan.canvas.height} "
        f"video at times: {time_labels}.\n"
        "Check: framing (subject centered, not cropped awkwardly), "
        "caption readability (if visible), overall visual quality."
    )

    try:
        result, _usage = chat_vision(
            system, user, images=image_paths,
            return_json=True, max_tokens=2048,
            timeout_seconds=180,
        )
        if not isinstance(result, list):
            raise ValueError("vision reviewer returned a non-list JSON response")

        issues = []
        for item in result:
            idx = item.get("frame_index", 0)
            if 0 <= idx < len(selected):
                frame = selected[idx]
                seg_id = _find_segment_at_time(plan, frame["time"])
                issues.append(QCIssue(
                    segment_id=seg_id,
                    timestamp=frame["time"],
                    type=item.get("type", "low_quality"),
                    severity=item.get("severity", "warning"),
                    description=item.get("description", "Vision LLM flagged this frame"),
                    suggested_fix=item.get("suggested_fix", "review_manually"),
                ))
        return issues
    except Exception as e:
        log.warning("vision QC review failed: %s", e)
        raise RuntimeError(f"vision QC review failed: {e}") from e
