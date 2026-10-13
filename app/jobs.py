"""PostgreSQL-backed job registry + background render worker.

One job has a media-only directory under ``JOBS_DIR/<id>`` (uploads, renders,
and editor artifacts). Durable metadata and progress are database records.
"""
from __future__ import annotations
import asyncio
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
from app.database import AsyncSessionLocal, DB_AVAILABLE
from app.models import Job as JobRecord, Plan as PlanRecord, QCResult, RenderResult
from request_context import celery_request_headers
from sqlalchemy import select
from engine.build_mlt import build
from engine.captions import load_style
from engine.premiere import AttachedMusic, build_premiere
from engine.render import render as run_render, export_poster, embed_poster
from engine.schema import validate_plan
from app import plan_versions


JOBS_ROOT = Path(settings.JOBS_DIR).expanduser()


def _ensure_jobs_root() -> None:
    """Create the configured media mount lazily, not while importing modules."""
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
    technical_qc: Optional[dict] = None


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
    asr_fallback_reason: str = ""
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
class MusicState:
    """Attached background music and the status of its post-render mix."""
    file: Optional[str] = None    # job-relative path, e.g. music/attached_ab12.mp3
    name: Optional[str] = None    # original upload name, for display
    duration_s: float = 0.0
    volume: float = 0.3           # 0.0-1.0
    fade_in: float = 2.0
    fade_out: float = 3.0
    status: str = "idle"          # idle | queued | running | done | error
    progress: int = 0
    message: str = ""
    output: Optional[str] = None  # mixed file in exports/; render.output is left untouched
    mixed_from: Optional[str] = None
    technical_qc: Optional[dict] = None
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
    music: MusicState = field(default_factory=MusicState)
    versions: list[str] = field(default_factory=list)
    plan_data: Optional[dict] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dir"] = str(self.dir)
        d.pop("plan_data", None)
        return d


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_db_loop: asyncio.AbstractEventLoop | None = None
_db_loop_ready = threading.Event()
_db_loop_lock = threading.Lock()


def _database_loop() -> asyncio.AbstractEventLoop:
    """Return one loop for all sync registry calls.

    asyncpg connections are bound to their creating event loop. A persistent
    loop avoids the cross-loop failure caused by creating a new loop for every
    FastAPI/Celery status update.
    """
    global _db_loop
    with _db_loop_lock:
        if _db_loop is None:
            def serve() -> None:
                global _db_loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                _db_loop = loop
                _db_loop_ready.set()
                loop.run_forever()
            threading.Thread(target=serve, name="job-db-loop", daemon=True).start()
    _db_loop_ready.wait()
    assert _db_loop is not None
    return _db_loop


def _job_status(job: Job) -> tuple[str, str, str, int]:
    """Flatten the active operation for indexed list/detail queries."""
    for name, state in (("render", job.render), ("generate", job.generate), ("qc", job.qc)):
        if state.status in {"queued", "running", "error"}:
            return state.status, getattr(state, "stage", "") or name, state.message, getattr(state, "progress", 0)
    if job.render.status == "done":
        return "done", "render", job.render.message, job.render.progress
    if job.generate.status == "done":
        return "done", "generate", job.generate.message, 100
    return "new", "", "", 0


def _job_from_record(record: JobRecord, plan_data: Optional[dict] = None) -> Job:
    state = record.state or {}
    payload = state.get("job", state)
    render = payload.get("render") or {}
    generate = payload.get("generate") or {}
    qc = payload.get("qc") or {}
    music = payload.get("music") or {}
    return Job(
        id=record.id,
        dir=JOBS_ROOT / record.id,
        user_id=str(record.user_id) if record.user_id is not None else None,
        raw_name=payload.get("raw_name"),
        plan_name="plan.json",
        render=RenderState(**{k: render.get(k, getattr(RenderState(), k)) for k in RenderState.__dataclass_fields__}),
        generate=GenerateState(**{k: generate.get(k, getattr(GenerateState(), k)) for k in GenerateState.__dataclass_fields__}),
        qc=QCState(**{k: qc.get(k, getattr(QCState(), k)) for k in QCState.__dataclass_fields__}),
        music=MusicState(**{k: music.get(k, getattr(MusicState(), k)) for k in MusicState.__dataclass_fields__}),
        versions=list(payload.get("versions") or []),
        plan_data=plan_data,
    )


