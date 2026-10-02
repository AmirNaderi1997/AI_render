"""In-memory job registry + background render worker.

One job = one folder under jobs/<id>/ with subdirs raw/, exports/ and files
plan.json, project.mlt, captions.ass, status.json.
"""
from __future__ import annotations
import json
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from engine.build_mlt import build
from engine.render import render as run_render
from engine.schema import validate_plan


JOBS_ROOT = Path(__file__).resolve().parent.parent / "jobs"
JOBS_ROOT.mkdir(exist_ok=True)


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
class Job:
    id: str
    dir: Path
    raw_name: Optional[str] = None
    plan_name: str = "plan.json"
    render: RenderState = field(default_factory=RenderState)
    generate: GenerateState = field(default_factory=GenerateState)
    versions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dir"] = str(self.dir)
        return d


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _write_status(job: Job) -> None:
    (job.dir / "status.json").write_text(json.dumps(job.to_dict(), indent=2))


def create_job() -> Job:
    jid = uuid.uuid4().hex[:12]
    d = JOBS_ROOT / jid
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "exports").mkdir(parents=True, exist_ok=True)
    job = Job(id=jid, dir=d)
    with _lock:
        _jobs[jid] = job
    _write_status(job)
    return job


def get(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    with _lock:
        return list(_jobs.values())


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
            status_p = d / "status.json"
            if not status_p.exists():
                continue
            try:
                s = json.loads(status_p.read_text())
            except Exception:
                continue
            jid = s.get("id") or d.name
            raw_name = s.get("raw_name")
            if not raw_name:
                raws = sorted((d / "raw").glob("*")) if (d / "raw").exists() else []
                raw_name = raws[0].name if raws else None
            exports_dir = d / "exports"
            fs_versions = sorted(p.name for p in exports_dir.glob("v*.mp4")) if exports_dir.exists() else []
            versions = s.get("versions") or fs_versions
            r_state = s.get("render") or {}
            # A render marked running/queued from a previous process is stale.
            if r_state.get("status") in ("running", "queued"):
                r_state = {**r_state, "status": "idle", "progress": 0, "message": ""}
            render_state = RenderState(**{
                k: r_state.get(k, getattr(RenderState(), k))
                for k in RenderState.__dataclass_fields__
            })
            g_state = s.get("generate") or {}
            if g_state.get("status") == "running":
                g_state = {**g_state, "status": "idle", "stage": "", "message": ""}
            gen_state = GenerateState(**{
                k: g_state.get(k, getattr(GenerateState(), k))
                for k in GenerateState.__dataclass_fields__
            })
            job = Job(
                id=jid,
                dir=d,
                raw_name=raw_name,
                plan_name=s.get("plan_name", "plan.json"),
                render=render_state,
                generate=gen_state,
                versions=list(versions),
            )
            _jobs[jid] = job
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


def save_plan(job: Job, data: dict) -> tuple[Optional[dict], list[str]]:
    """Validate and persist a plan. Returns (plan_dict, errors)."""
    plan, errs = validate_plan(data, base_dir=job.dir, check_media=True)
    if errs:
        return None, errs
    (job.dir / "plan.json").write_text(json.dumps(data, indent=2))
    _write_status(job)
    return data, []


def load_plan(job: Job) -> dict:
    return json.loads((job.dir / "plan.json").read_text())


def start_render(job: Job, preview: bool = False, loudnorm: bool = False) -> None:
    if job.render.status == "running":
        return
    job.render = RenderState(status="queued", preview=preview, loudnorm=loudnorm,
                             started_at=time.time())
    _write_status(job)
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
) -> None:
    if job.generate.status == "running":
        return
    job.generate = GenerateState(status="running", stage="transcribing",
                                  started_at=time.time())
    _write_status(job)
    threading.Thread(
        target=_run_generate,
        args=(job, style, instruction, whisper_model, language, use_saved_transcript,
              transcribe_only, transcription_hint, asr_engine),
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
            on_progress=lambda msg: _gen_progress(job, msg),
        )

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
        job.generate.message = str(e)
        job.generate.finished_at = time.time()
        _write_status(job)


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


def _run_job(job: Job, preview: bool, loudnorm: bool = False) -> None:
    try:
        job.render.status = "running"
        job.render.message = "building MLT"
        _write_status(job)

        data = load_plan(job)
        plan, errs = validate_plan(data, base_dir=job.dir, check_media=True)
        if errs:
            raise ValueError("; ".join(errs))

        mlt, _ass = build(plan, job.dir, base_dir=job.dir)

        version_n = len(job.versions) + 1
        suffix = "_preview" if preview else ""
        out_name = f"v{version_n}{suffix}.mp4"
        out_path = job.dir / "exports" / out_name

        def report(pct: int) -> None:
            job.render.progress = pct

        job.render.message = "rendering"
        run_render(mlt, out_path, preview=preview, on_progress=report,
                   apply_loudnorm=loudnorm)

        job.render.output = out_name
        job.versions.append(out_name)
        job.render.status = "done"
        job.render.progress = 100
        job.render.finished_at = time.time()
        _write_status(job)
    except Exception as e:
        job.render.status = "error"
        job.render.message = str(e)
        job.render.finished_at = time.time()
        _write_status(job)
