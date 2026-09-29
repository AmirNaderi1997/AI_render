"""Shared fixtures: generate synthetic media once per test session."""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MEDIA = REPO / "samples" / "media"


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


@pytest.fixture(scope="session")
def media_dir() -> Path:
    if not _has("ffmpeg"):
        pytest.skip("ffmpeg not on PATH")
    if not (MEDIA / "raw.mp4").exists():
        sys.path.insert(0, str(REPO))
        from samples.scripts.make_media import make
        make(MEDIA)
    return MEDIA


@pytest.fixture(scope="session")
def has_melt() -> bool:
    return _has("melt")
