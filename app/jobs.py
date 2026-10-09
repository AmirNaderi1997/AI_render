"""In-memory job registry + background render worker.

One job = one folder under jobs/<id>/ with subdirs raw/, exports/ and files
plan.json, project.mlt, captions.ass, status.json.
"""
from __future__ import annotations
import json
import hashlib
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from app.celery_app import CELERY_AVAILABLE
from app.config import settings
from engine.build_mlt import build
from engine.premiere import build_premiere
from engine.render import render as run_render, export_poster
from engine.schema import validate_plan


JOBS_ROOT = Path(settings.JOBS_DIR).expanduser()
JOBS_ROOT.mkdir(parents=True, exist_ok=True)


@dataclass
class RenderState:
    status: str = "idle"          # idle | queued | running | done | error
    progress: int = 0
    message: str = ""
    output: Optional[str] = None
    preview: bool = False
    loudnorm: bool = False
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    plan_sha256: Optional[str] = None


@dataclass
class GenerateState:
    status: str = "idle"          # idle | running | done | error
    stage: str = ""               # transcribing | detecting_pauses | planning | validating
    message: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    asr_engine: str = ""
    asr_audio_seconds: float = 0.0
    asr_cost_usd: float = 0.0
    correction_model: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class QCState:
    status: str = "idle"          # idle | running | done | error
    message: str = ""
    current_round: int = 0
    total_issues: int = 0
    fixed_issues: int = 0
    issues: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class Job:
    id: str
    dir: Path
    user_id: Optional[str] = None
    raw_name: Optional[str] = None
    plan_name: str = "plan.json"
    render: RenderState = field(default_factory=RenderState)
    generate: GenerateState = field(default_factory=GenerateState)
    qc: QCState = field(default_factory=QCState)
    versions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dir"] = str(self.dir)
        return d


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _write_status(job: Job) -> None:
    status_path = job.dir / "status.json"
    payload = json.dumps(job.to_dict(), indent=2)
    if CELERY_AVAILABLE:
        # The API may read while a worker is writing; publish a complete file.
        temporary = job.dir / f".status-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(payload)
            temporary.replace(status_path)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        status_path.write_text(payload)


def create_job(user_id: Optional[str] = None) -> Job:
    jid = uuid.uuid4().hex[:12]
    d = JOBS_ROOT / jid
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "exports").mkdir(parents=True, exist_ok=True)
    job = Job(id=jid, dir=d, user_id=str(user_id) if user_id is not None else None)
    with _lock:
        _jobs[jid] = job
    _write_status(job)
    return job


def get(job_id: str) -> Optional[Job]:
    if CELERY_AVAILABLE:
        # Workers run in other processes, so the persisted status is authoritative.
        if Path(job_id).name != job_id:
            return None
        job = _job_from_status(JOBS_ROOT / job_id, reset_stale=False)
        if job is not None:
            with _lock:
                _jobs[job_id] = job
        return job
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    if CELERY_AVAILABLE:
        rescan()
    with _lock:
        return list(_jobs.values())


def _job_from_status(d: Path, *, reset_stale: bool) -> Optional[Job]:
    status_p = d / "status.json"
    if not status_p.is_file():
        return None
    try:
        s = json.loads(status_p.read_text())
    except (OSError, ValueError, TypeError):
        return None
    jid = s.get("id") or d.name
    raw_name = s.get("raw_name")
    if not raw_name:
        raws = sorted((d / "raw").glob("*")) if (d / "raw").exists() else []
        raw_name = raws[0].name if raws else None
    exports_dir = d / "exports"
    fs_versions = sorted(p.name for p in exports_dir.glob("v*.mp4")) if exports_dir.exists() else []
    versions = s.get("versions") or fs_versions
    r_state = s.get("render") or {}
    if reset_stale and r_state.get("status") in ("running", "queued"):
        r_state = {**r_state, "status": "idle", "progress": 0, "message": ""}
    render_state = RenderState(**{
        k: r_state.get(k, getattr(RenderState(), k))
        for k in RenderState.__dataclass_fields__
    })
    g_state = s.get("generate") or {}
    if reset_stale and g_state.get("status") == "running":
        g_state = {**g_state, "status": "idle", "stage": "", "message": ""}
    gen_state = GenerateState(**{
        k: g_state.get(k, getattr(GenerateState(), k))
        for k in GenerateState.__dataclass_fields__
    })
    q_state = s.get("qc") or {}
    if reset_stale and q_state.get("status") == "running":
        q_state = {**q_state, "status": "idle", "message": ""}
    qc_state = QCState(**{
        k: q_state.get(k, getattr(QCState(), k))
        for k in QCState.__dataclass_fields__
    })
    return Job(
        id=jid,
        dir=d,
        user_id=str(s["user_id"]) if s.get("user_id") is not None else None,
        raw_name=raw_name,
        plan_name=s.get("plan_name", "plan.json"),
        render=render_state,
        generate=gen_state,
        qc=qc_state,
        versions=list(versions),
    )


