"""End-to-end render tests: needs ffmpeg + melt on PATH."""
from __future__ import annotations
import json
import platform
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from engine.build_mlt import build
from engine.captions import load_style
from engine.render import _melt_env, melt_bin, render as run_render, export_poster, embed_poster
from engine.probe import probe, has_audio, video_stream, probe_duration
from engine.schema import validate_plan


SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "plans"


def _prep_job(tmp_path: Path, media: Path, plan_name: str) -> tuple[Path, dict]:
    """Copy media + plan into tmp_path and rewrite plan paths to bare filenames."""
    for f in media.iterdir():
        shutil.copy(f, tmp_path / f.name)
    data = json.loads((SAMPLES / plan_name).read_text())
    # Sample plans may use paths like "../media/foo.mp4" for CLI use; strip to
    # bare filenames so they resolve inside tmp_path.
    def _strip(p: str) -> str:
        return Path(p).name
    data["source"] = _strip(data["source"])
    for b in data.get("broll", []):
        b["file"] = _strip(b["file"])
    for s in data.get("sfx", []):
        s["file"] = _strip(s["file"])
    if data.get("music"):
        data["music"]["file"] = _strip(data["music"]["file"])
    (tmp_path / "plan.json").write_text(json.dumps(data))
    return tmp_path, data


def _render(tmp_path: Path, data: dict, out_name: str) -> Path:
    plan, errs = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert errs == [], errs
    mlt, _ = build(plan, tmp_path, base_dir=tmp_path)
    out = tmp_path / out_name
    run_render(mlt, out)
    assert out.exists() and out.stat().st_size > 0
    return out


ALL_PLANS = sorted(p.name for p in SAMPLES.glob("*.json"))


def _stream_duration(path: Path, kind: str) -> float:
    for s in probe(path)["streams"]:
        if s["codec_type"] == kind:
            return float(s.get("duration") or probe(path)["format"]["duration"])
    raise AssertionError(f"no {kind} stream in {path}")


def _decoded_video_frames(path: Path) -> int:
    data = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=nb_read_frames", "-of", "json", str(path),
    ], text=True))
    return int(data["streams"][0]["nb_read_frames"])


def _tone_amplitude(path: Path, frequency: float, start: float, duration: float = 0.2) -> float:
    """Measure the target tone in a decoded audio window, ignoring codec/container details."""
    import numpy as np

    decoded = subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", str(start), "-t", str(duration), "-i", str(path),
        "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-",
    ])
    samples = np.frombuffer(decoded, dtype="<f4")
    if not len(samples):
        return 0.0
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    bins = np.fft.rfftfreq(len(samples), d=1 / 48000)
    band = (bins >= frequency - 20) & (bins <= frequency + 20)
    return float(spectrum[band].max() / len(samples)) if np.any(band) else 0.0


def _make_audio_probe_video(path: Path, duration: float = 3.0) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        f"color=c=black:s=320x240:r=30:d={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path),
    ], check=True, capture_output=True)


def test_every_sample_plan_is_covered():
    assert {"minimal.json", "full.json", "cut.json", "pause_removal.json", "zoom.json",
            "captions.json", "broll.json", "music.json", "sfx.json"} <= set(ALL_PLANS)


@pytest.mark.parametrize("plan_name", ALL_PLANS)
def test_render_matches_expected_dims_and_length(tmp_path, media_dir, has_melt, plan_name):
    if not has_melt:
        pytest.skip("melt not on PATH")
    tmp_path, data = _prep_job(tmp_path, media_dir, plan_name)
    out = _render(tmp_path, data, "out.mp4")

    v = video_stream(out)
    assert int(v["width"]) == 1080
    assert int(v["height"]) == 1920

    # fps: eval_avg_frame_rate string like "30/1"
    fps_str = v.get("avg_frame_rate") or v.get("r_frame_rate", "0/1")
    num, den = fps_str.split("/")
    assert abs(int(num) / max(int(den), 1) - 30) < 0.5

    expected = sum(s["out"] - s["in"] for s in data["segments"])
    frame = 1.0 / 30
    got = probe_duration(out)
    assert abs(got - expected) <= frame + 0.05, (got, expected)

    assert has_audio(out)
    video_len = _stream_duration(out, "video")
    audio_len = _stream_duration(out, "audio")
    assert abs(video_len - expected) <= frame + 0.05, (video_len, expected)
    assert abs(audio_len - video_len) <= frame + 0.05, (audio_len, video_len)