async def _persist_job(job: Job) -> None:
    if AsyncSessionLocal is None:
        return
    status, stage, message, progress = _job_status(job)
    state = job.to_dict()
    state.pop("dir", None)
    state.pop("plan_data", None)
    async with AsyncSessionLocal() as db:
        record = await db.get(JobRecord, job.id)
        if record is None:
            record = JobRecord(id=job.id, user_id=int(job.user_id) if job.user_id else None,
                               title=None, source_path=(f"raw/{job.raw_name}" if job.raw_name else None),
                               status=status, stage=stage, message=message, progress_pct=progress,
                               state={"job": state})
            db.add(record)
        else:
            record.status, record.stage, record.message, record.progress_pct = status, stage, message, progress
            record.source_path = f"raw/{job.raw_name}" if job.raw_name else record.source_path
            record.state = {"job": state}
        if job.plan_data is not None:
            plan = (await db.execute(select(PlanRecord).where(PlanRecord.job_id == job.id))).scalar_one_or_none()
            if plan is None:
                plan = PlanRecord(job_id=job.id, scenes=job.plan_data.get("segments", []),
                                  captions=job.plan_data.get("captions", []), data=job.plan_data)
                db.add(plan)
            else:
                plan.scenes, plan.captions, plan.data = job.plan_data.get("segments", []), job.plan_data.get("captions", []), job.plan_data
        if job.render.status == "done" and job.render.output:
            exists = (await db.execute(select(RenderResult).where(RenderResult.job_id == job.id,
                RenderResult.output_path == f"exports/{job.render.output}"))).scalar_one_or_none()
            if exists is None:
                db.add(RenderResult(job_id=job.id, output_path=f"exports/{job.render.output}", format="mp4", duration=None))
        if job.qc.status == "done":
            db.add(QCResult(job_id=job.id,
                            scores={"current_round": job.qc.current_round, "total_issues": job.qc.total_issues,
                                    "fixed_issues": job.qc.fixed_issues}, issues=job.qc.issues))
        await db.commit()


def _await_db(coro):
    """Run async SQLAlchemy work from legacy sync routes, threads, or Celery."""
    return asyncio.run_coroutine_threadsafe(coro, _database_loop()).result()


def _write_status(job: Job) -> None:
    """Persist job state to PostgreSQL; status.json is intentionally not written."""
    if DB_AVAILABLE:
        _await_db(_persist_job(job))
    with _lock:
        _jobs[job.id] = job


def create_job(user_id: Optional[str] = None, db=None, *, persist: bool = True) -> Job:
    _ensure_jobs_root()
    jid = uuid.uuid4().hex[:12]
    d = JOBS_ROOT / jid
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "exports").mkdir(parents=True, exist_ok=True)
    job = Job(id=jid, dir=d, user_id=str(user_id) if user_id is not None else None)
    if persist:
        _write_status(job)
    return job


def get(job_id: str, db=None) -> Optional[Job]:
    if Path(job_id).name != job_id:
        return None
    if DB_AVAILABLE:
        async def load():
            assert AsyncSessionLocal is not None
            async with AsyncSessionLocal() as db:
                record = await db.get(JobRecord, job_id)
                if record is None:
                    return None
                plan = (await db.execute(select(PlanRecord).where(PlanRecord.job_id == job_id))).scalar_one_or_none()
                return _job_from_record(record, plan.data if plan else None)
        job = _await_db(load())
        if job is not None:
            with _lock:
                _jobs[job_id] = job
        return job
    with _lock:
        return _jobs.get(job_id)


