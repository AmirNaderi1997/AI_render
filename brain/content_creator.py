"""Content Creator orchestrator — generates Instagram content from a text prompt."""
from __future__ import annotations

import json
import hashlib
import logging
import math
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from app.celery_app import CELERY_AVAILABLE
from app.config import settings
from request_context import celery_request_headers
from engine.content_types import ContentType, get_preset
from engine.schema import PROJECT_ROOT, validate_plan
from .storyboard import Storyboard, Scene, generate_storyboard
from .media_provider import get_provider, list_providers, MediaResult, still_to_motion_video

log = logging.getLogger(__name__)


def _save_checkpoint(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    temporary.replace(path)


def _load_checkpoint(path: Path, signature: str, provider_name: str) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text())
            # Completed scene files are reusable when a failed job is retried
            # with another provider. The storyboard signature is the content
            # identity; provider choice only affects scenes that still need media.
            if isinstance(data, dict) and data.get("signature") == signature:
                data["provider"] = provider_name
                return data
        except (OSError, ValueError, TypeError):
            pass
    return {"signature": signature, "provider": provider_name, "media": [], "narration": []}


def _voice_provider() -> str:
    content_tts = os.environ.get(
        "CONTENT_TTS_PROVIDER", settings.CONTENT_TTS_PROVIDER
    ).strip().lower()
    if content_tts:
        if content_tts not in ("sarovi", "azure", "edge-tts", "elevenlabs", "disabled"):
            raise ValueError(
                "CONTENT_TTS_PROVIDER must be sarovi, azure, edge-tts, elevenlabs, or disabled"
            )
        return content_tts
    # TTS_PROVIDER is the current explicit narration contract. Keep an
    # explicitly configured legacy Sarovi route working until it is migrated.
    configured_tts = os.environ.get("TTS_PROVIDER", settings.TTS_PROVIDER).strip().lower()
    if configured_tts not in ("sarovi", "azure", "edge-tts", "elevenlabs", "disabled"):
        raise ValueError("TTS_PROVIDER must be sarovi, azure, edge-tts, elevenlabs, or disabled")
    if os.environ.get("TTS_PROVIDER") is not None:
        return configured_tts
    configured = os.environ.get("CONTENT_VOICE_PROVIDER", settings.CONTENT_VOICE_PROVIDER).strip().lower()
    if configured not in ("auto", "sarovi", "edge"):
        raise ValueError("CONTENT_VOICE_PROVIDER must be auto, sarovi, or edge")
    sarovi_configured = os.environ.get("SAROVI_API_KEY", "").strip()
    return "sarovi" if configured == "sarovi" or (configured == "auto" and sarovi_configured) else "edge"


def _default_narration_voice(language: str) -> str:
    """Choose a native locale voice for Content Creator's default narration."""
    normalized = language.lower().strip()
    if normalized in {"fa", "per", "fas", "persian", "farsi"}:
        return os.environ.get("CONTENT_TTS_VOICE_FA", "fa-IR-DilaraNeural").strip() or "fa-IR-DilaraNeural"
    return os.environ.get("CONTENT_TTS_VOICE_EN", "en-US-GuyNeural").strip() or "en-US-GuyNeural"


def _default_elevenlabs_voice(language: str) -> str:
    """Prefer an account voice trained in the requested narration language."""
    normalized = language.lower().strip()
    if normalized in {"fa", "per", "fas", "persian", "farsi"}:
        return os.environ.get("CONTENT_TTS_ELEVENLABS_VOICE_FA", "").strip()
    return os.environ.get(
        "CONTENT_TTS_ELEVENLABS_VOICE_EN",
        os.environ.get("ELEVENLABS_VOICE_ID", settings.ELEVENLABS_VOICE_ID),
    ).strip()


