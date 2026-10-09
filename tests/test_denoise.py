"""Tests for the denoise feature."""
from __future__ import annotations

import json
import subprocess
import shutil
import wave
from array import array
from math import pi, sin, cos
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def tmp_audio(tmp_path):
    """Generate a short WAV with ffmpeg (sine + noise)."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not found")
    out = tmp_path / "test.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=3",
        "-ar", "44100", "-ac", "1", str(out),
    ], check=True, capture_output=True)
    return out


@pytest.fixture
def tmp_video(tmp_path):
    """Generate a short video with audio."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not found")
    out = tmp_path / "test.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-shortest", str(out),
    ], check=True, capture_output=True)
    return out


class TestExtractSpeechAudio:
    def test_extract_produces_wav(self, tmp_video, tmp_path):
        from engine.denoise import extract_speech_audio
        result = extract_speech_audio(tmp_video, out_dir=tmp_path / "audio")
        assert result.exists()
        assert result.suffix == ".wav"

    def test_extract_missing_file(self, tmp_path):
        from engine.denoise import extract_speech_audio
        with pytest.raises(FileNotFoundError):
            extract_speech_audio(tmp_path / "nonexistent.mp4")


class TestDenoiseSpeech:
    def test_bypass_strength_zero(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech
        result = denoise_speech(tmp_audio, strength=0.0, out_dir=tmp_path)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_strength_half(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech
        result = denoise_speech(tmp_audio, strength=0.5, out_dir=tmp_path)
        assert result.exists()
        assert "0.50" in result.name

    def test_strength_full(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech
        result = denoise_speech(tmp_audio, strength=1.0, out_dir=tmp_path)
        assert result.exists()

    def test_same_duration(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech, _probe_audio
        result = denoise_speech(tmp_audio, strength=0.5, out_dir=tmp_path)
        orig = _probe_audio(tmp_audio)
        cleaned = _probe_audio(result)
        assert abs(orig["duration"] - cleaned["duration"]) < 0.2


class TestABSamples:
    def test_generates_two_clips(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech, generate_ab_samples
        cleaned = denoise_speech(tmp_audio, strength=0.5, out_dir=tmp_path)
        samples = generate_ab_samples(tmp_audio, cleaned)
        assert samples["original_sample"].exists()
        assert samples["cleaned_sample"].exists()
        assert samples["duration_s"] > 0

    def test_same_offset(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech, generate_ab_samples
        cleaned = denoise_speech(tmp_audio, strength=0.5, out_dir=tmp_path)
        samples = generate_ab_samples(tmp_audio, cleaned, sample_offset=0.5)
        assert samples["offset_s"] == 0.5

    @pytest.mark.parametrize("channels", [1, 2])
    def test_subsecond_samples_keep_channels_and_duration(self, tmp_path, channels):
        from engine.denoise import denoise_speech, generate_ab_samples, _probe_audio
        original = tmp_path / "short.wav"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
            "-ac", str(channels), str(original),
        ], check=True, capture_output=True)
        cleaned = denoise_speech(original, out_dir=tmp_path)
        samples = generate_ab_samples(original, cleaned)
        for key in ("original_sample", "cleaned_sample"):
            info = _probe_audio(samples[key])
            assert info["channels"] == channels
            assert 0.25 <= info["duration"] <= 0.31


def test_short_silence_is_detected(tmp_path):
    from engine.denoise import detect_silence
    silent = tmp_path / "silent.wav"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", "0.3", str(silent),
    ], check=True, capture_output=True)
    assert detect_silence(silent)


class TestMeasureQuality:
    def test_returns_valid_loudness(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech, measure_quality
        cleaned = denoise_speech(tmp_audio, strength=0.5, out_dir=tmp_path)
        q = measure_quality(tmp_audio, cleaned)
        assert q["duration_match"] is True
        assert q["sample_rate_match"] is True
        assert q["loudness_original"] is not None


class TestDenoiseState:
    def test_serialization_roundtrip(self):
        from brain.denoise_manager import DenoiseState
        state = DenoiseState(
            status="ready", strength=0.7, approved=True,
            original_audio="/tmp/orig.wav", cleaned_audio="/tmp/clean.wav",
        )
        d = state.to_dict()
        restored = DenoiseState.from_dict(d)
        assert restored.status == "ready"
        assert restored.strength == 0.7
        assert restored.approved is True

    def test_approve_bypass_toggle(self, tmp_path):
        from brain.denoise_manager import (
            DenoiseState, _states, _save_state, approve_cleaned,
            set_bypass, get_state,
        )
        job_id = "test123"
        state = DenoiseState(status="ready", cleaned_audio="/tmp/c.wav")
        _states[job_id] = state
        _save_state(tmp_path, state)

        approved = approve_cleaned(job_id, tmp_path)
        assert approved.approved is True
        assert approved.bypass is False

        bypassed = set_bypass(job_id, tmp_path, True)
        assert bypassed.bypass is True
        assert bypassed.approved is False

        # Clean up
        _states.pop(job_id, None)

    def test_source_without_audio_is_skipped(self, tmp_path):
        from brain.denoise_manager import DenoiseState, _states, _run_denoise
        raw = tmp_path / "raw" / "silent_video.mp4"
        raw.parent.mkdir()
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=160x120:r=30:d=1", "-an", str(raw),
        ], check=True, capture_output=True)
        (tmp_path / "plan.json").write_text(json.dumps({"source": "raw/silent_video.mp4"}))
        job_id = "no-audio-source"
        _states[job_id] = DenoiseState(status="processing")
        try:
            _run_denoise(job_id, tmp_path, 0.5, raise_errors=True)
            assert _states[job_id].status == "skipped"
            assert _states[job_id].cleaned_audio is None
        finally:
            _states.pop(job_id, None)


class TestDenoisePlanSync:
    def test_start_clears_previous_approval_before_new_processing(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from app.routers import denoise
        from app import jobs as jobstore
        from brain.denoise_manager import DenoiseState

        (tmp_path / "plan.json").write_text("{}")
        plan = {"source": "raw/source.mp4", "denoise": {
            "enabled": True, "strength": 0.5, "audio_file": "audio/old.wav"}}
        monkeypatch.setattr(jobstore, "get", lambda _id: SimpleNamespace(dir=tmp_path))
        monkeypatch.setattr(jobstore, "load_plan", lambda _job: dict(plan))
        def save_plan(_job, data):
            plan.clear()
            plan.update(data)
            return data, []
        monkeypatch.setattr(jobstore, "save_plan", save_plan)
        monkeypatch.setattr("brain.denoise_manager.get_state", lambda *_: DenoiseState(status="ready"))

        def start(_job_id, _job_dir, strength):
            assert "denoise" not in plan
            return DenoiseState(status="processing", strength=strength)

        monkeypatch.setattr("brain.denoise_manager.start_denoise", start)
        denoise.denoise_start("job", denoise.DenoiseStartBody(strength=0.7))
        assert "denoise" not in plan

    def test_approval_enables_cleaned_track_and_bypass_removes_it(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        from app.routers import denoise
        from app import jobs as jobstore
        from brain.denoise_manager import DenoiseState

        (tmp_path / "plan.json").write_text("{}")
        cleaned = tmp_path / "audio" / "clean.wav"
        cleaned.parent.mkdir()
        cleaned.write_bytes(b"audio")
        job = SimpleNamespace(dir=tmp_path)
        plan = {"source": "raw.mp4"}
        monkeypatch.setattr(jobstore, "load_plan", lambda _job: dict(plan))
        saved = {}

        def save_plan(_job, data):
            plan.clear()
            plan.update(data)
            saved.clear()
            saved.update(data)
            return data, []

        monkeypatch.setattr(jobstore, "save_plan", save_plan)
        denoise._sync_denoise_plan(job, DenoiseState(
            status="ready", strength=0.7, approved=True, cleaned_audio=str(cleaned)))
        assert saved["denoise"] == {
            "enabled": True, "strength": 0.7, "audio_file": "audio/clean.wav"}

        denoise._sync_denoise_plan(job, DenoiseState(status="ready", bypass=True))
        assert "denoise" not in saved

    def test_interrupted_worker_is_retryable_after_restart(self, tmp_path):
        from brain.denoise_manager import DenoiseState, _states, _save_state, get_state
        job_id = "interrupted123"
        _states.pop(job_id, None)
        _save_state(tmp_path, DenoiseState(status="processing", strength=0.6))

        recovered = get_state(job_id, tmp_path)

        assert recovered.status == "error"
        assert "interrupted by an app restart" in recovered.message
        assert recovered.finished_at is not None
        assert json.loads((tmp_path / "audio" / "denoise_state.json").read_text())["status"] == "error"
        _states.pop(job_id, None)

    def test_start_rejects_non_finite_or_out_of_range_strength(self, tmp_path):
        from brain.denoise_manager import start_denoise
        for strength in (float("nan"), float("inf"), -0.01, 1.01):
            with pytest.raises(ValueError, match="between 0 and 1"):
                start_denoise(f"bad-{strength}", tmp_path, strength)


class TestEditPlanBackcompat:
    def test_none_denoise(self):
        from engine.schema import EditPlan
        plan_data = {
            "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "source": "raw/test.mp4",
            "segments": [{"id": "s1", "in": 0, "out": 3}],
            "export": {"file": "out.mp4"},
        }
        plan = EditPlan(**plan_data)
        assert plan.denoise is None

    def test_denoise_enabled(self):
        from engine.schema import EditPlan
        plan_data = {
            "canvas": {"width": 1080, "height": 1920, "fps": 30},
            "source": "raw/test.mp4",
            "segments": [{"id": "s1", "in": 0, "out": 3}],
            "denoise": {"enabled": True, "strength": 0.5, "audio_file": "audio/speech_cleaned_0.50.wav"},
            "export": {"file": "out.mp4"},
        }
        plan = EditPlan(**plan_data)
        assert plan.denoise["enabled"] is True


class TestBuildMLTDenoise:
    def test_render_uses_cleaned_audio_instead_of_camera_audio(self, tmp_path):
        if not shutil.which("melt") and not shutil.which("melt-7"):
            pytest.skip("melt not found")
        raw = tmp_path / "raw" / "source.mp4"
        raw.parent.mkdir()
        cleaned = tmp_path / "audio" / "clean.wav"
        cleaned.parent.mkdir()
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=30:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(raw),
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=1320:duration=1",
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
            "-map", "[a]", "-ac", "1", str(cleaned),
        ], check=True, capture_output=True)
        from engine.schema import EditPlan
        from engine.build_mlt import build
        plan = EditPlan(**{
            "canvas": {"width": 160, "height": 120, "fps": 30},
            "source": "raw/source.mp4",
            "segments": [{"id": "s1", "in": 1, "out": 2},
                         {"id": "s2", "in": 0, "out": 1}],
            "denoise": {"enabled": True, "strength": 0.5, "audio_file": "audio/clean.wav"},
            "export": {"file": "out.mp4"},
        })
        mlt, _ = build(plan, tmp_path / "build", base_dir=tmp_path)
        output = tmp_path / "render.wav"
        subprocess.run([
            shutil.which("melt") or shutil.which("melt-7"), str(mlt),
            "-consumer", f"avformat:{output}", "acodec=pcm_s16le", "vn=1",
        ], check=True, capture_output=True)
        with wave.open(str(output)) as stream:
            rate = stream.getframerate()
            channels = stream.getnchannels()
            samples = array("h", stream.readframes(stream.getnframes()))[::channels]
        def energy(window, frequency):
            real = sum(value * cos(2 * pi * frequency * index / rate)
                       for index, value in enumerate(window))
            imag = sum(value * sin(2 * pi * frequency * index / rate)
                       for index, value in enumerate(window))
            return real * real + imag * imag
        first = samples[int(rate * 0.2):int(rate * 0.8)]
        second = samples[int(rate * 1.2):int(rate * 1.8)]
        assert energy(first, 1320) > energy(first, 440) * 100
        assert energy(first, 1320) > energy(first, 880) * 100
        assert energy(second, 880) > energy(second, 440) * 100
        assert energy(second, 880) > energy(second, 1320) * 100

    def test_mlt_includes_speech_clean_producer(self, tmp_path):
        """When denoise is enabled, MLT should include a speech_clean producer."""
        # Create minimal files
        raw = tmp_path / "raw" / "test.mp4"
        raw.parent.mkdir()
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        cleaned = audio_dir / "speech_cleaned_0.50.wav"

        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not found")

        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(raw),
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-ar", "44100", str(cleaned),
        ], check=True, capture_output=True)

        from engine.schema import EditPlan
        from engine.build_mlt import build

        plan_data = {
            "canvas": {"width": 320, "height": 240, "fps": 30},
            "source": "raw/test.mp4",
            "segments": [{"id": "s1", "in": 0, "out": 2}],
            "denoise": {"enabled": True, "strength": 0.5, "audio_file": "audio/speech_cleaned_0.50.wav"},
            "export": {"file": "out.mp4"},
        }
        plan = EditPlan(**plan_data)
        mlt_path, _ = build(plan, tmp_path / "build", base_dir=tmp_path)
        mlt_text = mlt_path.read_text()
        assert 'id="speech_clean"' in mlt_text
        assert 'id="a0"' in mlt_text
        assert '<property name="level">-60</property>' in mlt_text

    def test_mlt_without_denoise_unchanged(self, tmp_path):
        """Without denoise, MLT should not have speech_clean producer."""
        raw = tmp_path / "raw" / "test.mp4"
        raw.parent.mkdir()

        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not found")

        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(raw),
        ], check=True, capture_output=True)

        from engine.schema import EditPlan
        from engine.build_mlt import build

        plan_data = {
            "canvas": {"width": 320, "height": 240, "fps": 30},
            "source": "raw/test.mp4",
            "segments": [{"id": "s1", "in": 0, "out": 2}],
            "export": {"file": "out.mp4"},
        }
        plan = EditPlan(**plan_data)
        mlt_path, _ = build(plan, tmp_path / "build", base_dir=tmp_path)
        mlt_text = mlt_path.read_text()
        assert 'id="speech_clean"' not in mlt_text
        assert 'id="a0"' not in mlt_text