def list_jobs(db=None) -> list[Job]:
    if DB_AVAILABLE:
        async def load_all():
            assert AsyncSessionLocal is not None
            async with AsyncSessionLocal() as db:
                records = (await db.execute(select(JobRecord).order_by(JobRecord.created_at.desc()))).scalars().all()
                plans = {p.job_id: p.data for p in (await db.execute(select(PlanRecord))).scalars()}
                return [_job_from_record(record, plans.get(record.id)) for record in records]
        jobs = _await_db(load_all())
        with _lock:
            _jobs.clear(); _jobs.update({job.id: job for job in jobs})
        return jobs
    with _lock:
        return list(_jobs.values())


def get_job(job_id: str, db=None) -> Optional[Job]:
    """Public CRUD alias retained for route-level dependency injection."""
    return get(job_id, db=db)


def update_job(job: Job, db=None) -> Job:
    """Persist a mutated job state without changing its public JSON shape."""
    _write_status(job)
    return job


def rescan(root: Optional[Path] = None) -> int:
    """Refresh the process-local cache from PostgreSQL."""
    if DB_AVAILABLE:
        cleanup_orphaned_jobs()
        _recover_stuck_jobs()
        return len(list_jobs())
    with _lock:
        return len(_jobs)


def _recover_stuck_jobs() -> int:
    """Mark jobs stuck in running/queued state as errors after a restart."""
    if not DB_AVAILABLE:
        return 0

    async def recover() -> int:
        assert AsyncSessionLocal is not None
        async with AsyncSessionLocal() as db:
            records = (await db.execute(
                select(JobRecord).where(JobRecord.status.in_(["running", "queued"]))
            )).scalars().all()
            changed = 0
            for record in records:
                record.status = "error"
                record.message = "Interrupted by server restart. Please try again."
                state = record.state or {}
                payload = state.get("job", state)
                for key in ("generate", "render", "qc"):
                    sub = payload.get(key)
                    if isinstance(sub, dict) and sub.get("status") in ("running", "queued"):
                        sub["status"] = "error"
                        sub["message"] = "Interrupted by server restart"
                record.state = {**state, "job": payload}
                changed += 1
            if changed:
                await db.commit()
            return changed
    return _await_db(recover())


def save_raw(job: Job, filename: str, src, *, expected_size: int | None = None) -> Path:
    """Stream a file-like object to raw/ in 1 MB chunks (no full-file RAM copy)."""
    filename = Path(filename).name or "raw.mp4"
    dst = job.dir / "raw" / filename
    try:
        with open(dst, "wb") as out:
            shutil.copyfileobj(src, out, 1024 * 1024)
        if not dst.is_file():
            raise OSError("upload file was not created")
        actual_size = dst.stat().st_size
        if expected_size is not None and actual_size != expected_size:
            raise OSError(f"upload size mismatch: expected {expected_size} bytes, wrote {actual_size}")
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
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


def save_plan(
    job: Job,
    data: dict,
    *,
    source: str = "user_ui",
    operations: Optional[list] = None,
    parent_version: Optional[int] | object = plan_versions.LATEST,
) -> tuple[Optional[dict], list[str]]:
    """Validate and persist a plan as a new version. Returns (plan_dict, errors)."""
    plan, errs = validate_plan(data, base_dir=job.dir, check_media=True)
    if errs:
        return None, errs
    _ensure_baseline_version(job)
    job.plan_data = data
    _write_status(job)
    plan_versions.record_version(job, data, source, operations, parent_version)
    return data, []


def _ensure_baseline_version(job: Job) -> None:
    """Plans saved before versioning existed get a 'legacy' v1 so undo can reach them."""
    if job.plan_data is not None and not plan_versions.list_versions(job):
        plan_versions.record_version(job, job.plan_data, "legacy")


def _guard_plan_edit(job: Job) -> None:
    if job.generate.status == "running":
        raise ValueError("wait for plan generation to finish")