def create_content(
    prompt: str,
    content_type: str,
    language: str = "fa",
    style: str = "rafiei_reel",
    provider_name: str = "local_fixture",
    creative_brief: Optional[dict[str, str]] = None,
    user_id: Optional[str] = None,
) -> dict:
    from app.jobs import create_job, _write_status

    ct = ContentType(content_type)
    get_provider(provider_name)
    brief = {key: str((creative_brief or {}).get(key, "")).strip()[:500]
             for key in ("audience", "goal", "brand", "avoid")}
    brief = {key: value for key, value in brief.items() if value}
    content_llm_provider = os.environ.get(
        "CONTENT_LLM_PROVIDER", settings.CONTENT_LLM_PROVIDER
    ).strip().lower()
    storyboard = generate_storyboard(
        prompt, ct, language, style, brief,
        provider_name=content_llm_provider or None,
    )

    job = create_job(user_id=user_id)
    (job.dir / "generated").mkdir(exist_ok=True)

    storyboard_path = job.dir / "storyboard.json"
    storyboard_path.write_text(
        json.dumps(storyboard.to_dict(), indent=2, ensure_ascii=False)
    )

    gen_status = {
        "state": "pending",
        "scenes_done": 0,
        "scenes_total": len(storyboard.scenes),
        "cost_so_far": 0.0,
        "cost_status": "not_started",
        "content_type": content_type,
        "provider": provider_name,
    }
    (job.dir / "generation_status.json").write_text(json.dumps(gen_status, indent=2))

    _write_status(job)

    return {"job_id": job.id, "storyboard": storyboard.to_dict()}


def get_storyboard(job_id: str) -> Optional[dict]:
    from app.jobs import get as get_job
    job = get_job(job_id)
    if not job:
        return None
    sb_path = job.dir / "storyboard.json"
    if not sb_path.exists():
        return None
    return json.loads(sb_path.read_text())


