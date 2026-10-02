#!/usr/bin/env python3
"""Generate showcase reel with 12 distinct effects, 2s each.

Creates:
- docs/effects_showcase.mp4 (all effects in sequence)
- assets/effect_previews/<effect_id>.mp4 (individual 2s clips)

Requires: ffmpeg, melt, and a source video at raw/MYVIDEO.mp4.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.schema import PROJECT_ROOT, validate_plan
from engine.build_mlt import build
from engine.render import render
from engine.effects import EFFECT_FAMILIES


SHOWCASE_FAMILIES = [
    "punch", "slow_push", "slow_pull", "lift", "dim", "flash",
    "close_hold", "drift", "tilt", "breathe", "punch_bright", "flash_end",
]

SOURCE = PROJECT_ROOT / "raw" / "MYVIDEO.mp4"


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def generate_showcase():
    if not SOURCE.exists():
        print(f"Source video not found: {SOURCE}")
        sys.exit(1)

    src_dur = _probe_duration(SOURCE)
    families = [f for f in SHOWCASE_FAMILIES if f in EFFECT_FAMILIES][:12]
    seg_dur = 2.0
    start_offset = max(0, src_dur / 2 - len(families))

    preview_dir = PROJECT_ROOT / "assets" / "effect_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = PROJECT_ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    segments = []
    effects = []
    for i, fam in enumerate(families):
        seg_in = start_offset + i * seg_dur
        seg_out = seg_in + seg_dur
        if seg_out > src_dur:
            seg_out = src_dur
            seg_in = max(0, seg_out - seg_dur)
        sid = f"s{i+1}"
        eid = EFFECT_FAMILIES[fam]["ids"][0]
        segments.append({"id": sid, "in": round(seg_in, 2), "out": round(seg_out, 2)})
        effects.append({"segment_id": sid, "type": eid})

    plan_data = {
        "version": "0.2",
        "style": "rafiei_reel",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": str(SOURCE),
        "segments": segments,
        "visual_effects": effects,
        "captions": [],
        "broll": [],
        "music": None,
        "sfx": [],
        "export": {"file": str(docs_dir / "effects_showcase.mp4"), "crf": 20},
    }

    plan, errs = validate_plan(plan_data, check_media=True)
    if errs:
        print(f"Plan validation errors: {errs}")
        sys.exit(1)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # Render full showcase
        print(f"Building showcase: {len(families)} effects x {seg_dur}s")
        mlt_path, _ = build(plan, tmp)
        out = render(mlt_path, docs_dir / "effects_showcase.mp4", preview=False)
        print(f"Showcase: {out}")

        # Render individual preview clips
        for i, fam in enumerate(families):
            eid = EFFECT_FAMILIES[fam]["ids"][0]
            seg = segments[i]
            one_plan = {
                **plan_data,
                "segments": [{"id": "s1", "in": seg["in"], "out": seg["out"]}],
                "visual_effects": [{"segment_id": "s1", "type": eid}],
                "export": {"file": str(preview_dir / f"{eid}.mp4"), "crf": 20},
            }
            p, e = validate_plan(one_plan, check_media=True)
            if e:
                print(f"  skip {eid}: {e}")
                continue
            mlt_p, _ = build(p, tmp)
            clip = render(mlt_p, preview_dir / f"{eid}.mp4", preview=True)
            print(f"  Preview: {clip}")

    print("Done.")


if __name__ == "__main__":
    generate_showcase()