def rescan(root: Optional[Path] = None) -> int:
    """Rebuild the in-memory registry from disk. Returns the number of jobs loaded.

    A job directory is any immediate subdirectory of JOBS_ROOT with a status.json.
    Missing fields fall back to filesystem state (raw/<file>, exports/*.mp4).
    """
    r = Path(root) if root else JOBS_ROOT
    if not r.exists():
        return 0
    loaded = 0
    with _lock:
        _jobs.clear()
        for d in sorted(p for p in r.iterdir() if p.is_dir()):
            job = _job_from_status(d, reset_stale=not CELERY_AVAILABLE)
            if job is None:
                continue
            _jobs[job.id] = job
            loaded += 1
    return loaded


def save_raw(job: Job, filename: str, src) -> Path:
    """Stream a file-like object to raw/ in 1 MB chunks (no full-file RAM copy)."""
    filename = Path(filename).name or "raw.mp4"
    dst = job.dir / "raw" / filename
    with open(dst, "wb") as out:
        shutil.copyfileobj(src, out, 1024 * 1024)
    job.raw_name = filename
    _write_status(job)
    return dst


def save_music(job: Job, filename: str, src) -> Path:
    """Stream a music file to music/ inside the job directory."""
    filename = Path(filename).name or "music.mp3"
    music_dir = job.dir / "music"
    music_dir.mkdir(exist_ok=True)
    dst = music_dir / filename
    with open(dst, "wb") as out:
        shutil.copyfileobj(src, out, 1024 * 1024)
    _write_status(job)
    return dst


def save_plan(job: Job, data: dict) -> tuple[Optional[dict], list[str]]:
    """Validate and persist a plan. Returns (plan_dict, errors)."""
    plan, errs = validate_plan(data, base_dir=job.dir, check_media=True)
    if errs:
        return None, errs
    path = job.dir / "plan.json"
    try:
        unchanged = json.loads(path.read_text()) == data
    except (OSError, ValueError):
        unchanged = False
    if not unchanged:
        path.write_text(json.dumps(data, indent=2))
    _write_status(job)
    return data, []


def load_plan(job: Job) -> dict:
    plan_path = job.dir / "plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError("plan.json not found — generate or upload a plan first")
    return json.loads(plan_path.read_text())


def start_render(job: Job, preview: bool = False, loudnorm: bool = False) -> None:
    with _lock:
        if job.generate.status == "running":
            raise ValueError("plan generation must finish before rendering")
        if job.render.status in {"queued", "running"}:
            return
        # Reset QC state so stale issues don't persist
        job.qc = QCState()
        job.render = RenderState(status="queued", preview=preview, loudnorm=loudnorm,
                                 started_at=time.time())
        _write_status(job)
    if CELERY_AVAILABLE:
        from app.tasks import task_run_render
        task_run_render.delay(job.id, preview, loudnorm)
    else:
        threading.Thread(target=_run_job, args=(job, preview, loudnorm), daemon=True).start()