class TestSilenceDetection:
    def test_silent_audio(self, tmp_path):
        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not found")
        silent = tmp_path / "silent.wav"
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "anullsrc=r=44100:cl=mono", "-t", "2", str(silent),
        ], check=True, capture_output=True)
        from engine.denoise import detect_silence
        assert detect_silence(silent) is True

    def test_speech_audio_not_silent(self, tmp_audio):
        from engine.denoise import detect_silence
        assert detect_silence(tmp_audio) is False


class TestPremiereExportDenoise:
    def test_zip_includes_cleaned_audio(self, tmp_path):
        """Premiere ZIP should include cleaned audio when denoise is enabled."""
        import zipfile

        raw = tmp_path / "raw" / "test.mp4"
        raw.parent.mkdir()
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        cleaned = audio_dir / "speech_cleaned_0.50.wav"

        if not shutil.which("ffmpeg"):
            pytest.skip("ffmpeg not found")

        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest", str(raw),
        ], check=True, capture_output=True)
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-ar", "44100", str(cleaned),
        ], check=True, capture_output=True)

        from engine.schema import EditPlan
        from engine.premiere import build_premiere

        plan_data = {
            "canvas": {"width": 320, "height": 240, "fps": 30},
            "source": str(raw),
            "segments": [{"id": "s1", "in": 0, "out": 2}],
            "denoise": {"enabled": True, "strength": 0.5, "audio_file": str(cleaned)},
            "export": {"file": "out.mp4"},
        }
        plan = EditPlan(**plan_data)
        bundle = build_premiere(plan, tmp_path, base_dir=tmp_path)
        with zipfile.ZipFile(bundle) as zf:
            names = zf.namelist()
            assert "speech_cleaned_0.50.wav" in names


class TestRedenoise:
    def test_adjust_replaces_file(self, tmp_audio, tmp_path):
        from engine.denoise import denoise_speech
        r1 = denoise_speech(tmp_audio, strength=0.3, out_dir=tmp_path)
        r2 = denoise_speech(tmp_audio, strength=0.7, out_dir=tmp_path)
        assert r1.name != r2.name
        assert r1.exists()
        assert r2.exists()
