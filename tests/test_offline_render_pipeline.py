"""Fresh API-to-video acceptance with local fixtures and no provider calls."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import auth, jobs as jobstore
from brain.llm import LLMUsage
from brain import planner, silence, transcribe
from engine.captions import load_style
from engine.probe import probe, probe_duration, video_stream


def _make_media(path: Path, source_duration: float, *, frequency: int,
                size: str = "320x240") -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"testsrc2=size={size}:rate=30:duration={source_duration}",
        "-f", "lavfi", "-i",
        f"sine=frequency={frequency}:sample_rate=48000:duration={source_duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ], check=True, capture_output=True)


def _tone_amplitude(path: Path, frequency: float, start: float) -> float:
    decoded = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(start), "-t", "0.2", "-i", str(path),
        "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-",
    ])
    samples = np.frombuffer(decoded, dtype="<f4")
    if not len(samples):
        return 0.0
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    bins = np.fft.rfftfreq(len(samples), d=1 / 48000)
    band = (bins >= frequency - 20) & (bins <= frequency + 20)
    return float(spectrum[band].max() / len(samples)) if np.any(band) else 0.0


def _wait_for(client: TestClient, url: str, expected: str, timeout: float = 90) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        response = client.get(url, headers={"Authorization": "Bearer offline-test"})
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in {"done", "error"}:
            assert last["status"] == expected, last
            return last
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {expected}: {last}")


def test_offline_generate_style_font_transition_music_preview_and_final(
        tmp_path, monkeypatch):
    if not shutil.which("melt"):
        pytest.skip("melt is required for the offline render acceptance")

    from engine import font_library, style_library

    jobs_root = tmp_path / "jobs"
    monkeypatch.setattr(jobstore, "JOBS_ROOT", jobs_root)
    monkeypatch.setattr(jobstore, "_jobs", {})
    monkeypatch.setattr(auth, "get_current_user_from_token",
                        lambda _token: SimpleNamespace(id="offline-test-user"))

    # Keep font import/approval inside this test's temporary storage.
    font_root = tmp_path / "font-library"
    monkeypatch.setattr(font_library, "LIBRARY_ROOT", font_root)
    monkeypatch.setattr(font_library, "CANDIDATES", font_root / "candidates")
    monkeypatch.setattr(font_library, "APPROVED", font_root / "approved")
    monkeypatch.setattr(font_library, "INDEX", font_root / "library.json")

    # Use an approved, imported style profile but avoid mutating the project's
    # persistent style library.
    imported_style = copy.deepcopy(load_style("rafiei_reel"))
    imported_style["captions"]["base"]["size"] = 46
    imported_style["render"].update({
        "preview_scale": 0.75,
        "preview_crf": 21,
        "preset": "ultrafast",
        "loudness_lufs": -18,
    })
    monkeypatch.setattr(style_library, "get_profile",
                        lambda _style_id, _version: {"name": "Offline imported look"})
    monkeypatch.setattr(style_library, "resolve_preset",
                        lambda _style_id, _version: copy.deepcopy(imported_style))

    # Remove machine-specific My Effects preferences from this deterministic run.
    def clean_effect_preferences(instance):
        instance.favorites = {}
        instance.rules = []
        instance.dislikes = set()
        instance.custom_assets = {}
        instance.selected_rafiei_style = None
    monkeypatch.setattr("engine.effects_v4.MyEffectsPreset.load", clean_effect_preferences)

    # Local fixture replaces provider-dependent calls while the planner's
    # validation, timing, selection, transition and poster logic remains real.
    model_plan = {
        "version": "0.3",
        "style": "rafiei_reel",
        "canvas": {"width": 360, "height": 640, "fps": 30},
        "source": "raw/offline-clip.mp4",
        "segments": [
            {"id": "s1", "in": 0.0, "out": 1.4},
            {"id": "s2", "in": 1.5, "out": 3.0},
        ],
        "captions": [
            {"start": 0.1, "end": 0.8, "text": "این آزمایش خیلی خوب است", "style": "emphasis"},
            {"start": 1.5, "end": 2.5, "text": "نتیجه را ببینید", "style": "normal"},
        ],
        "music": {
            "file": "music/selected.wav",
            "volume_db": -12,
            "duck": [{"start": 0.8, "end": 1.2, "volume_db": -48}],
        },
        "export": {"file": "exports/v1.mp4", "crf": 17},
    }
    provider = type("OfflineProvider", (), {
        "generate_plan": lambda self, *_args, **_kwargs: (
            copy.deepcopy(model_plan),
            LLMUsage(input_tokens=1, output_tokens=1, model="offline-fixture"),
        )
    })()
    monkeypatch.setattr(planner, "get_provider", lambda: provider)
    monkeypatch.setattr(planner, "measure_segment_signals", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(planner, "analyse_segments", lambda segments, *_args, **_kwargs: (
        [
            {"segment_id": "s1", "role": "hook", "energy": 4,
             "shareability_score": 10, "is_turning_point": True},
            {"segment_id": "s2", "role": "claim", "energy": 3,
             "shareability_score": 6, "is_turning_point": False},
        ], LLMUsage(model="offline-analysis")
    ))
    monkeypatch.setattr(planner, "_apply_scored_effects", lambda data, *_args, **_kwargs: (
        data.update(visual_effects=[
            {"segment_id": "s1", "type": "punch__lift_soft"},
            {"segment_id": "s2", "type": "slow_push__neutral"},
        ]) or LLMUsage(model="offline-effects")
    ))
    monkeypatch.setattr(silence, "detect_pauses", lambda *_args, **_kwargs: {
        "keep": [(0.0, 3.0)], "remove": [],
    })

    auth_headers = {"Authorization": "Bearer offline-test"}
    raw = tmp_path / "offline-clip.mp4"
    music = tmp_path / "selected.wav"
    _make_media(raw, 3.0, frequency=440, size="360x640")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=880:sample_rate=48000:duration=0.5", "-ac", "2", str(music),
    ], check=True, capture_output=True)

    with TestClient(app) as client:
        font_path = Path(__file__).resolve().parents[1] / "presets" / "fonts" / "RAY-EXTRABLACK.TTF"
        imported = client.post("/font-library/font", headers=auth_headers,
                               files={"font": (font_path.name, font_path.read_bytes(), "font/ttf")})
        assert imported.status_code == 200, imported.text
        approved = client.post(f"/font-library/{imported.json()['id']}/approve", headers=auth_headers)
        assert approved.status_code == 200, approved.text
        font_id = approved.json()["id"]

        created = client.post("/jobs", headers=auth_headers,
                              files={"video": (raw.name, raw.read_bytes(), "video/mp4")})
        assert created.status_code == 201, created.text
        job = created.json()["job"]
        job_id = job["id"]
        job_dir = Path(job["dir"])
        assert job_dir.parent == jobs_root

        music_response = client.post(f"/jobs/{job_id}/music/upload", headers=auth_headers,
                                     files={"file": (music.name, music.read_bytes(), "audio/wav")})
        assert music_response.status_code == 200, music_response.text
        model_plan["music"]["file"] = music_response.json()["path"]
        digest = transcribe.file_hash(job_dir / "raw" / raw.name)
        transcript = {
            "file_hash": digest,
            "cache_key": digest,
            "language": "fa",
            "duration": 3.0,
            "words": [
                {"w": "این", "start": 0.1, "end": 0.3},
                {"w": "آزمایش", "start": 0.3, "end": 0.7},
                {"w": "خیلی", "start": 0.8, "end": 1.1},
                {"w": "خوب", "start": 1.1, "end": 1.4},
                {"w": "نتیجه", "start": 1.5, "end": 1.9},
                {"w": "را", "start": 1.9, "end": 2.1},
                {"w": "ببینید", "start": 2.1, "end": 2.5},
            ],
            "sentences": [
                {"start": 0.1, "end": 1.4, "text": "این آزمایش خیلی خوب"},
                {"start": 1.5, "end": 2.5, "text": "نتیجه را ببینید"},
            ],
        }
        (job_dir / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False))

        generated = client.post(f"/jobs/{job_id}/generate-plan", headers=auth_headers, json={
            "use_saved_transcript": True,
            "language": "fa",
            "asr_engine": "whisper",
            "caption_font_id": font_id,
            "style_id": "offline-style",
            "style_version": 1,
            "output_kind": "reel",
            "transition_style": "crossfade",
        })
        assert generated.status_code == 200, generated.text
        _wait_for(client, f"/jobs/{job_id}/generate-plan/status", "done")
        plan = client.get(f"/jobs/{job_id}", headers=auth_headers).json()["plan"]

        assert plan["music"]["file"] == music_response.json()["path"]
        assert plan["canvas"]["caption_font_id"] == font_id
        assert plan["style_profile"] == {"style_id": "offline-style", "version": 1,
                                          "name": "Offline imported look"}
        assert "cover" not in plan
        assert plan["poster"]["source_caption_index"] == 0
        assert plan["transitions"][0]["type"] == "crossfade"
        assert plan["transitions"][0]["duration_frames"] == 6
        assert plan["captions"][1]["start"] < 1.5  # retimed onto the overlap timeline

        for preview in (True, False):
            started = client.post(f"/jobs/{job_id}/render?preview={str(preview).lower()}&loudnorm=true",
                                  headers=auth_headers)
            assert started.status_code == 202, started.text
            _wait_for(client, f"/jobs/{job_id}/render/status", "done")
            current = jobstore.get(job_id)
            assert current is not None and current.render.output
            output = job_dir / "exports" / current.render.output
            assert output.is_file() and output.stat().st_size > 5000
            video = video_stream(output)
            expected_size = (270, 480) if preview else (360, 640)
            assert (int(video["width"]), int(video["height"])) == expected_size
            assert abs(probe_duration(output) - plan_duration(plan)) <= 1 / 30 + 0.02
            assert video.get("codec_name") == "h264"
            assert any(stream.get("codec_type") == "audio" for stream in probe(output)["streams"])

        final = job_dir / "exports" / jobstore.get(job_id).render.output
        # Very short synthetic tones fall below EBU R128's loudness gate even
        # when the encoded audio is present, so verify the voice/music spectra.
        voice = _tone_amplitude(final, 440, 0.3)
        assert voice > 0.001
        music_before = _tone_amplitude(final, 880, 0.3)
        music_ducked = _tone_amplitude(final, 880, 0.95)
        music_after = _tone_amplitude(final, 880, 1.8)
        assert music_before > 0.0001 and music_ducked > 0
        assert music_before > music_ducked * 3, (music_before, music_ducked)
        assert music_after > music_ducked * 3, (music_ducked, music_after)

        project = (job_dir / "project.mlt").read_text()
        assert "boundary_video_0" in project
        assert '<property name="ai-render:type">crossfade</property>' in project
        assert font_id in project
        assert (job_dir / "assets" / "fonts").is_dir()
        assert (job_dir / "exports" / "v2_poster.jpg").is_file()
        assert (job_dir / "project_premiere.xml").is_file()


def plan_duration(plan: dict) -> float:
    frames = sum(round((segment["out"] - segment["in"]) * plan["canvas"]["fps"])
                 for segment in plan["segments"])
    frames -= sum(transition["duration_frames"] for transition in plan.get("transitions", []))
    return frames / plan["canvas"]["fps"]