def test_full_plan_has_audio(tmp_path, media_dir, has_melt):
    if not has_melt:
        pytest.skip("melt not on PATH")
    tmp_path, data = _prep_job(tmp_path, media_dir, "full.json")
    out = _render(tmp_path, data, "out.mp4")
    assert has_audio(out)


@pytest.mark.parametrize("transition_type", ["crossfade", "directional", "zoom"])
def test_boundary_transition_renders_with_frame_accurate_duration(
        tmp_path, media_dir, has_melt, transition_type):
    if not has_melt:
        pytest.skip("melt not on PATH")
    tmp_path, data = _prep_job(tmp_path, media_dir, "cut.json")
    data["version"] = "0.3"
    data["transitions"] = [{
        "from_segment_id": "s1", "to_segment_id": "s2",
        "type": transition_type, "duration_frames": 6,
        "direction": "left", "intensity": 0.75,
        "source": "manual", "locked": True,
    }]
    out = _render(tmp_path, data, f"{transition_type}.mp4")
    expected_frames = 2 * 30 + 3 * 30 - 6
    got = probe_duration(out)
    assert abs(got - expected_frames / 30) <= 1 / 30 + 0.01, (got, expected_frames)
    assert has_audio(out)


def test_crossfade_visibly_blends_adjacent_shots(tmp_path, has_melt):
    if not has_melt:
        pytest.skip("melt not on PATH")
    source = tmp_path / "two-colors.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=red:s=320x240:r=30:d=1", "-f", "lavfi", "-i",
        "color=c=blue:s=320x240:r=30:d=1", "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(source),
    ], check=True, capture_output=True)
    data = {
        "version": "0.3",
        "canvas": {"width": 320, "height": 240, "fps": 30},
        "source": str(source),
        "segments": [{"id": "red", "in": 0, "out": 1},
                     {"id": "blue", "in": 1, "out": 2}],
        "transitions": [{
            "from_segment_id": "red", "to_segment_id": "blue",
            "type": "crossfade", "duration_frames": 6,
            "source": "manual", "locked": True,
        }],
        "export": {"file": "crossfade.mp4"},
    }
    plan, errors = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert not errors, errors
    mlt, _ = build(plan, tmp_path / "crossfade-build", base_dir=tmp_path)
    output = tmp_path / "crossfade.mp4"
    run_render(mlt, output)
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(output), "-map", "0:v:0",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])

    def center(frame: int) -> tuple[int, int, int]:
        offset = (frame * 320 * 240 + 120 * 320 + 160) * 3
        return tuple(raw[offset:offset + 3])

    before, middle, end = center(24), center(27), center(29)
    assert before[0] > 200 and before[2] < 20
    assert middle[0] > 20 and middle[2] > 20
    assert end[0] < 30 and end[2] > 200
    assert plan.output_frames == 54


@pytest.mark.parametrize("preview", [False, True])
def test_fractional_source_endpoints_do_not_lose_a_planned_frame(
        tmp_path, media_dir, has_melt, preview):
    """Regression for Job 57e4a9abd409's former 293 -> 292 frame loss."""
    if not has_melt:
        pytest.skip("melt not on PATH")
    shutil.copy(media_dir / "raw.mp4", tmp_path / "raw.mp4")
    data = {
        "version": "0.3",
        "style": "rafiei_reel",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": "raw.mp4",
        "segments": [
            {"id": "s1", "in": 0.06, "out": 3.48},
            {"id": "s2", "in": 3.82, "out": 5.86},
            {"id": "s3", "in": 6.24, "out": 7.86},
            {"id": "s4", "in": 8.08, "out": 9.20},
            {"id": "s5", "in": 9.42, "out": 11.52},
        ],
        "transitions": [
            {"from_segment_id": "s1", "to_segment_id": "s2", "type": "hard_cut", "duration_frames": 0},
            {"from_segment_id": "s2", "to_segment_id": "s3", "type": "zoom", "duration_frames": 5},
            {"from_segment_id": "s3", "to_segment_id": "s4", "type": "crossfade", "duration_frames": 4},
            {"from_segment_id": "s4", "to_segment_id": "s5", "type": "directional", "duration_frames": 8},
        ],
        "export": {"file": "out.mp4", "crf": 20},
    }
    plan, errors = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert errors == []
    assert plan.output_frames == 293
    mlt, _ = build(plan, tmp_path, base_dir=tmp_path)
    root = ET.parse(mlt).getroot()
    assert root.find("tractor[@id='main']").get("out") == "292"
    assert root.find("playlist[@id='v1a']/entry").get("in") == "2"
    assert root.find("playlist[@id='v1a']/entry").get("out") == "104"
    out = tmp_path / ("preview.mp4" if preview else "final.mp4")
    run_render(mlt, out, preview=preview)
    assert _decoded_video_frames(out) == plan.output_frames
    assert abs(_stream_duration(out, "audio") - plan.output_duration) <= 1 / 30 + 0.01


