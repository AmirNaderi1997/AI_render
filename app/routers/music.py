"""Music API routes."""
from __future__ import annotations

from pathlib import Path
import asyncio
import io
import shutil
import tempfile
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from app import jobs as jobstore
from app.job_access import require_job_access

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".aac", ".m4a"}

router = APIRouter(prefix="/jobs", tags=["music"], dependencies=[Depends(require_job_access)])
legacy_router = APIRouter(tags=["music"])


def _validate_energy(energy: Optional[int]) -> None:
    """Energy must be 1-5 to match LibraryAsset; reject out-of-range up front
    so it never reaches the pydantic model as an unhandled 500 (and, worse,
    never gets written to a sidecar that would then break the whole index)."""
    if energy is not None and not (1 <= energy <= 5):
        raise HTTPException(422, "energy must be between 1 and 5")


@legacy_router.get("/library")
def get_library():
    from engine.library import library_for_api
    return library_for_api()


@legacy_router.post("/library/rescan")
def rescan_library():
    from engine.library import scan_library
    index = scan_library()
    return {"ok": True, "counts": index.counts()}


@legacy_router.post("/library/upload")
async def upload_library_asset(
    file: UploadFile = File(...),
    category: str = Form(...),
    tags: str = Form(""),
    mood: str = Form(""),
    energy: Optional[int] = Form(None),
    description: str = Form(""),
):
    from engine.library import add_asset, CATEGORIES
    if category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    _validate_energy(energy)
    content = await file.read()
    if len(content) > 100_000_000:
        raise HTTPException(413, "file must be at most 100 MB")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    asset = add_asset(
        category=category,
        filename=file.filename or "asset",
        data=content,
        tags=tag_list or None,
        mood=mood or None,
        energy=energy,
        description=description or None,
    )
    return asset.model_dump()


class UpdateAssetBody(BaseModel):
    tags: Optional[list[str]] = None
    mood: Optional[str] = None
    energy: Optional[int] = None
    description: Optional[str] = None


class GenerateMusicBody(BaseModel):
    prompt: str


class MixBody(BaseModel):
    """Mix settings; omitted fields fall back to the defaults (30% / 2s in / 3s out)."""
    volume_level: float = Field(0.3, ge=0.0, le=1.0)
    fade_in_seconds: float = Field(2.0, ge=0.0, le=60.0)
    fade_out_seconds: float = Field(3.0, ge=0.0, le=60.0)


@legacy_router.put("/library/{category}/{filename}")
def update_library_asset(category: str, filename: str, body: UpdateAssetBody):
    from engine.library import update_asset_tags, CATEGORIES
    if category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    _validate_energy(body.energy)
    result = update_asset_tags(category, filename,
                               tags=body.tags, mood=body.mood,
                               energy=body.energy, description=body.description)
    if not result:
        raise HTTPException(404, "asset not found")
    return result.model_dump()


@legacy_router.delete("/library/{category}/{filename}")
def delete_library_asset(category: str, filename: str):
    from engine.library import remove_asset, CATEGORIES
    if category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    removed = remove_asset(category, filename)
    if not removed:
        raise HTTPException(404, "asset not found")
    return {"ok": True}


@legacy_router.get("/library/{category}/{filename}/preview")
def preview_library_asset(category: str, filename: str):
    from engine.library import LIBRARY_ROOT, CATEGORIES
    if category not in CATEGORIES:
        raise HTTPException(422, f"category must be one of {CATEGORIES}")
    path = LIBRARY_ROOT / category / filename
    if not path.is_file():
        raise HTTPException(404, "asset not found")
    return FileResponse(path)


@legacy_router.post("/library/match/broll")
def match_broll(query: str = Form(...), min_duration: float = Form(0.0)):
    from brain.asset_match import broll_match
    matches = broll_match(query, min_duration=min_duration)
    return [m.model_dump() for m in matches]


@router.post("/{job_id}/music/upload")
async def upload_music(job_id: str, file: UploadFile = File(...)):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    fname = file.filename or "music.mp3"
    ext = Path(fname).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise HTTPException(422, f"Music format not supported: {ext}. Use mp3, wav, ogg, aac, or m4a.")
    try:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
    except (AttributeError, OSError):
        size = None
    if size == 0:
        raise HTTPException(422, "Music upload is empty")
    if size is not None and size > 100_000_000:
        raise HTTPException(413, "Music file must be at most 100 MB")
    # Validate before saving so a corrupt replacement cannot overwrite a track.
    from engine.probe import probe
    with tempfile.NamedTemporaryFile(suffix=ext) as pending:
        shutil.copyfileobj(file.file, pending)
        pending.flush()
        try:
            metadata = probe(Path(pending.name))
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise ValueError("no audio stream")
            if float(metadata.get("format", {}).get("duration", 0)) <= 0:
                raise ValueError("no playable duration")
        except Exception as exc:
            raise HTTPException(422, "Music file has no playable audio") from exc
        pending.seek(0)
        name = f"{Path(fname).stem}_{uuid.uuid4().hex[:8]}{ext}"
        dst = jobstore.save_music(job, name, pending)
    return {"ok": True, "path": f"music/{dst.name}"}