def update_storyboard(job, scenes: list[dict]) -> Optional[dict]:
    sb_path = job.dir / "storyboard.json"
    if not sb_path.exists():
        return None

    sb_data = json.loads(sb_path.read_text())
    gs_path = job.dir / "generation_status.json"
    if gs_path.exists() and json.loads(gs_path.read_text()).get("state") == "generating":
        raise ValueError("Wait for generation to finish before editing the storyboard")
    if not scenes:
        raise ValueError("The storyboard must contain at least one scene")
    normalized = []
    for index, scene in enumerate(scenes):
        try:
            scene = Scene(**{**scene, "index": index}).to_dict()
            duration = float(scene["duration_s"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Scene {index + 1} is invalid") from exc
        if not math.isfinite(duration) or duration < 0.5:
            raise ValueError(f"Scene {index + 1} duration must be at least 0.5 seconds")
        scene["duration_s"] = duration
        normalized.append(scene)
    scenes = normalized
    preset = get_preset(sb_data["content_type"])
    if preset["is_static"] and (len(scenes) != 1 or scenes[0]["duration_s"] != 5):
        raise ValueError("A post must contain one 5-second scene")
    if preset["max_duration"] and sum(s["duration_s"] for s in scenes) > preset["max_duration"]:
        raise ValueError(f"Total duration must not exceed {preset['max_duration']} seconds")
    sb_data["scenes"] = scenes
    sb_data["total_duration_s"] = round(sum(s.get("duration_s", 0) for s in scenes), 2)
    sb_data["estimated_total_cost"] = round(sum(s.get("estimated_cost", 0) for s in scenes), 4)

    sb_path.write_text(json.dumps(sb_data, indent=2, ensure_ascii=False))

    gen_status_path = job.dir / "generation_status.json"
    if gen_status_path.exists():
        gs = json.loads(gen_status_path.read_text())
        gs["scenes_total"] = len(scenes)
        gen_status_path.write_text(json.dumps(gs, indent=2))

    return sb_data


def get_storyboard_status(job) -> Optional[dict]:
    gs_path = job.dir / "generation_status.json"
    if not gs_path.exists():
        return None
    return json.loads(gs_path.read_text())


def approve_and_generate(job, provider_name: Optional[str] = None) -> None:
    gs_path = job.dir / "generation_status.json"
    gs = json.loads(gs_path.read_text()) if gs_path.exists() else {}
    if gs.get("state") == "generating":
        return

    provider_name = provider_name or gs.get("provider") or "local_fixture"
    try:
        provider = get_provider(provider_name)
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    if not provider.has_key:
        raise ValueError(f"Provider {provider_name} is not configured")

    gs["state"] = "generating"
    gs["provider"] = provider_name
    gs.pop("error", None)
    gs_path.write_text(json.dumps(gs, indent=2))

    if CELERY_AVAILABLE:
        from app.tasks import task_generate_content
        task_generate_content.apply_async(
            args=(job.id, {"provider_name": provider_name}),
            headers=celery_request_headers(),
        )
    else:
        threading.Thread(
            target=_run_generation, args=(job.id, provider_name), daemon=True
        ).start()


def _run_generation(job_id: str, provider_name: str, *, raise_errors: bool = False) -> None:
    from app.jobs import get as get_job, _write_status

    job = get_job(job_id)
    if not job:
        return

    gs_path = job.dir / "generation_status.json"
    sb_path = job.dir / "storyboard.json"
    gen_dir = job.dir / "generated"
    gen_dir.mkdir(exist_ok=True)

    try:
        provider = get_provider(provider_name)
        sb_data = json.loads(sb_path.read_text())
        storyboard = Storyboard.from_dict(sb_data)
        content_type = ContentType(storyboard.content_type)
        preset = get_preset(content_type)
        signature = hashlib.sha256(json.dumps(sb_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        checkpoint_path = gen_dir / "generation_checkpoint.json"
        checkpoint = _load_checkpoint(checkpoint_path, signature, provider_name)
        cached_media = {
            m["scene_index"]: m for m in checkpoint["media"]
            if isinstance(m, dict) and Path(m.get("file_path", "")).is_file()
        }

        generated_media: list[dict] = []
        total_cost = 0.0
        cost_reported = True

        for scene in storyboard.scenes:
            try:
                if scene.index in cached_media:
                    record = cached_media[scene.index]
                else:
                    if preset["is_static"] or scene.media_method == "upload":
                        result = provider.generate_image(
                            scene.media_prompt or scene.description,
                            preset["aspect"],
                            gen_dir,
                        )
                    else:
                        result = provider.generate_video(
                            scene.media_prompt or scene.description,
                            scene.duration_s,
                            preset["aspect"],
                            gen_dir,
                        )
                    record = {
                        "scene_index": scene.index,
                        "file_path": result.file_path,
                        "source": result.source,
                        "cost_usd": result.cost_usd,
                        "generation_id": result.generation_id,
                        "width": result.width,
                        "height": result.height,
                        "duration_s": result.duration_s,
                        "fps": result.fps,
                        "metadata": result.metadata,
                    }
                if record["cost_usd"] is None:
                    cost_reported = False
                else:
                    total_cost += record["cost_usd"]
                generated_media.append(record)
                cached_media[scene.index] = record
                checkpoint["media"] = [cached_media[index] for index in sorted(cached_media)]
                _save_checkpoint(checkpoint_path, checkpoint)

                gs = json.loads(gs_path.read_text())
                gs["scenes_done"] = len(generated_media)
                gs["cost_so_far"] = round(total_cost, 4) if cost_reported else None
                gs["cost_status"] = "reported" if cost_reported else "not_reported_by_provider"
                gs_path.write_text(json.dumps(gs, indent=2))

            except Exception as exc:
                log.error("scene %d generation failed: %s", scene.index, exc)
                gs = json.loads(gs_path.read_text())
                gs["state"] = "failed"
                gs["error"] = f"Scene {scene.index}: {exc}"
                gs_path.write_text(json.dumps(gs, indent=2))
                if raise_errors:
                    raise
                return

        narration_segments: list[dict] = []
        warnings: list[str] = []
        voice_provider = _voice_provider()
        if voice_provider == "sarovi":
            voice_settings = ":".join((
                os.environ.get("SAROVI_TTS_MODEL", "google/gemini-3.8-flash-tts"),
                os.environ.get("SAROVI_TTS_VOICE", "Sulafat"),
                os.environ.get("SAROVI_TTS_INSTRUCTIONS", ""),
            ))
        elif voice_provider == "azure":
            # Include fallback voice and credential availability so prior audio
            # is not reused after Azure becomes available.
            voice_settings = (
                f"fa={_default_narration_voice('fa')}:"
                f"en={_default_narration_voice('en')}:"
                f"fallback_fa={_default_elevenlabs_voice('fa')}:"
                f"fallback_en={_default_elevenlabs_voice('en')}:"
                f"configured={bool(os.environ.get('AZURE_SPEECH_KEY', '').strip() and os.environ.get('AZURE_SPEECH_REGION', '').strip())}"
            )
        elif voice_provider == "elevenlabs":
            # The voice ID is safe checkpoint metadata; never persist the key.
            voice_settings = (
                f"fa={_default_elevenlabs_voice('fa')}:"
                f"en={_default_elevenlabs_voice('en')}"
            )
        elif voice_provider in ("edge", "edge-tts"):
            voice_settings = (
                f"fa={_default_narration_voice('fa')}:"
                f"en={_default_narration_voice('en')}:"
                f"rate={os.environ.get('TTS_RATE', settings.TTS_RATE)}"
            )
        else:
            voice_settings = (
                f"{os.environ.get('TTS_VOICE', settings.TTS_VOICE)}:"
                f"{os.environ.get('TTS_RATE', settings.TTS_RATE)}"
            )
        voice_signature = f"{voice_provider}:{voice_settings}"
        if checkpoint.get("voice_signature") != voice_signature:
            checkpoint["narration"] = []
        checkpoint["voice_signature"] = voice_signature
        cached_narration = {
            n["scene_index"]: n for n in checkpoint["narration"]
            if isinstance(n, dict) and Path(n.get("file_path", "")).is_file()
            and (voice_provider != "azure" or n.get("provider") == "azure")
        }
        if voice_provider == "disabled":
            log.info("narration skipped for generated content because TTS_PROVIDER=disabled")
            warnings.append("Narration skipped because TTS_PROVIDER=disabled")
        else:
            try:
                if voice_provider == "sarovi":
                    from .sarovi_voice import generate_narration
                else:
                    from .tts import generate_narration
                for scene in storyboard.scenes:
                    if not isinstance(scene.narration_text, str) or not scene.narration_text.strip():
                        continue
                    try:
                        if scene.index in cached_narration:
                            record = cached_narration[scene.index]
                        else:
                            voice = scene.narration_voice.strip() if isinstance(scene.narration_voice, str) else "default"
                            voice_kwargs = {}
                            if voice_provider in ("azure", "edge", "edge-tts"):
                                voice_kwargs["voice_id"] = (
                                    voice if voice and voice != "default"
                                    else _default_narration_voice(storyboard.language)
                                )
                                if voice_provider == "azure":
                                    voice_kwargs["fallback_voice_id"] = _default_elevenlabs_voice(storyboard.language)
                            elif voice_provider == "elevenlabs":
                                voice_kwargs["voice_id"] = (
                                    voice if voice and voice != "default"
                                    else _default_elevenlabs_voice(storyboard.language)
                                )
                                if not voice_kwargs["voice_id"]:
                                    if storyboard.language.lower().strip() in {
                                        "fa", "per", "fas", "persian", "farsi",
                                    }:
                                        raise ValueError(
                                            "Set CONTENT_TTS_ELEVENLABS_VOICE_FA to a "
                                            "Persian-native ElevenLabs voice ID for Persian content."
                                        )
                                    raise ValueError(
                                        "Set ELEVENLABS_VOICE_ID or "
                                        "CONTENT_TTS_ELEVENLABS_VOICE_EN for English content."
                                    )
                            if voice_provider == "sarovi":
                                tts_result = generate_narration(scene.narration_text, gen_dir)
                            else:
                                tts_result = generate_narration(
                                    scene.narration_text,
                                    gen_dir,
                                    provider=voice_provider,
                                    **voice_kwargs,
                                )
                            record = {
                                "scene_index": scene.index,
                                "file_path": tts_result.file_path,
                                "duration_s": tts_result.duration_s,
                                "provider": getattr(tts_result, "provider", "") or voice_provider,
                            }
                        if preset["is_static"]:
                            record = _fit_post_narration(record, gen_dir, preset, warnings)
                        narration_segments.append(record)
                        cached_narration[scene.index] = record
                        checkpoint["narration"] = [cached_narration[index] for index in sorted(cached_narration)]
                        _save_checkpoint(checkpoint_path, checkpoint)
                    except Exception as tts_exc:
                        raise RuntimeError(f"Voiceover failed for scene {scene.index + 1}: {tts_exc}") from tts_exc
            except ImportError as exc:
                if any(scene.narration_text for scene in storyboard.scenes):
                    raise RuntimeError(f"Voiceover requires the {voice_provider} provider") from exc

        if preset["is_static"]:
            if not generated_media:
                raise RuntimeError("Static content generation produced no media")
            still_path = generated_media[0]["file_path"]
            image_export = job.dir / "exports" / "post.png"
            image_export.parent.mkdir(exist_ok=True)
            import shutil
            shutil.copy2(still_path, image_export)
            motion = still_to_motion_video(
                still_path,
                gen_dir,
                5.0,
                preset["aspect"],
                generation_id=generated_media[0].get("generation_id", ""),
                cost_usd=generated_media[0].get("cost_usd"),
                source=f"{generated_media[0].get('source', 'image')}_motion",
                metadata=generated_media[0].get("metadata") or {},
            )
            generated_media[0].update({
                "file_path": motion.file_path,
                "source": motion.source,
                "width": motion.width,
                "height": motion.height,
                "duration_s": motion.duration_s,
                "fps": motion.fps,
                "metadata": motion.metadata,
            })
            source_path = motion.file_path

        narration_path = None
        if narration_segments:
            if content_type in (ContentType.STORY, ContentType.REEL):
                _fit_limited_narration(
                    generated_media, narration_segments, gen_dir, preset,
                    content_type, warnings,
                )
                checkpoint["narration"] = narration_segments
                _save_checkpoint(checkpoint_path, checkpoint)
            _fit_video_to_narration(generated_media, narration_segments, gen_dir, preset, warnings)
            checkpoint["media"] = generated_media
            _save_checkpoint(checkpoint_path, checkpoint)
            narration_path = _concat_audio(narration_segments, gen_dir, generated_media)

        if not preset["is_static"]:
            source_path = _stitch_videos(generated_media, gen_dir, preset)

        background_music_path = None
        music_source = None
        if not preset["is_static"] and settings.SAROVI_API_KEY.strip():
            cached_music = checkpoint.get("music")
            if isinstance(cached_music, dict) and Path(cached_music.get("file_path", "")).is_file():
                background_music_path = cached_music["file_path"]
                music_source = "sarovi_lyria"
            else:
                try:
                    from .sarovi_music import generate_clip
                    from engine.probe import probe
                    music_path = gen_dir / "calm_instrumental.mp3"
                    music_prompt = (
                        "Calm, warm instrumental background music for a Persian narrated social video. "
                        "Gentle piano and soft ambient textures, steady unhurried pulse, no vocals, "
                        "no speech, no dramatic hits, smooth ending. Theme: " + storyboard.prompt[:500]
                    )
                    music_path.write_bytes(generate_clip(music_prompt))
                    music_probe = probe(music_path)
                    if not any(s.get("codec_type") == "audio" for s in music_probe.get("streams", [])) or float(music_probe.get("format", {}).get("duration", 0)) <= 0:
                        raise ValueError("generated music is not playable")
                    background_music_path = str(music_path)
                    music_source = "sarovi_lyria"
                    checkpoint["music"] = {"file_path": background_music_path}
                    _save_checkpoint(checkpoint_path, checkpoint)
                except Exception as exc:
                    (gen_dir / "calm_instrumental.mp3").unlink(missing_ok=True)
                    warnings.append(f"Calm music generation failed: {exc}")
        try:
            from .asset_match import music_match
            from engine.probe import probe
            for asset in ([] if background_music_path else music_match(top_n=5)):
                candidate = Path(asset.path)
                if not candidate.is_absolute():
                    candidate = PROJECT_ROOT / candidate
                try:
                    if candidate.is_file() and any(
                        stream.get("codec_type") == "audio"
                        for stream in probe(candidate).get("streams", [])
                    ):
                        background_music_path = str(candidate)
                        music_source = "library"
                        break
                except Exception as exc:
                    log.warning("Skipping unreadable background music %s: %s", candidate.name, exc)
        except Exception as exc:
            log.warning("Background music lookup skipped: %s", exc)
        if not background_music_path:
            warnings.append("No playable background music was found in the library. Add or upload music in the plan editor.")

        provenance_path = gen_dir / "provenance.json"
        provenance_path.write_text(
            json.dumps(generated_media, indent=2, ensure_ascii=False)
        )

        plan_data = storyboard_to_plan(
            storyboard, generated_media, content_type, source_path,
            narration_path=narration_path,
            background_music_path=background_music_path,
        )
        plan_data["generation_meta"]["warnings"] = warnings
        plan_data["generation_meta"]["voice_provider"] = voice_provider if narration_segments else None
        plan_data["generation_meta"]["music_source"] = music_source
        if music_source == "sarovi_lyria" and plan_data.get("music"):
            plan_data["music"]["volume_db"] = -18.0
        job.plan_data = plan_data

        job.raw_name = None
        _write_status(job)

        gs = json.loads(gs_path.read_text())
        gs["state"] = "ready"
        gs.pop("error", None)
        gs["warnings"] = warnings
        gs["cost_so_far"] = round(total_cost, 4) if cost_reported else None
        gs["cost_status"] = "reported" if cost_reported else "not_reported_by_provider"
        gs_path.write_text(json.dumps(gs, indent=2))

    except Exception as exc:
        log.exception("content generation failed for job %s", job_id)
        gs = json.loads(gs_path.read_text())
        gs["state"] = "failed"
        gs["error"] = str(exc)
        gs_path.write_text(json.dumps(gs, indent=2))
        if raise_errors:
            raise


def _stitch_videos(media: list[dict], gen_dir: Path, preset: dict) -> str:
    if len(media) == 1:
        return media[0]["file_path"]

    concat_list = gen_dir / "concat.txt"
    lines = []
    for m in media:
        fp = m["file_path"].replace("'", "'\\''")
        lines.append(f"file '{fp}'")
    concat_list.write_text("\n".join(lines))

    out_path = gen_dir / "stitched.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(out_path),
    ], capture_output=True, check=True, timeout=120)

    return str(out_path)


def _fit_video_to_narration(
    media: list[dict], narration: list[dict], gen_dir: Path,
    preset: dict, warnings: list[str],
) -> None:
    """Extend visuals modestly to preserve narration without creating long holds."""
    by_scene = {item["scene_index"]: item for item in narration}
    targets = []
    for item in media:
        current = float(item["duration_s"])
        voice = by_scene.get(item["scene_index"])
        target = max(current, round(float(voice["duration_s"]) + 0.2, 2)) if voice else current
        targets.append(target)
    if preset["is_static"] and targets[0] > 5.0:
        raise ValueError("Post voiceover exceeds 5 seconds; shorten its script before generating")
    if preset["max_duration"] and sum(targets) > preset["max_duration"] + 0.01:
        raise ValueError(
            f"Voiceover needs {sum(targets):.1f}s, above the {preset['max_duration']}s "
            "limit. Shorten the scripts in the storyboard."
        )

    max_stretch = float(preset.get("max_scene_stretch", 1.15))
    for item, target in zip(media, targets):
        current = float(item["duration_s"])
        if target > current * max_stretch + 0.08:
            raise ValueError(
                f"Scene {item['scene_index'] + 1} narration needs {target:.1f}s, "
                f"but its visual can be held for at most {current * max_stretch:.1f}s. "
                "Shorten that scene's script in the storyboard."
            )

    for item, target in zip(media, targets):
        current = float(item["duration_s"])
        if target <= current + 0.1:
            continue
        source = Path(item["file_path"])
        out = gen_dir / f"timed_scene_{item['scene_index']}.mp4"
        ratio = target / current
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-vf", f"setpts={ratio:.8f}*(PTS-STARTPTS),fps={preset['fps']},format=yuv420p",
            "-t", str(target), "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-movflags", "+faststart", str(out),
        ], capture_output=True, check=True, timeout=max(60, round(target * 12)))
        item["file_path"] = str(out)
        item["duration_s"] = target
        item["metadata"] = {**item.get("metadata", {}), "original_duration_s": current,
                            "timing_adjustment": "stretched_to_fit_narration"}
        warnings.append(f"Scene {item['scene_index'] + 1}: visual duration extended to fit voiceover.")


