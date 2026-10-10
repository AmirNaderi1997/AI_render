"""Denoise workflow manager — coordinates background denoise and state persistence."""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from app.celery_app import CELERY_AVAILABLE
from request_context import celery_request_headers


@dataclass
class DenoiseState:
    status: str = "idle"  # idle | processing | ready | error | skipped
    strength: float = 0.5
    level: Optional[str] = None
    preserve_voice: bool = True
    denoised_video: Optional[str] = None
    original_audio: Optional[str] = None
    cleaned_audio: Optional[str] = None
    approved: bool = False
    bypass: bool = False
    message: str = ""
    samples: Optional[dict] = None
    quality: Optional[dict] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DenoiseState":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


_states: dict[str, DenoiseState] = {}
_lock = threading.Lock()


def _state_path(job_dir: Path) -> Path:
    return job_dir / "audio" / "denoise_state.json"


def _save_state(job_dir: Path, state: DenoiseState) -> None:
    p = _state_path(job_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state.to_dict(), indent=2))


def _load_state(job_dir: Path) -> DenoiseState:
    p = _state_path(job_dir)
    if p.is_file():
        state = DenoiseState.from_dict(json.loads(p.read_text()))
        if state.status == "processing" and not CELERY_AVAILABLE:
            # A daemon worker cannot survive a FastAPI process restart. Mark its
            # persisted state retryable rather than polling "processing" forever.
            state.status = "error"
            state.message = "Denoise was interrupted by an app restart. Start it again to retry."
            state.finished_at = time.time()
        return state
    return DenoiseState()


def get_state(job_id: str, job_dir: Path) -> DenoiseState:
    with _lock:
        if CELERY_AVAILABLE or job_id not in _states:
            _states[job_id] = _load_state(job_dir)
            if _states[job_id].status == "error" and "interrupted by an app restart" in _states[job_id].message:
                _save_state(job_dir, _states[job_id])
        return _states[job_id]


def start_denoise(job_id: str, job_dir: Path, strength: float = 0.5,
                  level: Optional[str] = None, preserve_voice: bool = True) -> DenoiseState:
    """Start background denoise. Returns current state."""
    job_dir = Path(job_dir)
    if level is not None:
        from engine.denoise import preset_strength
        strength = preset_strength(level)
    strength = float(strength)
    if not math.isfinite(strength) or not 0.0 <= strength <= 1.0:
        raise ValueError("denoise strength must be between 0 and 1")
    with _lock:
        state = _load_state(job_dir) if CELERY_AVAILABLE else _states.get(job_id) or _load_state(job_dir)
        if state.status == "processing":
            return state
        state = DenoiseState(
            status="processing",
            strength=strength,
            level=level,
            preserve_voice=preserve_voice,
            started_at=time.time(),
        )
        _states[job_id] = state
        _save_state(job_dir, state)

    if CELERY_AVAILABLE:
        from app.tasks import task_denoise_audio
        task_denoise_audio.apply_async(args=(job_id, {
            "job_dir": str(job_dir), "strength": strength,
            "level": level, "preserve_voice": preserve_voice,
        }), headers=celery_request_headers())
    else:
        threading.Thread(
            target=_run_denoise,
            args=(job_id, job_dir, strength),
            kwargs={"level": level, "preserve_voice": preserve_voice},
            daemon=True,
        ).start()
    return state


