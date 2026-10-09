"""Regression checks for generated-content audio and playable rendered mixes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from brain.content_creator import storyboard_to_plan, update_storyboard, _run_generation
from brain.storyboard import Scene, Storyboard
from engine.content_types import ContentType


@pytest.mark.parametrize("context", ["worker", "running_loop"])
def test_tts_works_in_generation_thread_and_running_loop(tmp_path, monkeypatch, context):
    from brain import tts
    async def generate(text, output, voice, rate):
        Path(output).write_bytes(b"audio")
    monkeypatch.setattr(tts, "_generate_async", generate)
    monkeypatch.setattr(tts, "_get_audio_duration", lambda _: 1.0)
    if context == "worker":
        with ThreadPoolExecutor() as pool:
            result = pool.submit(tts.generate_narration, "test", tmp_path).result()
    else:
        async def call():
            return tts.generate_narration("test", tmp_path)
        result = asyncio.run(call())
    assert Path(result.file_path).read_bytes() == b"audio"


def test_invalid_tts_audio_is_rejected_and_removed(tmp_path, monkeypatch):
    from brain import tts
    async def generate(text, output, voice, rate):
        Path(output).write_bytes(b"corrupt")
    monkeypatch.setattr(tts, "_generate_async", generate)
    monkeypatch.setattr(tts, "_get_audio_duration", lambda _: 0)
    with pytest.raises(RuntimeError, match="playable duration"):
        tts.generate_narration("test", tmp_path)
    assert not list(tmp_path.glob("*.mp3"))


def test_tts_retries_connection_timeout_without_leaving_partial_audio(tmp_path, monkeypatch):
    from brain import tts
    attempts = []
    async def generate(text, output, voice, rate):
        attempts.append(output)
        if len(attempts) == 1:
            Path(output).write_bytes(b"partial")
            raise TimeoutError("temporary connection timeout")
        Path(output).write_bytes(b"complete-audio")
    monkeypatch.setattr(tts, "_generate_async", generate)
    monkeypatch.setattr(tts, "_get_audio_duration", lambda _: 1.25)
    monkeypatch.setattr(tts.time, "sleep", lambda _: None)
    result = tts.generate_narration("سلام", tmp_path)
    assert len(attempts) == 2
    assert Path(result.file_path).read_bytes() == b"complete-audio"
    assert len(list(tmp_path.glob("narration_*.mp3"))) == 1


def test_edge_tts_is_primary_and_never_calls_elevenlabs(tmp_path, monkeypatch):
    from brain import tts
    async def generate(text, output, voice, rate):
        Path(output).write_bytes(b"edge-audio")
    monkeypatch.setenv("TTS_PROVIDER", "edge-tts")
    monkeypatch.setenv("TTS_VOICE", "en-US-GuyNeural")
    monkeypatch.setattr(tts, "_generate_async", generate)
    monkeypatch.setattr(tts, "_get_audio_duration", lambda _: 1.0)
    monkeypatch.setattr(tts, "_generate_elevenlabs", lambda *_: (_ for _ in ()).throw(AssertionError("must not call ElevenLabs")))
    result = tts.generate_narration("Hello", tmp_path)
    assert Path(result.file_path).read_bytes() == b"edge-audio"


def test_blocked_elevenlabs_falls_back_to_edge_tts(tmp_path, monkeypatch):
    from brain import tts
    async def generate(text, output, voice, rate):
        Path(output).write_bytes(b"edge-audio")
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setattr(tts, "_generate_elevenlabs", lambda *_: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(tts, "_generate_async", generate)
    monkeypatch.setattr(tts, "_get_audio_duration", lambda _: 1.0)
    result = tts.generate_narration("Hello", tmp_path)
    assert Path(result.file_path).read_bytes() == b"edge-audio"


def test_disabled_tts_skips_narration(tmp_path, monkeypatch):
    from brain import tts
    monkeypatch.setenv("TTS_PROVIDER", "disabled")
    result = tts.generate_narration("Hello", tmp_path)
    assert result.file_path == ""
    assert result.duration_s == 0.0
    assert not list(tmp_path.iterdir())


def test_captions_follow_actual_generated_scene_durations(tmp_path):
    sb = Storyboard(prompt="test", content_type="reel", language="en", style="rafiei_reel",
                    scenes=[Scene(index=0, description="a", duration_s=5, text_overlay="One"),
                            Scene(index=1, description="b", duration_s=5, text_overlay="Two")])
    data = storyboard_to_plan(sb, [{"scene_index": 0, "duration_s": 3, "source": "local_fixture"},
                                  {"scene_index": 1, "duration_s": 4, "source": "local_fixture"}], ContentType.REEL, "source.mp4")
    assert [(c["start"], c["end"]) for c in data["captions"]] == [(0, 3), (3, 7)]


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 91])
def test_invalid_storyboard_edit_does_not_overwrite_saved_data(tmp_path, duration):
    path = tmp_path / "storyboard.json"
    before = json.dumps({"content_type": "reel", "scenes": []})
    path.write_text(before)
    with pytest.raises(ValueError):
        update_storyboard(SimpleNamespace(dir=tmp_path), [dict(index=0, description="test", duration_s=duration)])
    assert path.read_text() == before


def test_requested_voiceover_failure_cannot_report_ready(tmp_path, monkeypatch):
    from brain import content_creator, tts
    monkeypatch.setenv("CONTENT_VOICE_PROVIDER", "edge")
    from brain.media_provider import MediaResult
    job = SimpleNamespace(id="audio-test", dir=tmp_path)
    sb = Storyboard(prompt="test", content_type="reel", language="en", style="rafiei_reel",
                    scenes=[Scene(index=0, description="test", duration_s=1, narration_text="Hello")])
    (tmp_path / "storyboard.json").write_text(json.dumps(sb.to_dict()))
    (tmp_path / "generation_status.json").write_text('{"state":"generating"}')
    monkeypatch.setattr("app.jobs.get", lambda _: job)
    monkeypatch.setattr(content_creator, "get_provider", lambda _: SimpleNamespace(
        generate_video=lambda *args: MediaResult(file_path=str(tmp_path / "video.mp4"), source="local_fixture", duration_s=1)))
    def fail(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(tts, "generate_narration", fail)
    _run_generation(job.id, "test")
    status = json.loads((tmp_path / "generation_status.json").read_text())
    assert status["state"] == "failed"
    assert "Voiceover failed for scene 1" in status["error"]
    assert not (tmp_path / "plan.json").exists()


def test_corrupt_library_track_does_not_hide_next_playable_track(tmp_path, monkeypatch):
    from brain import content_creator
    from brain.media_provider import MediaResult
    job = SimpleNamespace(id="library-test", dir=tmp_path, raw_name=None)
    sb = Storyboard(prompt="test", content_type="reel", language="en", style="rafiei_reel",
                    scenes=[Scene(index=0, description="test", duration_s=1)])
    (tmp_path / "storyboard.json").write_text(json.dumps(sb.to_dict()))
    (tmp_path / "generation_status.json").write_text('{"state":"generating"}')
    bad, good = tmp_path / "bad.mp3", tmp_path / "good.wav"
    bad.write_bytes(b"bad")
    good.write_bytes(b"audio")
    monkeypatch.setattr("app.jobs.get", lambda _: job)
    monkeypatch.setattr("app.jobs._write_status", lambda _: None)
    monkeypatch.setattr(content_creator, "get_provider", lambda _: SimpleNamespace(
        generate_video=lambda *args: MediaResult(file_path=str(tmp_path / "video.mp4"), source="local_fixture", duration_s=1)))
    monkeypatch.setattr("brain.asset_match.music_match", lambda **_: [SimpleNamespace(path=str(bad)), SimpleNamespace(path=str(good))])
    def probe(path):
        if path == bad:
            raise ValueError("undecodable track")
        return {"streams": [{"codec_type": "audio"}]}
    monkeypatch.setattr("engine.probe.probe", probe)
    _run_generation(job.id, "test", raise_errors=True)
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert plan["music"]["file"] == str(good)
    assert not plan["sfx"]


def test_storyboard_cannot_change_while_generation_is_running(tmp_path):
    (tmp_path / "storyboard.json").write_text('{"content_type":"reel","scenes":[]}')
    (tmp_path / "generation_status.json").write_text('{"state":"generating"}')
    with pytest.raises(ValueError, match="Wait for generation"):
        update_storyboard(SimpleNamespace(dir=tmp_path), [dict(index=0, description="test", duration_s=1)])


def test_upload_rejects_corrupt_audio_and_previews_exact_selected_file(tmp_path, monkeypatch):
    from app.routers import music
    monkeypatch.setattr("app.jobs.get", lambda _: SimpleNamespace(dir=tmp_path))
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "first.wav").write_bytes(b"first")
    (tmp_path / "music" / "second.wav").write_bytes(b"second")
    app = FastAPI()
    app.include_router(music.router)
    with TestClient(app) as client:
        result = client.post("/jobs/test/music/upload", files={"file": ("first.wav", b"bad audio", "audio/wav")})
        assert result.status_code == 422
        assert (tmp_path / "music" / "first.wav").read_bytes() == b"first"
        assert client.get("/jobs/test/music/preview?filename=second.wav").content == b"second"
        assert client.get("/jobs/test/music/preview?filename=../second.wav").status_code == 422


def test_generated_source_preview_uses_job_local_plan_source(tmp_path, monkeypatch):
    from app.routers.jobs import get_raw
    source = tmp_path / "generated" / "clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    (tmp_path / "plan.json").write_text(json.dumps({"source_type": "generated", "source": str(source)}))
    monkeypatch.setattr("app.jobs.get", lambda _: SimpleNamespace(dir=tmp_path, raw_name=None))
    assert Path(get_raw("test").path) == source


@pytest.mark.parametrize("preview", [True, False])
def test_generated_voice_and_looped_music_mix_in_preview_and_final(tmp_path, has_melt, preview):
    if not has_melt:
        pytest.skip("melt is required")
    from engine.build_mlt import build
    from engine.render import render
    from engine.schema import validate_plan
    from engine.probe import probe_duration
    import numpy as np
    source = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=320x240:r=30:d=3", "-c:v", "libx264", str(source)], check=True)
    for name, frequency, duration in [("voice", 440, 3), ("music", 880, 0.5)]:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"sine=frequency={frequency}:duration={duration}:sample_rate=48000",
                        str(tmp_path / f"{name}.wav")], check=True)
    sb = Storyboard(prompt="test", content_type="reel", language="en", style="rafiei_reel",
                    scenes=[Scene(index=0, description="test", duration_s=3)])
    data = storyboard_to_plan(sb, [{"scene_index": 0, "duration_s": 3, "source": "local_fixture"}], ContentType.REEL,
                              str(source), str(tmp_path / "voice.wav"), str(tmp_path / "music.wav"))
    data["canvas"] = {"width": 320, "height": 240, "fps": 30}
    def amplitude(path, frequency):
        pcm = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", "1.8", "-t", "0.2",
                                      "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"])
        samples = np.frombuffer(pcm, dtype="<f4")
        bins = np.fft.rfftfreq(len(samples), 1 / 48000)
        spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)))) / len(samples)
        return spectrum[(bins > frequency - 20) & (bins < frequency + 20)].max()
    levels = []
    for music in [data["music"], None]:
        data["music"] = music
        plan, errors = validate_plan(data, check_media=True)
        assert not errors
        mlt, _ = build(plan, tmp_path)
        output = tmp_path / f"{'mix' if music else 'voice'}_{preview}.mp4"
        render(mlt, output, preview=preview, apply_loudnorm=True)
        assert abs(probe_duration(output) - 3) < 0.03
        levels.append((amplitude(output, 440), amplitude(output, 880)))
    assert levels[0][0] > levels[0][1] * 8  # -24 dB music stays below voice
    assert levels[0][1] > 0.0002  # short background still plays near the end
    assert levels[1][1] < levels[0][1] / 10  # remove music really removes it
    assert levels[1][0] == pytest.approx(levels[0][0], rel=0.15)  # voice remains