def _fit_post_narration(
    record: dict, gen_dir: Path, preset: dict, warnings: list[str],
) -> dict:
    """Keep every approved word while fitting moderate speech into a five second post."""
    from .tts import _get_audio_duration

    duration = float(record["duration_s"])
    if duration <= 4.8:
        return record
    target = 4.65  # reserve room for encoder padding and the final pause
    speed = duration / target
    max_speed = float(preset.get("max_narration_speed", 1.15))
    if speed > max_speed:
        raise ValueError(
            f"Post voiceover is {duration:.1f}s and would need more than "
            f"{max_speed:.2f}x speech speed. "
            "Shorten the approved script in the storyboard."
        )
    source = Path(record["file_path"])
    output = gen_dir / f"narration_post_fit_{record['scene_index']}.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-filter:a", f"atempo={speed:.6f}", "-c:a", "libmp3lame", "-q:a", "2",
        str(output),
    ], capture_output=True, check=True, timeout=60)
    fitted_duration = _get_audio_duration(str(output))
    if not 0 < fitted_duration <= 4.8:
        output.unlink(missing_ok=True)
        raise RuntimeError("Post voiceover could not be fitted within five seconds")
    warnings.append(
        f"Post voiceover speed adjusted to {speed:.2f}x to preserve the approved script."
    )
    return {**record, "file_path": str(output), "duration_s": fitted_duration,
            "original_duration_s": duration, "timing_adjustment": "sped_up_for_post"}