def apply_plan_operations(
    job: Job,
    operations: list,
    *,
    source: str = "user_ui",
    dry_run: bool = False,
    base_version: Optional[int] = None,
) -> dict:
    """Apply a batch of EditOperations to the job's plan.

    User edits may change locked items; chat and QC edits may not. With
    ``dry_run`` nothing is saved and the diff is returned. ``base_version``
    rejects the batch if the plan changed since the caller last read it.
    Raises ValueError (conflict/state) or engine.operations.OperationError.
    """
    from engine.operations import OpContext, apply_operations

    _guard_plan_edit(job)
    current = load_plan(job)
    latest = plan_versions.latest_version(job)
    current_version = latest["version"] if latest else None
    if base_version is not None and current_version is not None and base_version != current_version:
        raise PlanVersionConflict(f"plan is at version {current_version}, not {base_version}")
    ctx = OpContext(actor="user" if source == "user_ui" else "ai", respect_locks=source != "user_ui")
    result = apply_operations(current, operations, ctx, base_dir=job.dir, check_media=True)
    response = {"ok": True, "dry_run": dry_run, "diff": result.diff, "operations": result.operations,
                "plan": result.plan, "version": current_version}
    if not dry_run:
        _, errors = save_plan(job, result.plan, source=source, operations=result.operations)
        if errors:  # validated above; only a media file vanishing could get here
            raise ValueError("; ".join(errors))
        response["version"] = plan_versions.latest_version(job)["version"]
    return response


def undo_plan(job: Job) -> dict:
    """Restore the parent of the latest version, recorded as a new 'undo' version.

    The undo version's parent is the restored version's parent, so repeated
    undos keep walking back through history.
    """
    _guard_plan_edit(job)
    latest = plan_versions.latest_version(job)
    if latest is None or latest.get("parent_version") is None:
        raise ValueError("nothing to undo")
    target = plan_versions.get_version(job, latest["parent_version"])
    if target is None:
        raise ValueError(f"version {latest['parent_version']} not found")
    _, errors = save_plan(job, target["plan"], source="undo",
                          operations=[{"op": "undo", "from_version": latest["version"],
                                       "restored_version": target["version"]}],
                          parent_version=target.get("parent_version"))
    if errors:
        raise ValueError("; ".join(errors))
    return {"ok": True, "version": plan_versions.latest_version(job)["version"],
            "restored_version": target["version"], "plan": target["plan"]}


class PlanVersionConflict(ValueError):
    pass


def load_plan(job: Job) -> dict:
    if DB_AVAILABLE:
        async def load():
            assert AsyncSessionLocal is not None
            async with AsyncSessionLocal() as db:
                plan = (await db.execute(
                    select(PlanRecord).where(PlanRecord.job_id == job.id)
                )).scalar_one_or_none()
                return plan.data if plan is not None else None
        plan_data = _await_db(load())
        if plan_data is None:
            raise FileNotFoundError("Generate a plan first")
        job.plan_data = plan_data
        return plan_data
    if job.plan_data is None:
        raise FileNotFoundError("Generate a plan first")
    return job.plan_data


def source_media_path(job: Job) -> Path | None:
    """Resolve the original source media path recorded for this job."""
    if job.raw_name:
        return job.dir / "raw" / Path(job.raw_name).name
    plan = job.plan_data
    if plan and plan.get("source"):
        source = Path(plan["source"])
        return source if source.is_absolute() else job.dir / source
    return None


def cleanup_orphaned_jobs() -> int:
    """Mark persisted uploads failed when their recorded source file is gone."""
    if not DB_AVAILABLE:
        return 0

    async def cleanup() -> int:
        assert AsyncSessionLocal is not None
        async with AsyncSessionLocal() as db:
            records = (await db.execute(
                select(JobRecord).where(JobRecord.source_path.is_not(None))
            )).scalars().all()
            changed = 0
            for record in records:
                relative = Path(record.source_path)
                source = (JOBS_ROOT / record.id / relative).resolve()
                root = (JOBS_ROOT / record.id).resolve()
                if source.is_relative_to(root) and source.is_file():
                    continue
                record.status = "failed"
                record.message = "Upload was interrupted. Please upload again."
                changed += 1
            if changed:
                await db.commit()
            return changed
    return _await_db(cleanup())