def test_render_duration_with_long_music(tmp_path, media_dir, has_melt):
    """Music file longer than the edit must not extend rendered output."""
    if not has_melt:
        pytest.skip("melt not on PATH")
    import subprocess
    tmp_path, data = _prep_job(tmp_path, media_dir, "full.json")
    # Create a music file 3x longer than the edit (output_duration ~ 7.5 s → 30 s)
    long_music = tmp_path / "long_music.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "sine=frequency=220:sample_rate=48000:duration=30",
         "-ac", "2", str(long_music)],
        check=True, capture_output=True,
    )
    data["music"]["file"] = "long_music.wav"
    out = _render(tmp_path, data, "out_long_music.mp4")
    expected = sum(s["out"] - s["in"] for s in data["segments"])
    got = probe_duration(out)
    assert abs(got - expected) < 1.0 / 30 + 0.05, (
        f"rendered {got:.3f}s but plan duration is {expected:.3f}s"
    )


def test_short_music_loops_through_video_and_duck_ranges_recover(tmp_path, has_melt):
    if not has_melt:
        pytest.skip("melt not on PATH")

    source = tmp_path / "source.mp4"
    music = tmp_path / "short_music.wav"
    _make_audio_probe_video(source)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=880:sample_rate=48000:duration=0.5", "-ac", "2", str(music),
    ], check=True, capture_output=True)
    data = {
        "canvas": {"width": 320, "height": 240, "fps": 30},
        "source": "source.mp4",
        "segments": [{"id": "s1", "in": 0, "out": 3}],
        "music": {"file": "short_music.wav", "volume_db": -12,
                  "duck": [{"start": 0.7, "end": 1.5, "volume_db": -36}]},
        "export": {"file": "out.mp4"},
    }

    out = _render(tmp_path, data, "music_loop.mp4")
    before = _tone_amplitude(out, 880, 0.2)
    during = _tone_amplitude(out, 880, 1.0)
    after = _tone_amplitude(out, 880, 2.0)

    assert before > 0.001
    assert during > 0
    assert before > during * 3, (before, during)
    assert after > during * 3, (during, after)


def test_music_stays_ducked_across_loops_and_cut_without_broll_audio(tmp_path, has_melt):
    if not has_melt:
        pytest.skip("melt not on PATH")

    source = tmp_path / "source.mp4"
    broll = tmp_path / "broll.mp4"
    music = tmp_path / "music.wav"
    _make_audio_probe_video(source, duration=4)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=blue:s=320x240:r=30:d=1", "-f", "lavfi", "-i",
        "sine=frequency=1320:sample_rate=48000:duration=1",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(broll),
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=880:sample_rate=48000:duration=0.5", str(music),
    ], check=True, capture_output=True)
    data = {
        "canvas": {"width": 320, "height": 240, "fps": 30},
        "source": "source.mp4",
        "segments": [{"id": "s1", "in": 0, "out": 1},
                     {"id": "s2", "in": 2, "out": 3}],
        "broll": [{"at": 0.5, "duration": 1, "file": "broll.mp4"}],
        "music": {"file": "music.wav", "volume_db": -12,
                  "duck": [{"start": 0, "end": 2, "volume_db": -36}]},
        "export": {"file": "out.mp4"},
    }
    ducked = _render(tmp_path, data, "ducked.mp4")
    data["music"]["duck"] = []
    unducked = _render(tmp_path, data, "unducked.mp4")

    # The music repeats every half-second; its gain must remain low through
    # both loop edges and the source edit at output time 1.0 seconds.
    for at in (0.35, 0.48, 0.55, 0.95, 1.05, 1.48, 1.55):
        quiet = _tone_amplitude(ducked, 880, at, 0.06)
        normal = _tone_amplitude(unducked, 880, at, 0.06)
        assert quiet > 0 and normal > quiet * 5, (at, quiet, normal)
    assert _tone_amplitude(ducked, 440, 0.8) > 0.001
    assert _tone_amplitude(ducked, 1320, 0.8) < 0.0005


