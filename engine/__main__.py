"""CLI: python -m engine {validate|build|render} plan.json [--preview]"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from .schema import validate_plan
from .build_mlt import build
from .render import render as run_render


def _load(plan_file: str) -> tuple[dict, Path]:
    p = Path(plan_file).resolve()
    return json.loads(p.read_text()), p.parent


def _validated(plan_file: str, check_media: bool = True):
    data, base = _load(plan_file)
    plan, errs = validate_plan(data, base_dir=base, check_media=check_media)
    if errs:
        print("Plan invalid:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    return plan, base


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="engine")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="Validate a plan.json")
    v.add_argument("plan")

    b = sub.add_parser("build", help="Build project.mlt + captions.ass next to plan.json")
    b.add_argument("plan")
    b.add_argument("--out", default=None, help="output dir (default: alongside plan)")

    r = sub.add_parser("render", help="Build + render to plan.export.file")
    r.add_argument("plan")
    r.add_argument("--preview", action="store_true", help="fast preview (540x960, veryfast)")
    r.add_argument("--out", default=None)
    r.add_argument("--loudnorm", action=argparse.BooleanOptionalAction, default=True,
                   help="normalize audio to the preset LUFS target (default: on)")

    args = p.parse_args(argv)

    if args.cmd == "validate":
        _validated(args.plan)
        print("OK")
        return 0

    plan, base = _validated(args.plan)
    out_dir = Path(args.out).resolve() if args.out else base
    mlt, ass = build(plan, out_dir, base_dir=base)
    print(f"wrote {mlt}")
    print(f"wrote {ass}")

    if args.cmd == "render":
        export_path = Path(plan.export.file)
        if not export_path.is_absolute():
            export_path = base / export_path
        if args.preview:
            export_path = export_path.with_name(export_path.stem + "_preview.mp4")

        def report(pct: int) -> None:
            print(f"\rrender {pct:3d}%", end="", flush=True)

        run_render(
            mlt, export_path,
            preview=args.preview,
            on_progress=report,
            apply_loudnorm=args.loudnorm,
        )
        print(f"\ndone: {export_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