def _clear_mix(job: Job) -> None:
    """Forget the mixed output (keeps the attached track and its settings)."""
    job.music.status, job.music.progress, job.music.message = "idle", 0, ""
    job.music.output = job.music.mixed_from = None
    job.music.started_at = job.music.finished_at = None


def attach_music(job: Job, rel_path: str, name: str, duration_s: float) -> None:
    """Attach a validated track, replacing (and deleting) any previous one."""
    with _lock:
        _guard_music_edit(job)
        stale = [job.music.file if job.music.file != rel_path else None,
                 f"exports/{job.music.output}" if job.music.output else None]
        job.music.file, job.music.name, job.music.duration_s = rel_path, name, duration_s
        _clear_mix(job)
    _write_status(job)
    for rel in filter(None, stale):
        (job.dir / rel).unlink(missing_ok=True)


def detach_music(job: Job) -> None:
    """Remove the attached track and its mixed output from the job."""
    with _lock:
        _guard_music_edit(job)
        paths = [p for p in (job.music.file, f"exports/{job.music.output}" if job.music.output else None) if p]
        job.music = MusicState()
    _write_status(job)
    for rel in paths:
        (job.dir / rel).unlink(missing_ok=True)


def attached_music(job: Job) -> Optional[AttachedMusic]:
    """The job's attached background music for the Premiere export, if its file exists."""
    m = getattr(job, "music", None)
    if m is None or not m.file or not (job.dir / m.file).is_file():
        return None
    return AttachedMusic(file=job.dir / m.file, volume=m.volume, fade_in=m.fade_in, fade_out=m.fade_out)


def _guard_music_edit(job: Job) -> None:
    # Render and mix threads write their own copy of the job, so editing the
    # attachment meanwhile would be overwritten by their next status write.
    if job.render.status in {"queued", "running"}:
        raise ValueError("wait for the render to finish")
    if job.music.status in {"queued", "running"}:
        raise ValueError("wait for the music mix to finish")


def start_music_mix(job: Job, volume: float, fade_in: float, fade_out: float) -> None:
    """Save the mix settings and mix the attached music into the latest render."""
    from brain.music import validate_params
    volume, fade_in, fade_out = validate_params(volume, fade_in, fade_out)
    with _lock:
        _guard_music_edit(job)
        if not job.music.file or not (job.dir / job.music.file).is_file():
            raise FileNotFoundError("no music attached")
        if job.render.status != "done" or not job.render.output:
            raise ValueError("render the video before applying music")
        job.music.volume, job.music.fade_in, job.music.fade_out = volume, fade_in, fade_out
        job.music.status, job.music.progress, job.music.message = "queued", 0, ""
        job.music.output = job.music.mixed_from = None
        job.music.started_at, job.music.finished_at = time.time(), None
    _write_status(job)
    if CELERY_AVAILABLE:
        from app.tasks import task_mix_music
        task_mix_music.apply_async(args=(job.id,), headers=celery_request_headers())
    else:
        threading.Thread(target=_run_mix, args=(job,), daemon=True).start()