def test_approved_denoise_replaces_raw_audio_in_render(tmp_path, has_melt):
    if not has_melt:
        pytest.skip("melt not on PATH")
    source = tmp_path / "source.mp4"
    cleaned = tmp_path / "cleaned.wav"
    _make_audio_probe_video(source)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=1320:sample_rate=48000:duration=3", "-af", "volume=0.5",
        "-ac", "1", str(cleaned),
    ], check=True, capture_output=True)
    data = {
        "canvas": {"width": 320, "height": 240, "fps": 30},
        "source": "source.mp4",
        "segments": [{"id": "s1", "in": 0, "out": 3}],
        "denoise": {"enabled": True, "strength": 0.5, "audio_file": "cleaned.wav"},
        "export": {"file": "out.mp4"},
    }

    out = _render(tmp_path, data, "denoised.mp4")
    original_tone = _tone_amplitude(out, 440, 0.5)
    cleaned_tone = _tone_amplitude(out, 1320, 0.5)

    assert cleaned_tone > 0.001
    assert cleaned_tone > original_tone * 20, (cleaned_tone, original_tone)


@pytest.mark.parametrize("crossfade", [False, True])
def test_cleaned_speech_follows_source_segment_cuts(tmp_path, has_melt, crossfade):
    if not has_melt:
        pytest.skip("melt not on PATH")
    source = tmp_path / "source.mp4"
    cleaned = tmp_path / "cleaned.wav"
    _make_audio_probe_video(source, duration=4)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=1320:sample_rate=48000:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=1760:sample_rate=48000:duration=2",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map", "[a]", str(cleaned),
    ], check=True, capture_output=True)
    data = {
        "canvas": {"width": 320, "height": 240, "fps": 30},
        "source": "source.mp4",
        "segments": [{"id": "s1", "in": 0, "out": 1},
                     {"id": "s2", "in": 2, "out": 3}],
        "denoise": {"enabled": True, "audio_file": "cleaned.wav"},
        "export": {"file": "out.mp4"},
    }
    if crossfade:
        data["transitions"] = [{
            "from_segment_id": "s1", "to_segment_id": "s2",
            "type": "crossfade", "duration_frames": 4,
        }]
    out = _render(tmp_path, data, "cleaned_cuts.mp4")
    assert _tone_amplitude(out, 1320, 0.5) > 0.001
    assert _tone_amplitude(out, 1760, 1.5) > 0.001
    assert _tone_amplitude(out, 1320, 1.5) < 0.0002


def test_build_produces_absolute_paths(tmp_path, media_dir):
    tmp_path, data = _prep_job(tmp_path, media_dir, "full.json")
    plan, errs = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert errs == []
    mlt, ass = build(plan, tmp_path, base_dir=tmp_path)
    text = mlt.read_text()
    assert str((tmp_path / "raw.mp4").resolve()) in text
    assert ass.exists()


def test_poster_jpeg_exported_with_text(tmp_path, media_dir, has_melt):
    if not has_melt:
        pytest.skip("melt not on PATH")
    tmp_path, data = _prep_job(tmp_path, media_dir, "captions.json")
    data["poster"] = {"text": "Poster hook", "frame_time": 0.5}
    plan, errs = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert not errs, errs
    out = export_poster(plan, tmp_path, tmp_path / "v1_poster.jpg", base_dir=tmp_path)
    assert out.exists() and out.stat().st_size > 5000
    v = video_stream(out)
    assert (int(v["width"]), int(v["height"])) == (1080, 1920)
    assert "Poster hook" in (tmp_path / "poster_build" / "captions.cover.srt").read_text()


