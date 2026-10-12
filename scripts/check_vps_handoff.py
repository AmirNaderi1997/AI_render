"""Fail early when the required project-to-VPS handoff files are absent."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
REQUIRED = (
    Path("SKILLS.md"),
    Path("Prompts/README.md"),
    Path("RoadMap.md"),
    Path("GuideLine.md"),
)


def main() -> int:
    missing = [str(path) for path in REQUIRED if not (ROOT / path).is_file() or not (ROOT / path).read_text(encoding="utf-8").strip()]
    if missing:
        print("VPS handoff preflight failed: missing or empty files: " + ", ".join(missing))
        return 1
    print("VPS handoff files present. Review release evidence before deployment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