def _run_mix(job: Job, *, raise_errors: bool = False) -> None:
    """Mix `job.music` into the latest render. Never changes `job.render`."""
    try:
        from brain.music import mix_job_music
        music, source = job.music, job.render.output
        if not music.file or not source:
            raise ValueError("no music or render to mix")
        music.status, music.progress, music.message = "running", 0, "mixing"
        music.output = music.mixed_from = None  # never report a previous run's file
        music.started_at = music.started_at or time.time()
        _write_status(job)

        def report(pct: int) -> None:
            music.progress = pct
            if CELERY_AVAILABLE:
                _write_status(job)

        out = mix_job_music(job.id, music.file, volume_level=music.volume, fade_in_seconds=music.fade_in,
                            fade_out_seconds=music.fade_out, on_progress=report)
        from engine.technical_qc import inspect_export
        from brain.music import music_target_lufs
        from engine.probe import probe
        base_video = job.dir / "exports" / source
        base_stream = next(s for s in probe(base_video)["streams"] if s.get("codec_type") == "video"
                           and not s.get("disposition", {}).get("attached_pic"))
        from fractions import Fraction
        mix_fps = round(float(Fraction(base_stream["avg_frame_rate"])))
        mix_duration = float(base_stream.get("duration") or probe(base_video)["format"]["duration"])
        music.technical_qc = inspect_export(
            out, width=int(base_stream["width"]), height=int(base_stream["height"]),
            fps=mix_fps, duration=mix_duration,
            target_lufs=music_target_lufs(job),
        )
        music.output, music.mixed_from = out.name, source
        music.status, music.progress, music.message = "done", 100, ""
        music.finished_at = time.time()
        _write_status(job)
    except Exception as exc:
        job.music.status = "error"
        job.music.message = "Music mix failed. Check server logs." if settings.APP_ENV == "production" else str(exc)
        job.music.finished_at = time.time()
        _write_status(job)
        if raise_errors:
            raise


