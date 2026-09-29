"""In-memory job registry + background render worker.

One job = one folder under jobs/<id>/ with subdirs raw/, exports/ and files
plan.json, project.mlt, captions.ass, status.json.
"""
from __future__ import annotations
import json
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
class Job:
    id: str
    dir: Path
    raw_name: Optional[str] = None
    plan_name: str = "plan.json"
    render: RenderState = field(default_factory=RenderState)
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


def save_raw(job: Job, filename: str, data: bytes) -> Path:
    dst = job.dir / "raw" / filename
    dst.write_bytes(data)
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