def start_generate(
    job: Job,
    style: str = "rafiei_reel",
    instruction: str = "",
    whisper_model: Optional[str] = None,
    language: Optional[str] = None,
    use_saved_transcript: bool = False,
    transcribe_only: bool = False,
    transcription_hint: str = "",
    asr_engine: Optional[str] = None,
    caption_font: Optional[str] = None,
    caption_font_id: Optional[str] = None,
    style_id: Optional[str] = None,
    style_version: Optional[int] = None,
    output_kind: str = "reel",
    transition_style: str = "auto",
    transition_request: str = "",
) -> None:
    with _lock:
        if job.render.status in {"queued", "running"}:
            raise ValueError("render must finish before generating a plan")
        if job.generate.status == "running":
            return
        locked_transitions: list[dict] = []
        existing_plan = job.dir / "plan.json"
        if existing_plan.is_file():
            try:
                locked_transitions = [
                    dict(item) for item in json.loads(existing_plan.read_text()).get("transitions", [])
                    if item.get("locked")
                ]
            except (OSError, ValueError, TypeError):
                locked_transitions = []
        style_ref = None
        style_profile = None
        if style_id:
            if not style_version:
                raise ValueError("an approved style version is required")
            from engine.style_library import get_profile, resolve_preset
            try:
                profile = get_profile(style_id, style_version)
            except KeyError as exc:
                raise ValueError("approved style version not found") from exc
            style_ref = {"style_id": style_id, "version": style_version, "name": profile["name"]}
            style_profile = resolve_preset(style_id, style_version)
            (job.dir / "style_selection.json").write_text(json.dumps({**style_ref, "state": "pinned"}, indent=2))
        elif (job.dir / "style_selection.json").is_file():
            # Regeneration reuses the job's approved immutable version unless the
            # caller explicitly pins a different one.
            from engine.style_library import get_profile, resolve_preset
            selection = json.loads((job.dir / "style_selection.json").read_text())
            selected = get_profile(selection["style_id"], int(selection["version"]))
            style_ref = {"style_id": selection["style_id"], "version": int(selection["version"]),
                         "name": selected["name"]}
            style_profile = resolve_preset(style_ref["style_id"], style_ref["version"])
        job.generate = GenerateState(status="running", stage="transcribing",
                                      started_at=time.time())
        _write_status(job)
    if CELERY_AVAILABLE:
        # Preserve the exact approved style and transition inputs at dispatch.
        request = {
            "style": style,
            "instruction": instruction,
            "whisper_model": whisper_model,
            "language": language,
            "use_saved_transcript": use_saved_transcript,
            "transcribe_only": transcribe_only,
            "transcription_hint": transcription_hint,
            "asr_engine": asr_engine,
            "caption_font": caption_font,
            "caption_font_id": caption_font_id,
            "locked_transitions": locked_transitions,
            "output_kind": output_kind,
            "transition_style": transition_style,
            "transition_request": transition_request,
            "style_profile": style_profile,
            "style_ref": style_ref,
        }
        (job.dir / "generation_request.json").write_text(
            json.dumps(request, ensure_ascii=False)
        )
        from app.tasks import task_generate_plan
        task_generate_plan.delay(job.id)
    else:
        threading.Thread(
            target=_run_generate,
            args=(job, style, instruction, whisper_model, language, use_saved_transcript,
                  transcribe_only, transcription_hint, asr_engine, caption_font, caption_font_id,
                  locked_transitions, output_kind, transition_style, transition_request,
                  style_profile, style_ref),
            daemon=True,
        ).start()