def start_render(job: Job, preview: bool = False, loudnorm: bool = True) -> None:
    with _lock:
        if job.generate.status == "running":
            raise ValueError("plan generation must finish before rendering")
        if job.render.status in {"queued", "running"}:
            return
        if job.music.status in {"queued", "running"}:
            raise ValueError("music mix must finish before rendering")
        # Reset QC state so stale issues don't persist
        job.qc = QCState()
        _clear_mix(job)  # a mix of the previous render no longer matches
        job.render = RenderState(status="queued", preview=preview, loudnorm=loudnorm,
                                 started_at=time.time())
    _write_status(job)
    if CELERY_AVAILABLE:
        from app.tasks import task_run_render
        task_run_render.apply_async(args=(job.id, preview, loudnorm), headers=celery_request_headers())
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
        locked_items: dict = {}
        if job.plan_data:
            from engine.operations import extract_locked
            locked_transitions = [dict(item) for item in job.plan_data.get("transitions", []) if item.get("locked")]
            locked_items = extract_locked(job.plan_data)
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
            "locked_items": locked_items,
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
        task_generate_plan.apply_async(args=(job.id,), headers=celery_request_headers())
    else:
        threading.Thread(
            target=_run_generate,
            args=(job, style, instruction, whisper_model, language, use_saved_transcript,
                  transcribe_only, transcription_hint, asr_engine, caption_font, caption_font_id,
                  locked_transitions, output_kind, transition_style, transition_request,
                  style_profile, style_ref, locked_items),
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
    locked_items: Optional[dict] = None,
    *,
    raise_errors: bool = False,
) -> None:
    import os
    from brain.transcribe import transcribe, effective_transcript, file_hash, choose_engine
    from brain.silence import detect_pauses
    from brain.planner import generate_plan
    from brain.llm import LLMUsage
    from brain.ai_provider import LocalFallbackProvider, get_provider

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
            wm = whisper_model or os.getenv("WHISPER_MODEL_SIZE") or os.getenv("WHISPER_MODEL")
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

        job.generate.asr_fallback_reason = str(transcript.get("fallback_reason") or "")

        asr_cost_path = job.dir / "asr_cost.json"
        if asr_cost_path.exists():
            asr_info = json.loads(asr_cost_path.read_text())
            job.generate.asr_engine = asr_info.get("engine", "")
            job.generate.asr_audio_seconds = asr_info.get("audio_seconds", 0)
            job.generate.asr_cost_usd = asr_info.get("cost_usd", 0)

        # 2. Auto-correct transcript (best-effort; never breaks the pipeline)
        if not use_saved_transcript and not isinstance(get_provider(), LocalFallbackProvider):
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
            fallback_reason = transcript.get("fallback_reason") or "no speech detected"
            plan_data = _local_plan(
                job, transcript, style, output_kind, caption_font, caption_font_id,
                transition_style, transition_request, style_ref,
                fallback_reason,
            )
            _restore_locked(plan_data, locked_items)
            _ensure_baseline_version(job)
            job.plan_data = plan_data
            job.generate.status = "done"
            job.generate.stage = ""
            # Be explicit when the AI model was bypassed because transcription
            # produced no words. A silent "plan generated without subtitles"
            # hid the fact that no LLM ran; the user needs to see that so they
            # can fix ASR (e.g. refill quota) and regenerate.
            job.generate.asr_fallback_reason = str(fallback_reason)[:500]
            job.generate.message = (
                "plan built locally without the AI model — transcription produced "
                "no words, so captions and AI edits were skipped"
            )
            job.generate.model = "local_template"
            job.generate.finished_at = time.time()
            _write_status(job)
            plan_versions.record_version(job, plan_data, "ai_generate")
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
        learned_profile = None
        if not style_profile and job.user_id is not None:
            try:
                from app import style_store
                learned_profile = style_store.load_profile(job.user_id)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("learned style profile load failed: %s", exc)
        used_local = False
        local_reason = ""
        try:
            plan_data, usage = generate_plan(
                job_dir=job.dir,
                transcript=transcript,
                keep_ranges=pauses["keep"],
                remove_ranges=pauses["remove"],
                source_rel=source_rel,
                preset_name=style,
                instruction=instruction,
                caption_font=caption_font,
                caption_font_id=caption_font_id,
                style_profile=style_profile,
                style_ref=style_ref,
                learned_profile=learned_profile,
                locked_transitions=locked_transitions,
                output_kind=output_kind,
                transition_style=transition_style,
                transition_request=transition_request,
                on_progress=lambda msg: _gen_progress(job, msg),
            )
            used_local = (plan_data.get("generation_meta") or {}).get("provider") == "local"
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "AI plan generation failed; using local fallback: %s", exc)
            local_reason = f"external AI provider failed: {exc}"[:300]
        if local_reason:
            job.generate.message = "building local plan (no external provider)…"
            _write_status(job)
            plan_data = _local_plan(
                job, transcript, style, output_kind, caption_font, caption_font_id,
                transition_style, transition_request, style_ref, local_reason,
            )
            usage = LLMUsage()
            used_local = True
        if caption_font_id:
            from engine.font_library import resolve_font
            approved_font = resolve_font(caption_font_id)
            plan_data.setdefault("canvas", {})["caption_font_id"] = caption_font_id
            plan_data["canvas"]["caption_font"] = approved_font["family"]

        # 6. Validate and save
        job.generate.stage = "validating"
        job.generate.message = "validating plan…"
        _write_status(job)

        _restore_locked(plan_data, locked_items)
        _ensure_baseline_version(job)
        job.plan_data = plan_data

        job.generate.status = "done"
        job.generate.stage = ""
        job.generate.message = "plan generated locally (no external provider)" if used_local else "plan generated"
        job.generate.cost_usd = round(usage.cost_estimate, 6)
        job.generate.input_tokens = usage.input_tokens
        job.generate.output_tokens = usage.output_tokens
        job.generate.model = usage.model
        job.generate.finished_at = time.time()
        _write_status(job)
        plan_versions.record_version(job, plan_data, "ai_generate")

    except Exception as e:
        job.generate.status = "error"
        job.generate.message = "Plan generation failed. Check server logs." if settings.APP_ENV == "production" else str(e)
        job.generate.finished_at = time.time()
        _write_status(job)
        if raise_errors:
            raise