def test_mp4_contains_poster_as_opening_frame_and_cover(tmp_path):
    from PIL import Image

    video, poster = tmp_path / "video.mp4", tmp_path / "poster.jpg"
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "color=c=red:s=160x90:r=10:d=1", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(video),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "color=c=blue:s=160x90", "-frames:v", "1", str(poster),
    ], check=True)
    embed_poster(video, poster)
    streams = probe(video)["streams"]
    main = next(s for s in streams if s["codec_type"] == "video" and not s["disposition"]["attached_pic"])
    assert int(main["nb_frames"]) == 10
    assert any(s["codec_type"] == "audio" for s in streams)
    assert any(s["codec_type"] == "video" and s["disposition"]["attached_pic"] for s in streams)
    first = tmp_path / "first.png"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video),
                    "-frames:v", "1", str(first)], check=True)
    red, green, blue = Image.open(first).convert("RGB").getpixel((80, 45))
    assert blue > 180 and red < 80 and green < 80


def test_macos_melt_loads_bundled_ray_families(tmp_path, media_dir, has_melt):
    if platform.system() != "Darwin" or not has_melt:
        pytest.skip("requires the macOS melt/Qt renderer")
    tmp_path, data = _prep_job(tmp_path, media_dir, "captions.json")
    data["canvas"]["caption_font"] = "RAY-EXTRABLACK"
    data["cover"] = {"text": "اگر قرار باشه انتخاب کنید", "start": 0.0, "end": 0.5}
    plan, errs = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert not errs, errs
    mlt, _ = build(plan, tmp_path, base_dir=tmp_path)
    project = mlt.read_text()
    assert '<property name="family">Ray</property>' in project
    assert '<property name="style">ExtraBlack</property>' in project
    assert '<property name="style">ExtraBold</property>' in project

    out = tmp_path / "font_probe.jpg"
    env = _melt_env(load_style("rafiei_reel"))
    env["MLT_LOG_LEVEL"] = "debug"
    proc = subprocess.run(
        [melt_bin(), "-loglevel", "debug", str(mlt), "in=0", "out=0", "-consumer",
         f"avformat:{out}", "vcodec=mjpeg", "qscale=2", "an=1"],
        env=env,
        capture_output=True, text=True,
    )
    log = proc.stdout + proc.stderr
    assert proc.returncode == 0, log
    assert out.exists() and out.stat().st_size > 0
    assert 'missing font family "Ray ExtraBlack"' not in log
    assert 'missing font family "Ray ExtraBold"' not in log
    assert "[filter_qtext] family Ray style ExtraBlack" in log
    assert "[filter_qtext] family Ray style ExtraBold" in log


def test_preview_and_final_honor_style_aspect_and_export_crf(tmp_path, monkeypatch):
    import engine.render as render_module

    mlt = tmp_path / "project.mlt"
    mlt.write_text(
        '<mlt><profile width="320" height="240" frame_rate_num="30" '
        'frame_rate_den="1"/></mlt>'
    )
    commands = []
    monkeypatch.setattr(render_module, "melt_bin", lambda: "melt")
    monkeypatch.setattr(render_module, "_melt_env", lambda *_args: {})
    monkeypatch.setattr(
        render_module, "_run_and_stream",
        lambda command, _env, _progress: commands.append(command) or 0,
    )

    style = {"render": {"preview_scale": 0.75, "preview_crf": 21,
                         "crf": 24, "preset": "slow", "audio_bitrate": "160k"}}
    render_module.render(mlt, tmp_path / "preview.mp4", preview=True,
                         style_override=style, crf_override=17)
    render_module.render(mlt, tmp_path / "final.mp4", style_override=style,
                         crf_override=17)

    preview, final = commands
    assert "width=240" in preview and "height=180" in preview
    assert "display_aspect_num=4" in preview and "display_aspect_den=3" in preview
    assert "crf=21" in preview
    assert "display_aspect_num=4" in final and "display_aspect_den=3" in final
    assert "crf=17" in final
    assert "preset=slow" in final


def test_build_mlt_profile_uses_canvas_aspect(tmp_path):
    source = tmp_path / "source.mp4"
    _make_audio_probe_video(source, duration=1.0)
    data = {
        "canvas": {"width": 320, "height": 240, "fps": 30},
        "source": "source.mp4",
        "segments": [{"id": "s1", "in": 0, "out": 1}],
        "export": {"file": "out.mp4"},
    }
    plan, errors = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert not errors, errors
    mlt, _ = build(plan, tmp_path, base_dir=tmp_path)
    profile = ET.parse(mlt).getroot().find("profile")
    assert profile is not None
    assert profile.get("display_aspect_num") == "4"
    assert profile.get("display_aspect_den") == "3"
