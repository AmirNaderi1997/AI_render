from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

from engine import font_library as fonts
from engine.schema import validate_plan


def _library_at(monkeypatch, tmp_path):
    monkeypatch.setattr(fonts, "LIBRARY_ROOT", tmp_path / "font-library")
    monkeypatch.setattr(fonts, "CANDIDATES", tmp_path / "font-library" / "candidates")
    monkeypatch.setattr(fonts, "APPROVED", tmp_path / "font-library" / "approved")
    monkeypatch.setattr(fonts, "INDEX", tmp_path / "font-library" / "library.json")


def test_font_import_review_approval_and_hash(monkeypatch, tmp_path):
    _library_at(monkeypatch, tmp_path)
    source = Path(__file__).resolve().parents[1] / "presets/fonts/Vazirmatn-Regular.ttf"
    candidate = fonts.add_font_file(source.name, source.read_bytes())
    assert candidate["review_state"] == "candidate"
    assert candidate["metadata"]["family"] == "Vazirmatn"
    assert candidate["metadata"]["persian_coverage"]["supported"]
    assert candidate["metadata"]["latin_coverage"]["supported"]
    assert not fonts.list_library()["approved"]

    approved = fonts.approve(candidate["id"])
    assert approved["id"] == "font_" + hashlib.sha256(source.read_bytes()).hexdigest()[:20]
    assert approved["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert fonts.resolve_font(approved["id"])["path"].read_bytes() == source.read_bytes()
    assert fonts.list_library()["candidates"] == []


def test_remove_approved_font_hides_it_but_preserves_old_plan_and_reimport_restores(monkeypatch, tmp_path):
    _library_at(monkeypatch, tmp_path)
    source = Path(__file__).resolve().parents[1] / "presets/fonts/Vazirmatn-Regular.ttf"
    approved = fonts.approve(fonts.add_font_file(source.name, source.read_bytes())["id"])

    removed = fonts.remove(approved["id"])
    assert removed["state"] == "archived"
    assert fonts.list_library()["approved"] == []
    assert fonts.resolve_font(approved["id"])["path"].read_bytes() == source.read_bytes()

    restored = fonts.approve(fonts.add_font_file(source.name, source.read_bytes())["id"])
    assert restored["id"] == approved["id"]
    assert [entry["id"] for entry in fonts.list_library()["approved"]] == [approved["id"]]


def test_remove_font_candidate_deletes_record_and_file(monkeypatch, tmp_path):
    _library_at(monkeypatch, tmp_path)
    source = Path(__file__).resolve().parents[1] / "presets/fonts/Vazirmatn-Regular.ttf"
    candidate = fonts.add_font_file(source.name, source.read_bytes())
    candidate_path = fonts.CANDIDATES / candidate["filename"]

    assert fonts.remove(candidate["id"])["state"] == "deleted"
    assert not candidate_path.exists()
    assert fonts.list_library()["candidates"] == []


def test_copied_text_reference_is_not_a_font(monkeypatch, tmp_path):
    _library_at(monkeypatch, tmp_path)
    ref = fonts.add_text_reference("Brand sample", "سلام 123", "Vazirmatn")
    assert ref["review_state"] == "candidate"
    assert ref["font_name"] == "Vazirmatn"
    try:
        fonts.approve(ref["id"])
    except ValueError as exc:
        assert "cannot be used as fonts" in str(exc)
    else:
        raise AssertionError("text-only reference must not become a render font")


def test_image_ocr_candidate_is_approximate(monkeypatch, tmp_path):
    _library_at(monkeypatch, tmp_path)
    out = io.BytesIO()
    Image.new("RGB", (120, 60), "white").save(out, format="PNG")
    item = fonts.add_image_reference("reference.png", out.getvalue())
    assert item["review_state"] == "candidate"
    assert item["kind"] == "image_reference"
    assert all(c["confidence"] == "approximate" for c in item["font_candidates"])
    assert all("do not prove identity" in c["basis"] for c in item["font_candidates"])


def test_missing_unapproved_plan_font_is_visible(monkeypatch, tmp_path):
    _library_at(monkeypatch, tmp_path)
    data = {
        "version": "0.1", "source": "video.mp4",
        "canvas": {"width": 1080, "height": 1920, "fps": 30,
                   "caption_font_id": "font_missing"},
        "segments": [{"id": "s1", "in": 0, "out": 1,
                      "zoom": {"from": 1, "to": 1}}],
        "export": {"file": "out.mp4"},
    }
    plan, errors = validate_plan(data, check_media=False)
    assert plan is None
    assert any("canvas.caption_font_id" in e and "missing or not approved" in e for e in errors)