def _fit_limited_narration(
    media: list[dict], narration: list[dict], gen_dir: Path,
    preset: dict, content_type: ContentType, warnings: list[str],
) -> None:
    """Fit Story or Reel speech within duration and natural pacing limits."""
    from .tts import _get_audio_duration

    if content_type not in (ContentType.STORY, ContentType.REEL):
        raise ValueError("narration fitting is for Stories and Reels")
    label = content_type.value.capitalize()
    limit = float(preset["max_duration"])
    max_speed = float(preset.get("max_narration_speed", 1.15))
    max_stretch = float(preset.get("max_scene_stretch", 1.15))
    by_scene = {item["scene_index"]: item for item in narration}
    base = sum(float(item["duration_s"]) for item in media)
    if base > limit + 0.01:
        raise ValueError(f"{label} visuals already exceed the {limit:g}s limit")

    def total_at(speed: float) -> float:
        return sum(max(
            float(item["duration_s"]),
            round(float(by_scene[item["scene_index"]]["duration_s"]) / speed + 0.2, 2),
        ) if item["scene_index"] in by_scene else float(item["duration_s"])
                   for item in media)

    def stretch_speed_needed() -> float:
        needed = 1.0
        for item in media:
            voice = by_scene.get(item["scene_index"])
            if voice is None:
                continue
            current = float(item["duration_s"])
            required = float(voice["duration_s"]) + 0.2
            if required > current * max_stretch:
                needed = max(needed, float(voice["duration_s"]) / (current * max_stretch - 0.2))
        return needed

    needed_speed = stretch_speed_needed()
    if needed_speed > max_speed + 0.001:
        raise ValueError(
            f"{label} voiceover needs {needed_speed:.2f}x speed to fit its scene visuals, "
            f"above the natural pacing limit of {max_speed:.2f}x. "
            "Shorten the affected scripts in the storyboard."
        )
    if total_at(1.0) <= limit + 0.01 and needed_speed <= 1.001:
        return
    # Leave a little room for MP3 padding and frame rounding, unless the
    # approved visuals already consume nearly all available time.
    target_total = max(base, limit - 0.15)
    if total_at(max_speed) > target_total + 0.001:
        raise ValueError(
            f"{label} voiceover cannot fit within {limit:g}s at "
            f"{max_speed:.2f}x speech speed. "
            "Shorten the approved scripts in the storyboard."
        )
    low, high = max(1.0, needed_speed), max_speed
    for _ in range(24):
        mid = (low + high) / 2
        if total_at(mid) <= target_total:
            high = mid
        else:
            low = mid
    speed = min(max_speed, high * 1.002)
    for record in narration:
        scene_media = next((m for m in media if m["scene_index"] == record["scene_index"]), None)
        if scene_media is None or float(record["duration_s"]) + 0.2 <= float(scene_media["duration_s"]):
            continue
        original_duration = float(record["duration_s"])
        source = Path(record["file_path"])
        output = gen_dir / f"narration_{content_type.value}_fit_{record['scene_index']}_{uuid.uuid4().hex[:8]}.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(source),
            "-filter:a", f"atempo={speed:.6f}", "-c:a", "libmp3lame", "-q:a", "2",
            str(output),
        ], capture_output=True, check=True, timeout=60)
        fitted_duration = _get_audio_duration(str(output))
        if fitted_duration <= 0:
            output.unlink(missing_ok=True)
            raise RuntimeError(f"{label} voiceover could not be fitted")
        record.update(file_path=str(output), duration_s=fitted_duration,
                      original_duration_s=original_duration,
                      timing_adjustment=f"sped_up_for_{content_type.value}")
    if total_at(1.0) > limit + 0.01:
        raise RuntimeError(f"{label} voiceover could not be fitted within the duration limit")
    warnings.append(f"{label} voiceover speed adjusted to {speed:.2f}x to preserve the approved scripts.")