def _run_denoise(job_id: str, job_dir: Path, strength: float, *, raise_errors: bool = False,
                 level: Optional[str] = None, preserve_voice: bool = True) -> None:
    from engine.denoise import (
        extract_speech_audio, denoise_speech, generate_ab_samples,
        measure_quality, detect_silence, remux_with_video,
    )

    try:
        audio_dir = job_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # The plan's source is the video whose cuts will be used by MLT.
        plan_path = job_dir / "plan.json"
        source = json.loads(plan_path.read_text()).get("source") if plan_path.is_file() else None
        if source:
            candidate = Path(source)
            raw_path = candidate if candidate.is_absolute() else job_dir / candidate
        else:
            raw_dir = job_dir / "raw"
            raws = sorted(p for p in raw_dir.glob("*") if p.is_file()) if raw_dir.is_dir() else []
            if not raws:
                raise FileNotFoundError("no raw video found")
            raw_path = raws[0]

        # Extract speech
        try:
            original = extract_speech_audio(raw_path, out_dir=audio_dir)
        except RuntimeError as exc:
            if "no audio stream found" not in str(exc):
                raise
            with _lock:
                state = _states[job_id]
                state.status = "skipped"
                state.message = "Source has no audio track; denoise skipped"
                state.finished_at = time.time()
                _save_state(job_dir, state)
            return

        # Check for silence
        if detect_silence(original):
            with _lock:
                state = _states[job_id]
                state.status = "skipped"
                state.message = "No speech detected, denoise skipped"
                state.original_audio = str(original)
                state.finished_at = time.time()
                _save_state(job_dir, state)
            return

        # Denoise
        cleaned = denoise_speech(original, strength=strength, out_dir=audio_dir,
                                 level=level, preserve_voice=preserve_voice)

        # Denoised video saved alongside the original; failure is non-fatal
        denoised_video = None
        try:
            denoised_video = str(remux_with_video(
                raw_path, cleaned, audio_dir / f"{raw_path.stem}_denoised.mp4"))
        except Exception:
            pass

        # Generate A/B samples
        samples = generate_ab_samples(original, cleaned)
        samples_dict = {
            "original_sample": str(samples["original_sample"]),
            "cleaned_sample": str(samples["cleaned_sample"]),
            "offset_s": samples["offset_s"],
            "duration_s": samples["duration_s"],
        }

        # Measure quality
        try:
            quality = measure_quality(original, cleaned)
        except Exception:
            quality = None

        with _lock:
            state = _states[job_id]
            state.status = "ready"
            state.strength = strength
            state.original_audio = str(original)
            state.cleaned_audio = str(cleaned)
            state.denoised_video = denoised_video
            state.message = "Ready for review"
            state.samples = samples_dict
            state.quality = quality
            state.finished_at = time.time()
            _save_state(job_dir, state)

    except Exception as e:
        with _lock:
            state = _states.get(job_id, DenoiseState())
            state.status = "error"
            state.message = str(e)
            state.finished_at = time.time()
            _states[job_id] = state
            _save_state(job_dir, state)
        if raise_errors:
            raise


def approve_cleaned(job_id: str, job_dir: Path) -> DenoiseState:
    with _lock:
        state = _load_state(job_dir) if CELERY_AVAILABLE else _states.get(job_id) or _load_state(job_dir)
        if state.status != "ready":
            raise ValueError(f"cannot approve: denoise status is {state.status}")
        state.approved = True
        state.bypass = False
        _states[job_id] = state
        _save_state(job_dir, state)
        return state


def set_bypass(job_id: str, job_dir: Path, bypass: bool) -> DenoiseState:
    with _lock:
        state = _load_state(job_dir) if CELERY_AVAILABLE else _states.get(job_id) or _load_state(job_dir)
        state.bypass = bypass
        if bypass:
            state.approved = False
        _states[job_id] = state
        _save_state(job_dir, state)
        return state


def adjust_strength(job_id: str, job_dir: Path, strength: float,
                    level: Optional[str] = None, preserve_voice: bool = True) -> DenoiseState:
    """Re-run denoise with a new strength. Invalidates approval."""
    with _lock:
        state = _load_state(job_dir) if CELERY_AVAILABLE else _states.get(job_id) or _load_state(job_dir)
        if state.status == "processing":
            raise ValueError("denoise is already processing")
        state.approved = False
    return start_denoise(job_id, job_dir, strength, level=level, preserve_voice=preserve_voice)


def invalidate(job_id: str, job_dir: Path) -> None:
    """Invalidate denoise state (e.g. when video is re-uploaded)."""
    with _lock:
        _states.pop(job_id, None)
    p = _state_path(job_dir)
    if p.is_file():
        p.unlink()