def _run_generate(
    job: Job,
    style: str,
    instruction: str,
    whisper_model: Optional[str],
    language: Optional[str],
    use_saved_transcript: bool,
    transcribe_only: bool,
    transcription_hint: str,
    asr_engine: Optional[str] = None,
    caption_font: Optional[str] = None,
    caption_font_id: Optional[str] = None,
    locked_transitions: Optional[list[dict]] = None,
    output_kind: str = "reel",
    transition_style: str = "auto",
    transition_request: str = "",
    style_profile: Optional[dict] = None,
    style_ref: Optional[dict] = None,
    *,
    raise_errors: bool = False,
) -> None:
    import os
    from brain.transcribe import transcribe, effective_transcript, file_hash, choose_engine
    from brain.silence import detect_pauses
    from brain.planner import generate_plan

    try:
        raw_path = job.dir / "raw" / job.raw_name
        if not raw_path.exists():
            raise FileNotFoundError(f"raw video not found: {raw_path}")

        # 1. Transcribe
        selected_engine = choose_engine(language, asr_engine)
        job.generate.stage = "transcribing"
        job.generate.message = f"running {selected_engine}…"
        _write_status(job)

        if use_saved_transcript:
            transcript = effective_transcript(job.dir)
            if transcript["file_hash"] != file_hash(raw_path):
                raise ValueError("saved transcript belongs to another video")
        else:
            wm = whisper_model or os.getenv("WHISPER_MODEL")
            from brain.correct import load_glossary
            from brain.glossary import build_initial_prompt
            _glossary = load_glossary()
            _vocab_hint = build_initial_prompt(_glossary, language or "fa")
            combined_hint = " ".join(filter(None, [_vocab_hint, transcription_hint])).strip()[:500]
            glossary_terms = list(_glossary.get("vocabulary") or [])
            transcript = transcribe(
                raw_path, job.dir, model_size=wm, language=language,
                initial_prompt=combined_hint or None,
                engine=asr_engine,
                keyterms=glossary_terms or None,
            )

        asr_cost_path = job.dir / "asr_cost.json"
        if asr_cost_path.exists():
            asr_info = json.loads(asr_cost_path.read_text())
            job.generate.asr_engine = asr_info.get("engine", "")
            job.generate.asr_audio_seconds = asr_info.get("audio_seconds", 0)
            job.generate.asr_cost_usd = asr_info.get("cost_usd", 0)

        # 2. Auto-correct transcript (best-effort; never breaks the pipeline)
        if not use_saved_transcript:
            _run_auto_correct(job, transcript, style)
            transcript = _reload_transcript(job)

        if transcribe_only:
            job.generate.status = "done"
            job.generate.stage = ""
            job.generate.message = "transcript generated; plan unchanged"
            job.generate.finished_at = time.time()
            _write_status(job)
            return

        # A video-only upload is still a valid editing source. Likewise, a
        # deployment without the optional local Whisper runtime should remain
        # able to produce a renderable plan; it simply has no subtitle track.
        if not transcript.get("words"):
            duration = float(transcript.get("duration") or 0)
            if duration <= 0:
                raise ValueError("source video has no positive duration")
            canvas = {"width": 1080, "height": 1080 if output_kind == "post" else 1920,
                      "fps": 30}
            if caption_font:
                canvas["caption_font"] = caption_font
            if caption_font_id:
                canvas["caption_font_id"] = caption_font_id
            plan_data = {
                "version": "0.1",
                "style": style,
                "canvas": canvas,
                "source": f"raw/{job.raw_name}",
                "segments": [{"id": "s1", "in": 0.0, "out": duration}],
                "transitions": [],
                "transition_context": {
                    "output_kind": output_kind,
                    "style": transition_style,
                    "request": transition_request,
                },
                "captions": [],
                "broll": [],
                "sfx": [],
                "export": {"file": "output.mp4", "crf": 20},
                "generation_meta": {
                    "transcript_fallback": transcript.get("fallback_reason", "no speech detected")
                },
            }
            if style_ref:
                plan_data["style_profile"] = dict(style_ref)
            _, errors = validate_plan(plan_data, base_dir=job.dir, check_media=True)
            if errors:
                raise ValueError("; ".join(errors))
            plan_path = job.dir / "plan.json"
            if plan_path.exists():
                history = job.dir / "plans"
                history.mkdir(exist_ok=True)
                (history / f"plan-{int(time.time() * 1000)}.json").write_bytes(
                    plan_path.read_bytes()
                )
            plan_path.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False))
            job.generate.status = "done"
            job.generate.stage = ""
            job.generate.message = "plan generated without subtitles"
            job.generate.finished_at = time.time()
            _write_status(job)
            return

        # 4. Detect pauses
        job.generate.stage = "detecting_pauses"
        job.generate.message = "detecting pauses…"
        _write_status(job)

        pauses = detect_pauses(raw_path, transcript["words"], preset=style)

        # 5. Plan with LLM
        job.generate.stage = "planning"
        job.generate.message = "asking LLM to build edit plan…"
        _write_status(job)

        source_rel = f"raw/{job.raw_name}"
        plan_data, usage = generate_plan(
            job_dir=job.dir,
            transcript=transcript,
            keep_ranges=pauses["keep"],
            remove_ranges=pauses["remove"],
            source_rel=source_rel,
            preset_name=style,
            instruction=instruction,
            caption_font=caption_font,
            style_profile=style_profile,
            style_ref=style_ref,
            locked_transitions=locked_transitions,
            output_kind=output_kind,
            transition_style=transition_style,
            transition_request=transition_request,
            on_progress=lambda msg: _gen_progress(job, msg),
        )
        if caption_font_id:
            from engine.font_library import resolve_font
            approved_font = resolve_font(caption_font_id)
            plan_data.setdefault("canvas", {})["caption_font_id"] = caption_font_id
            plan_data["canvas"]["caption_font"] = approved_font["family"]

        # 6. Validate and save
        job.generate.stage = "validating"
        job.generate.message = "validating plan…"
        _write_status(job)

        plan_path = job.dir / "plan.json"
        if plan_path.exists():
            history = job.dir / "plans"
            history.mkdir(exist_ok=True)
            backup = history / f"plan-{int(time.time() * 1000)}.json"
            backup.write_bytes(plan_path.read_bytes())
        plan_path.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False))

        job.generate.status = "done"
        job.generate.stage = ""
        job.generate.message = "plan generated"
        job.generate.cost_usd = round(usage.cost_estimate, 6)
        job.generate.input_tokens = usage.input_tokens
        job.generate.output_tokens = usage.output_tokens
        job.generate.model = usage.model
        job.generate.finished_at = time.time()
        _write_status(job)

    except Exception as e:
        job.generate.status = "error"
        job.generate.message = "Plan generation failed. Check server logs." if settings.APP_ENV == "production" else str(e)
        job.generate.finished_at = time.time()
        _write_status(job)
        if raise_errors:
            raise


