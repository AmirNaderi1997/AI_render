"""Planner asset lookup should offer only playable music and SFX paths."""
from __future__ import annotations

import wave
from pathlib import Path

from brain import planner


def _write_wav(path: Path, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * int(8000 * seconds))


def test_find_asset_skips_empty_and_corrupt_files(tmp_path, monkeypatch):
    project = tmp_path / "project"
    music = project / "assets" / "music"
    music.mkdir(parents=True)
    (music / "a-empty.mp3").touch()
    (music / "b-corrupt.wav").write_bytes(b"not audio")
    valid = music / "z-valid.wav"
    _write_wav(valid)
    monkeypatch.setattr(planner, "PROJECT_ROOT", project)

    assert planner._find_asset(tmp_path / "job", "music") == str(valid.resolve())


def test_find_asset_prefers_uploaded_job_music(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project_music = project / "assets" / "music" / "project.wav"
    job_music = tmp_path / "job" / "music" / "uploaded.wav"
    _write_wav(project_music)
    _write_wav(job_music)
    monkeypatch.setattr(planner, "PROJECT_ROOT", project)

    assert planner._find_asset(job_music.parents[1], "music") == str(job_music.resolve())


def test_find_asset_returns_none_when_no_playable_asset_exists(tmp_path, monkeypatch):
    project = tmp_path / "project"
    broken = project / "assets" / "sfx" / "empty.wav"
    broken.parent.mkdir(parents=True)
    broken.touch()
    monkeypatch.setattr(planner, "PROJECT_ROOT", project)

    assert planner._find_asset(tmp_path / "job", "sfx") is None
