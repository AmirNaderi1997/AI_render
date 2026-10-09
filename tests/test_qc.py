"""Tests for QC pipeline: frozen frame, caption-face overlap, loudness, patch validity, max rounds."""
from __future__ import annotations

import json
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from engine.schema import EditPlan, Canvas, Segment, Caption, Music, DuckRange, Export, Zoom
from brain.qc_review import (
    QCIssue, deterministic_checks, _ssim_gray, _caption_overlaps_face, _detect_faces, _load_image,
)
from brain.qc_patch import patch_plan
from brain.qc_pipeline import MAX_ROUNDS


def test_vision_failure_is_not_reported_as_a_clean_review(monkeypatch):
    from brain import qc_review

    monkeypatch.setattr("brain.llm.chat_vision",
                        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("provider timed out")))
    plan = EditPlan(**_make_plan())
    with pytest.raises(RuntimeError, match="provider timed out"):
        qc_review.vision_review(plan, [{"path": "frame.jpg", "time": 1.0, "label": "s1"}])


def _make_plan(**overrides) -> dict:
    base = {
        "version": "0.1",
        "style": "rafiei_reel",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": "raw/test.mp4",
        "segments": [
            {"id": "s1", "in": 0.0, "out": 3.0, "zoom": {"from": 1.0, "to": 1.0}},
            {"id": "s2", "in": 3.0, "out": 6.0, "zoom": {"from": 1.0, "to": 1.0}},
        ],
        "captions": [
            {"start": 0.5, "end": 2.0, "text": "Hello", "style": "normal"},
        ],
        "export": {"file": "out.mp4", "crf": 20},
    }
    base.update(overrides)
    return base


def _make_white_image(tmp: Path, name: str = "frame.jpg") -> str:
    from PIL import Image
    img = Image.fromarray(np.ones((1920, 1080, 3), dtype=np.uint8) * 200)
    p = tmp / name
    img.save(str(p))
    return str(p)


def _make_black_image(tmp: Path, name: str = "black.jpg") -> str:
    from PIL import Image
    img = Image.fromarray(np.zeros((1920, 1080, 3), dtype=np.uint8))
    p = tmp / name
    img.save(str(p))
    return str(p)


class TestFrozenFrameDetection:
    def test_identical_frames_detected(self, tmp_path):
        plan_data = _make_plan()
        plan = EditPlan(**plan_data)
        p1 = _make_white_image(tmp_path, "f1.jpg")
        p2 = _make_white_image(tmp_path, "f2.jpg")
        frames = [
            {"time": 1.0, "path": p1, "label": "seg_s1_mid"},
            {"time": 2.0, "path": p2, "label": "seg_s2_mid"},
        ]
        issues = deterministic_checks(plan, frames, [])
        frozen = [i for i in issues if i.type == "frozen_frame"]
        assert len(frozen) >= 1

    def test_different_frames_not_flagged(self, tmp_path):
        plan_data = _make_plan()
        plan = EditPlan(**plan_data)
        p1 = _make_white_image(tmp_path, "f1.jpg")
        p2 = _make_black_image(tmp_path, "f2.jpg")
        frames = [
            {"time": 1.0, "path": p1, "label": "seg_s1_mid"},
            {"time": 4.0, "path": p2, "label": "seg_s2_mid"},
        ]
        issues = deterministic_checks(plan, frames, [])
        frozen = [i for i in issues if i.type == "frozen_frame"]
        assert len(frozen) == 0


class TestBlackFrameDetection:
    def test_black_frame_detected(self, tmp_path):
        plan_data = _make_plan()
        plan = EditPlan(**plan_data)
        p = _make_black_image(tmp_path)
        frames = [{"time": 1.0, "path": p, "label": "seg_s1_mid"}]
        issues = deterministic_checks(plan, frames, [])
        black = [i for i in issues if i.type == "black_frame"]
        assert len(black) == 1
        assert black[0].severity == "error"


class TestCaptionFaceOverlap:
    def test_missing_opencv_face_api_is_optional(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cv2", SimpleNamespace(imread=lambda _: None))
        assert _detect_faces("unused.jpg") == []

    def test_face_in_caption_zone(self):
        plan_data = _make_plan()
        plan = EditPlan(**plan_data)
        faces = [{"x": 0.3, "y": 0.8, "w": 0.2, "h": 0.15}]
        assert _caption_overlaps_face(plan, 1.0, faces) is True

    def test_face_above_caption_zone(self):
        plan_data = _make_plan()
        plan = EditPlan(**plan_data)
        faces = [{"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.15}]
        assert _caption_overlaps_face(plan, 1.0, faces) is False


class TestLoudnessFlagging:
    def test_music_too_loud(self, tmp_path):
        plan_data = _make_plan(music={"file": "music.mp3", "volume_db": -5})
        plan = EditPlan(**plan_data)
        # Mock measure_clip_lufs to return quiet speech
        with patch("engine.qc_sampler.measure_clip_lufs", return_value=-25.0):
            frames = [{"time": 1.0, "path": _make_white_image(tmp_path), "label": "f1"}]
            audio_clips = [{"time": 1.0, "path": str(tmp_path / "a.wav"), "label": "cap_0"}]
            issues = deterministic_checks(plan, frames, audio_clips)
        music_issues = [i for i in issues if i.type == "music_too_loud"]
        assert len(music_issues) >= 1


class TestPatchProducesValidPlan:
    def test_patch_music_volume(self):
        plan_data = _make_plan(music={"file": "music.mp3", "volume_db": -5})
        issues = [QCIssue(
            segment_id=None, timestamp=0, type="music_too_loud",
            severity="warning", description="too loud",
            suggested_fix="lower_music_volume",
        )]
        patched, changes = patch_plan(plan_data, issues)
        assert patched["music"]["volume_db"] == -9
        assert len(changes) == 1

    def test_patch_adds_zoom_for_frozen(self):
        plan_data = _make_plan()
        issues = [QCIssue(
            segment_id="s1", timestamp=1.0, type="frozen_frame",
            severity="warning", description="frozen",
            suggested_fix="add_zoom_effect",
        )]
        patched, changes = patch_plan(plan_data, issues)
        seg = next(s for s in patched["segments"] if s["id"] == "s1")
        assert seg["zoom"]["to"] > 1.0
        assert len(changes) == 1


class TestMaxRoundsEnforced:
    def test_max_rounds_constant(self):
        assert MAX_ROUNDS == 2


class TestSSIM:
    def test_identical_images(self, tmp_path):
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        ssim = _ssim_gray(img, img)
        assert ssim > 0.99

    def test_different_images(self, tmp_path):
        a = np.ones((100, 100, 3), dtype=np.uint8) * 200
        b = np.zeros((100, 100, 3), dtype=np.uint8)
        ssim = _ssim_gray(a, b)
        assert ssim < 0.5