@router.post("/{job_id}/music/generate")
async def generate_music(job_id: str, body: GenerateMusicBody):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    from brain.sarovi_music import MusicGenerationError, generate_clip
    from engine.probe import probe
    try:
        audio = await asyncio.to_thread(generate_clip, body.prompt)
    except MusicGenerationError as exc:
        raise HTTPException(422, str(exc)) from exc
    with tempfile.NamedTemporaryFile(suffix=".mp3") as pending:
        pending.write(audio)
        pending.flush()
        try:
            metadata = probe(Path(pending.name))
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise ValueError("no audio stream")
            if float(metadata.get("format", {}).get("duration", 0)) <= 0:
                raise ValueError("no playable duration")
        except Exception as exc:
            raise HTTPException(502, "Sarovi returned audio that cannot be played") from exc
    name = f"sarovi_lyria_{uuid.uuid4().hex[:8]}.mp3"
    dst = jobstore.save_music(job, name, io.BytesIO(audio))
    return {"ok": True, "path": f"music/{dst.name}"}


def _music_status(job) -> dict:
    m = job.music
    return {
        "attached": bool(m.file), "file": m.file, "name": m.name, "duration_s": m.duration_s,
        "volume_level": m.volume, "fade_in_seconds": m.fade_in, "fade_out_seconds": m.fade_out,
        "status": m.status, "progress": m.progress, "message": m.message,
        "output": m.output, "mixed_from": m.mixed_from,
        "technical_qc": m.technical_qc,
    }


@router.post("/{job_id}/music")
async def attach_music(job_id: str, file: UploadFile = File(...)):
    """Upload a track and attach it to the job (replaces any attached track)."""
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    fname = file.filename or "music.mp3"
    ext = Path(fname).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise HTTPException(422, f"Music format not supported: {ext}. Use mp3, wav, ogg, aac, or m4a.")
    try:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
    except (AttributeError, OSError):
        size = None
    if size == 0:
        raise HTTPException(422, "Music upload is empty")
    if size is not None and size > 100_000_000:
        raise HTTPException(413, "Music file must be at most 100 MB")
    from brain.music import probe_music
    with tempfile.NamedTemporaryFile(suffix=ext) as pending:
        shutil.copyfileobj(file.file, pending)
        pending.flush()
        try:
            duration = probe_music(Path(pending.name))
        except ValueError as exc:
            raise HTTPException(422, "Music file has no playable audio") from exc
        pending.seek(0)
        dst = jobstore.save_music(job, f"attached_{uuid.uuid4().hex[:8]}{ext}", pending)
    try:
        jobstore.attach_music(job, f"music/{dst.name}", Path(fname).name, duration)
    except ValueError as exc:
        dst.unlink(missing_ok=True)
        raise HTTPException(409, str(exc)) from exc
    return _music_status(job)


@router.post("/{job_id}/music/mix", status_code=202)
def mix_music(job_id: str, body: MixBody = MixBody()):
    """Mix the attached track into the latest render in the background."""
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    try:
        jobstore.start_music_mix(job, body.volume_level, body.fade_in_seconds, body.fade_out_seconds)
    except FileNotFoundError as exc:
        raise HTTPException(404, "no music attached") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": job.music.status}


@router.get("/{job_id}/music/status")
def music_status(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return _music_status(job)


@router.delete("/{job_id}/music")
def remove_music(job_id: str):
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    try:
        jobstore.detach_music(job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


def _mixed_preview(job, volume_level, fade_in_seconds, fade_out_seconds):
    from brain.music import MusicMixError, build_preview
    m = job.music
    music = job.dir / m.file
    if not music.is_file():
        raise HTTPException(404, "music file not found")
    video = None
    if job.render.output and (job.dir / "exports" / job.render.output).is_file():
        video = job.dir / "exports" / job.render.output
    else:
        video = jobstore.source_media_path(job)
        if video is None or not video.is_file():
            raise HTTPException(404, "Source media missing")
    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as handle:
        out = Path(handle.name)
    try:
        build_preview(
            video, music, out,
            volume_level=m.volume if volume_level is None else volume_level,
            fade_in_seconds=m.fade_in if fade_in_seconds is None else fade_in_seconds,
            fade_out_seconds=m.fade_out if fade_out_seconds is None else fade_out_seconds,
        )
    except (MusicMixError, ValueError) as exc:
        out.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    return FileResponse(out, media_type="audio/mp4", filename="music_preview.m4a",
                        background=BackgroundTask(out.unlink, missing_ok=True))


@router.get("/{job_id}/music/preview")
def preview_music(
    job_id: str,
    filename: Optional[str] = None,
    volume_level: Optional[float] = Query(None, ge=0.0, le=1.0),
    fade_in_seconds: Optional[float] = Query(None, ge=0.0, le=60.0),
    fade_out_seconds: Optional[float] = Query(None, ge=0.0, le=60.0),
):
    """With ?filename= returns that raw upload. Otherwise, when a track is
    attached, returns a 30-second preview of the mix (query params override the
    saved settings); with nothing attached it falls back to the first upload."""
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    if filename is None and getattr(getattr(job, "music", None), "file", None):
        return _mixed_preview(job, volume_level, fade_in_seconds, fade_out_seconds)
    music_dir = job.dir / "music"
    if not music_dir.is_dir():
        raise HTTPException(404, "no music uploaded")
    if filename is not None:
        if Path(filename).name != filename or Path(filename).suffix.lower() not in AUDIO_EXTENSIONS:
            raise HTTPException(422, "invalid music filename")
        selected = music_dir / filename
        if not selected.is_file():
            raise HTTPException(404, "music file not found")
        return FileResponse(selected)
    files = [f for f in music_dir.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]
    if not files:
        raise HTTPException(404, "no music file found")
    return FileResponse(files[0])