def _concat_audio(segments: list[dict], gen_dir: Path, media: list[dict]) -> str:
    """Assemble scene narration with silence for gaps, trimmed to scene lengths."""
    if not segments:
        raise ValueError("no narration segments")
    by_scene = {s["scene_index"]: s["file_path"] for s in segments}
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    total_duration = 0.0
    for index, scene_media in enumerate(media):
        duration = float(scene_media["duration_s"])
        if duration <= 0:
            raise ValueError("scene media has no positive duration")
        total_duration += duration
        audio_file = by_scene.get(scene_media["scene_index"])
        if audio_file:
            inputs.extend(["-i", audio_file])
        else:
            inputs.extend(["-f", "lavfi", "-t", str(duration),
                           "-i", "anullsrc=r=44100:cl=stereo"])
        label = f"scene{index}"
        filters.append(
            f"[{index}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"apad,atrim=duration={duration:.6f},asetpts=PTS-STARTPTS[{label}]"
        )
        labels.append(f"[{label}]")

    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[out]")
    out_path = gen_dir / "narration_full.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", *inputs,
        "-filter_complex", ";".join(filters), "-map", "[out]",
        "-t", str(total_duration), "-c:a", "libmp3lame", str(out_path),
    ], capture_output=True, check=True, timeout=120)
    return str(out_path)


