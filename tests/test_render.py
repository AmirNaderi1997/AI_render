"""End-to-end render tests: needs ffmpeg + melt on PATH."""
from __future__ import annotations
import json
import shutil
from pathlib import Path

import pytest

from engine.build_mlt import build
from engine.render import render as run_render
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


@pytest.mark.parametrize("plan_name", ["full.json", "minimal.json"])
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
    got = probe_duration(out)
    assert abs(got - expected) < 1.0 / 30 + 0.05, (got, expected)


def test_full_plan_has_audio(tmp_path, media_dir, has_melt):
    if not has_melt:
        pytest.skip("melt not on PATH")
    tmp_path, data = _prep_job(tmp_path, media_dir, "full.json")
    out = _render(tmp_path, data, "out.mp4")
    assert has_audio(out)


def test_build_produces_absolute_paths(tmp_path, media_dir):
    tmp_path, data = _prep_job(tmp_path, media_dir, "full.json")
    plan, errs = validate_plan(data, base_dir=tmp_path, check_media=True)
    assert errs == []
    mlt, ass = build(plan, tmp_path, base_dir=tmp_path)
    text = mlt.read_text()
    assert str((tmp_path / "raw.mp4").resolve()) in text
    assert ass.exists()
