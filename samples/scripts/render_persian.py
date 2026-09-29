"""Render samples/plans/persian.json with the Vazirmatn font.

The engine's caption style is chosen by preset (rafiei_reel). This tiny script
loads the plan, swaps the `emphasis` style's font to Vazirmatn, runs build +
render, and grabs a mid-clip PNG frame so the shaping can be inspected.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine import captions as C
from engine.build_mlt import build
from engine.render import render
from engine.schema import EditPlan

REPO = Path(__file__).resolve().parents[2]
PLAN_P = REPO / "samples" / "plans" / "persian.json"


def main() -> Path:
    data = json.loads(PLAN_P.read_text())
    plan = EditPlan(**data)

    orig_load = C.load_style

    def patched(name):
        s = orig_load(name)
        s["captions"]["styles"]["emphasis"] = {
            **s["captions"]["styles"].get("emphasis", {}),
            "font": "Vazirmatn",
        }
        return s

    C.load_style = patched
    try:
        out_dir = PLAN_P.parent
        mlt, _ = build(plan, out_dir, base_dir=out_dir)
        mp4 = out_dir / "out_persian.mp4"
        render(mlt, mp4, preview=False)
    finally:
        C.load_style = orig_load

    # Grab a frame from the middle of the caption (t=1.5s).
    png = out_dir / "persian_frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", "1.5", "-i", str(mp4), "-frames:v", "1", str(png)],
        check=True,
    )
    print(f"video: {mp4}")
    print(f"frame: {png}")
    return png


if __name__ == "__main__":
    main()