def _restore_locked(plan_data: dict, locked_items: Optional[dict]) -> None:
    """Carry user-locked effects/captions/music into a regenerated plan.

    Falls back to the plain generated plan if re-anchoring makes it invalid.
    """
    if not locked_items:
        return
    from engine.operations import merge_locked
    import copy as _copy
    candidate = _copy.deepcopy(plan_data)
    dropped = merge_locked(candidate, locked_items)
    _, errors = validate_plan(candidate, check_media=False)
    if errors:
        dropped = [f"all locked items (re-anchoring failed: {'; '.join(errors)[:200]})"]
    else:
        plan_data.clear()
        plan_data.update(candidate)
    if dropped:
        plan_data.setdefault("generation_meta", {})
        plan_data["generation_meta"] = {**(plan_data["generation_meta"] or {}), "dropped_locks": dropped}


def _local_plan(job, transcript, style, output_kind, caption_font, caption_font_id,
                transition_style, transition_request, style_ref, reason) -> dict:
    from brain.planner import generate_plan_local

    plan_data = generate_plan_local(
        job, style=style, output_kind=output_kind, caption_font=caption_font,
        caption_font_id=caption_font_id, transition_style=transition_style,
        transition_request=transition_request, style_ref=style_ref,
        duration=float(transcript.get("duration") or 0) or None, reason=reason,
        transcript=transcript,
    )
    _, errors = validate_plan(plan_data, base_dir=job.dir, check_media=True)
    if errors:
        raise ValueError("; ".join(errors))
    return plan_data


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
        # Saved jobs can predate the current hook-first poster rating. Refresh
        # them immediately before rendering so a re-render does not keep an
        # obsolete poster choice forever.
        from brain.planner import refresh_stale_poster_rating
        if refresh_stale_poster_rating(data):
            job.plan_data = data
            _write_status(job)
        render_plan_sha256 = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
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
        build_premiere(plan, job.dir, base_dir=job.dir, attached_music=attached_music(job))

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
            job.render.message = "adding poster to video"
            poster_path = out_path.with_name(out_path.stem + "_poster.jpg")
            export_poster(
                plan, job.dir, poster_path, base_dir=job.dir, style_name=plan.style,
                style_override=style_override, style_ref=style_ref,
            )
            render_cfg = (style_override or load_style(plan.style)).get("render", {})
            embed_poster(
                out_path, poster_path,
                crf=int(render_cfg.get("preview_crf", 22) if preview else plan.export.crf),
                preset="veryfast" if preview else render_cfg.get("preset", "medium"),
            )

        from engine.technical_qc import inspect_export
        render_cfg = (style_override or load_style(plan.style)).get("render", {})
        try:
            preview_scale = float(render_cfg.get("preview_scale", 0.5))
        except (TypeError, ValueError):
            preview_scale = 0.5
        preview_scale = min(1.0, max(0.1, preview_scale))
        expected_width = max(2, int(plan.canvas.width * preview_scale) & ~1) if preview else plan.canvas.width
        expected_height = max(2, int(plan.canvas.height * preview_scale) & ~1) if preview else plan.canvas.height
        job.render.message = "checking export"
        job.render.technical_qc = inspect_export(
            out_path, width=expected_width, height=expected_height,
            fps=plan.canvas.fps, duration=plan.output_duration,
            target_lufs=float(render_cfg.get("loudness_lufs", -14)) if loudnorm else None,
        )

        job.render.output = out_name
        job.render.plan_sha256 = render_plan_sha256
        job.versions.append(out_name)
        job.render.status = "done"
        job.render.progress = 100
        job.render.finished_at = time.time()
        _write_status(job)
        if job.music.file and (job.dir / job.music.file).is_file():
            # Failure is recorded in job.music; the finished render stays valid.
            job.music.started_at = time.time()
            _run_mix(job)
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
        task_run_qc.apply_async(args=(job.id,), headers=celery_request_headers())
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
        save_plan(job, patched, source="qc",
                  operations=[c["operation"] for c in changes if c.get("operation")])
    return patched, changes