def storyboard_to_plan(
    storyboard: Storyboard,
    generated_media: list[dict],
    content_type: ContentType,
    source_path: str,
    narration_path: Optional[str] = None,
    background_music_path: Optional[str] = None,
) -> dict:
    preset = get_preset(content_type)

    segments = []
    captions = []
    cursor = 0.0
    fps = preset["fps"]

    def _snap(t: float) -> float:
        return round(t * fps) / fps

    for scene in storyboard.scenes:
        media = next(
            (m for m in generated_media if m["scene_index"] == scene.index), None
        )
        if not media:
            continue

        if preset["is_static"]:
            dur = 5.0
        elif media.get("duration_s", 0) > 0:
            dur = media["duration_s"]
        else:
            dur = scene.duration_s

        dur = _snap(dur)

        seg_id = f"s{scene.index + 1}"
        segments.append({
            "id": seg_id,
            "in": 0.0 if preset["is_static"] else _snap(cursor),
            "out": dur if preset["is_static"] else _snap(cursor + dur),
            "zoom": {"from": 1.0, "to": 1.0},
        })

        if scene.text_overlay:
            cap_start = _snap(cursor)
            cap_end = _snap(cap_start + dur)
            if len(storyboard.scenes) > 1 and scene.index == 0:
                caption_style = "cover"
            elif len(storyboard.scenes) > 1 and scene.index == len(storyboard.scenes) - 1:
                caption_style = "cta"
            else:
                caption_style = "normal"
            captions.append({
                "start": round(cap_start, 3),
                "end": round(min(cap_end, cap_start + dur), 3),
                "text": scene.text_overlay,
                "style": caption_style,
            })

        cursor += dur

    if not segments:
        raise ValueError("no segments could be built from storyboard")

    plan = {
        "version": "0.1",
        "style": storyboard.style,
        "canvas": {
            "width": preset["width"],
            "height": preset["height"],
            "fps": preset["fps"],
        },
        "source": source_path,
        "segments": segments,
        "visual_effects": [
            {"segment_id": s["id"], "type": "steady__neutral"} for s in segments
        ],
        "transitions": [],
        "captions": captions,
        "broll": [],
        "music": (
            {"file": background_music_path, "volume_db": -24.0, "duck": []}
            if background_music_path else None
        ),
        "sfx": (
            [{"at": 0.0, "file": narration_path, "volume_db": 0.0}]
            if narration_path else []
        ),
        "export": {"file": "exports/v1.mp4", "crf": 20},
        "content_type": content_type.value,
        "source_type": "generated",
        "generation_meta": {
            "provider": generated_media[0]["source"] if generated_media else "unknown",
            "total_cost": (
                round(sum(m["cost_usd"] for m in generated_media), 4)
                if all(m.get("cost_usd") is not None for m in generated_media)
                else None
            ),
            "cost_status": (
                "reported" if all(m.get("cost_usd") is not None for m in generated_media)
                else "not_reported_by_provider"
            ),
            "scene_count": len(storyboard.scenes),
            "narration_file": narration_path,
            "background_music_file": background_music_path,
        },
    }

    from brain.planner import _apply_poster
    _apply_poster(plan, [])
    return plan


def export_post_image(job_id: str) -> Optional[str]:
    from app.jobs import get as get_job
    job = get_job(job_id)
    if not job:
        return None
    image_path = job.dir / "exports" / "post.png"
    if image_path.exists():
        return str(image_path)
    gen_dir = job.dir / "generated"
    provenance = gen_dir / "provenance.json"
    if not provenance.exists():
        return None
    media = json.loads(provenance.read_text())
    if not media:
        return None
    import shutil
    src = media[0]["file_path"]
    image_path.parent.mkdir(exist_ok=True)
    shutil.copy2(src, image_path)
    return str(image_path)