def _gen_progress(job: Job, msg: str) -> None:
    job.generate.message = msg
    _write_status(job)


def _reload_transcript(job: Job) -> dict:
    from brain.transcribe import effective_transcript
    try:
        return effective_transcript(job.dir)
    except Exception:
        return {}


def _run_auto_correct(job: Job, transcript: dict, style: str) -> None:
    """Auto-correct transcript with LLM. Saves corrections.json and applies high-confidence fixes."""
    import yaml
    from engine.schema import PROJECT_ROOT
    from brain.correct import auto_correct, load_glossary, expand_corrections_for_save
    from brain.transcribe import save_corrections

    if not transcript.get("words"):
        return

    job.generate.stage = "correcting"
    job.generate.message = "auto-correcting transcript…"
    _write_status(job)

    try:
        preset_path = PROJECT_ROOT / "presets" / f"{style}.yaml"
        preset = yaml.safe_load(preset_path.read_text()) if preset_path.exists() else {}
    except Exception:
        preset = {}

    glossary = load_glossary()
    corrections, usage = auto_correct(transcript, preset, glossary)
    if usage.model:
        job.generate.correction_model = usage.model
        _write_status(job)

    if not corrections:
        return

    correction_cfg = preset.get("correction") or {}
    min_confidence = float(correction_cfg.get("auto_apply_min_confidence", 0.85))

    auto_apply = [c for c in corrections if c["confidence"] >= min_confidence]
    suggestions = [c for c in corrections if c["confidence"] < min_confidence]

    # Persist all correction metadata (auto-applied + suggestions) for the UI
    meta_path = job.dir / "corrections.json"
    meta_path.write_text(
        json.dumps({
            "base_key": transcript.get("cache_key") or transcript.get("file_hash", ""),
            "auto_applied": auto_apply,
            "suggestions": suggestions,
        }, ensure_ascii=False, indent=2)
    )

    if auto_apply:
        base_key = transcript.get("cache_key") or transcript.get("file_hash", "")
        try:
            words = transcript.get("words", [])
            save_items = expand_corrections_for_save(auto_apply, words)
            save_corrections(
                job.dir,
                base_key,
                save_items,
            )
        except ValueError as exc:
            import logging
            logging.getLogger(__name__).warning("auto-correct save failed: %s", exc)


def _run_job(job: Job, preview: bool, loudnorm: bool = False, *, raise_errors: bool = False) -> None:
    try:
        job.render.status = "running"
        job.render.message = "building MLT"
        _write_status(job)

        data = load_plan(job)
        render_plan_sha256 = hashlib.sha256((job.dir / "plan.json").read_bytes()).hexdigest()
        plan, errs = validate_plan(data, base_dir=job.dir, check_media=True)
        if errs:
            raise ValueError("; ".join(errs))

        style_override = None
        style_ref = None
        selection_path = job.dir / "style_selection.json"
        if selection_path.exists():
            selection = json.loads(selection_path.read_text())
            from engine.style_library import resolve_preset
            style_override = resolve_preset(selection["style_id"], int(selection["version"]))
            style_ref = selection
        mlt, _ass = build(
            plan, job.dir, base_dir=job.dir, style_name=plan.style,
            style_override=style_override, style_ref=style_ref,
        )
        build_premiere(plan, job.dir, base_dir=job.dir)

        version_n = len(job.versions) + 1
        suffix = "_preview" if preview else ""
        out_name = f"v{version_n}{suffix}.mp4"
        out_path = job.dir / "exports" / out_name

        def report(pct: int) -> None:
            job.render.progress = pct
            if CELERY_AVAILABLE:
                _write_status(job)

        job.render.message = "rendering"
        if CELERY_AVAILABLE:
            _write_status(job)
        run_render(
            mlt, out_path, preview=preview, style_name=plan.style,
            style_override=style_override, crf_override=plan.export.crf,
            on_progress=report, apply_loudnorm=loudnorm,
        )

        if plan.poster:
            job.render.message = "exporting poster"
            try:
                export_poster(
                    plan, job.dir, out_path.with_name(out_path.stem + "_poster.jpg"),
                    base_dir=job.dir, style_name=plan.style,
                    style_override=style_override, style_ref=style_ref,
                )
            except Exception as exc:  # poster is optional; never fail the render
                import logging
                logging.getLogger(__name__).warning("poster export failed: %s", exc)

        job.render.output = out_name
        job.render.plan_sha256 = render_plan_sha256
        job.versions.append(out_name)
        job.render.status = "done"
        job.render.progress = 100
        job.render.finished_at = time.time()
        _write_status(job)
    except Exception as e:
        job.render.status = "error"
        job.render.message = "Render failed. Check server logs." if settings.APP_ENV == "production" else str(e)
        job.render.finished_at = time.time()
        _write_status(job)
        if raise_errors:
            raise


def start_qc(job: Job) -> None:
    if job.qc.status == "running":
        return
    if job.render.status != "done" or not job.render.output:
        raise ValueError("render must be done before running QC")
    job.qc = QCState(status="running", started_at=time.time())
    _write_status(job)
    if CELERY_AVAILABLE:
        from app.tasks import task_run_qc
        task_run_qc.delay(job.id)
    else:
        threading.Thread(target=_run_qc, args=(job,), daemon=True).start()


def _run_qc(job: Job, *, raise_errors: bool = False) -> None:
    from brain.qc_pipeline import run_qc

    try:
        video_path = job.dir / "exports" / job.render.output
        plan_data = load_plan(job)

        def on_status(status: str, message: str) -> None:
            job.qc.status = status
            job.qc.message = message
            _write_status(job)

        result = run_qc(job.dir, video_path, plan_data, on_status=on_status)

        job.qc.status = result.status
        job.qc.message = result.message
        job.qc.current_round = result.current_round
        job.qc.total_issues = result.total_issues
        job.qc.fixed_issues = result.fixed_issues
        all_issues = []
        all_changes = []
        for rd in result.rounds:
            all_issues.extend(rd.issues)
            all_changes.extend(rd.changes)
        job.qc.issues = all_issues
        job.qc.changes = all_changes
        job.qc.finished_at = time.time()
        _write_status(job)

    except Exception as e:
        job.qc.status = "error"
        job.qc.message = "Quality check failed. Check server logs." if settings.APP_ENV == "production" else str(e)
        job.qc.finished_at = time.time()
        _write_status(job)
        if raise_errors:
            raise


def apply_qc_fixes(job: Job, issue_indices: list[int] | None = None) -> tuple[dict, list[dict]]:
    """Apply QC fixes to plan and save. Returns (patched_plan, changes).

    If issue_indices is None, applies all issues. Otherwise only selected ones.
    """
    from brain.qc_pipeline import get_patched_plan

    plan_data = load_plan(job)
    issues = job.qc.issues
    if issue_indices is not None:
        issues = [issues[i] for i in issue_indices if 0 <= i < len(issues)]

    patched, changes = get_patched_plan(job.dir, plan_data, issues)
    if changes:
        save_plan(job, patched)
    return patched, changes
