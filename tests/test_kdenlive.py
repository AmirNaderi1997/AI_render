"""Kdenlive project topology checked against the saved KDE fixtures."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from engine.build_mlt import build
from engine.kdenlive import build_kdenlive
from engine.schema import validate_plan
from engine import font_library


ROOT = Path(__file__).resolve().parent.parent


def props(node):
    return {p.get("name"): p.text for p in node.findall("property")}


def test_kdenlive_project_graph(tmp_path, media_dir):
    data = json.loads((ROOT / "samples/plans/full.json").read_text())
    data["source"] = str(media_dir / "raw.mp4")
    for item in data["broll"]:
        item["file"] = str(media_dir / "broll.mp4")
    data["music"]["file"] = str(media_dir / "music.wav")
    for item in data["sfx"]:
        item["file"] = str(media_dir / "whoosh.wav")
    plan, errors = validate_plan(data, check_media=True)
    assert not errors
    mlt, _ = build(plan, tmp_path)
    root = ET.parse(build_kdenlive(mlt)).getroot()
    reference = ET.parse(ROOT / "samples/reference/transform.kdenlive").getroot()
    assert root.get("producer") == reference.get("producer") == "main_bin"
    bin_ = root.find("playlist[@id='main_bin']")
    assert bin_ is not None
    assert props(bin_)["kdenlive:docproperties.version"] == "1.1"
    project = next(t for t in root.findall("tractor")
                   if props(t).get("kdenlive:projectTractor") == "1")
    sequence_id = project.find("track").get("producer")
    sequence = root.find(f"tractor[@id='{sequence_id}']")
    assert sequence is not None
    tracks = sequence.findall("track")
    assert len(tracks) == 5  # black background + four editable tracks
    assert props(sequence)["kdenlive:sequenceproperties.tracksCount"] == "4"
    tractors = [root.find(f"tractor[@id='{t.get('producer')}']") for t in tracks[1:]]
    assert all(t is not None and len(t.findall("track")) == 2 for t in tractors)
    assert [props(t).get("kdenlive:audio_track") for t in tractors] == ["1", "1", None, None]
    assert len(root.find("playlist[@id='playlist4']").findall("entry")) == len(plan.segments)
    chains = root.findall("chain")
    assert len(chains) == 4
    bin_refs = {e.get("producer") for e in bin_.findall("entry")}
    assert {c.get("id") for c in chains} <= bin_refs
    assert all(Path(props(c)["resource"]).is_absolute() for c in chains)


def test_kdenlive_keeps_approved_font_reference_and_bundles_font(tmp_path, media_dir, monkeypatch):
    library_root = tmp_path / "library"
    monkeypatch.setattr(font_library, "LIBRARY_ROOT", library_root)
    monkeypatch.setattr(font_library, "CANDIDATES", library_root / "candidates")
    monkeypatch.setattr(font_library, "APPROVED", library_root / "approved")
    monkeypatch.setattr(font_library, "INDEX", library_root / "library.json")
    font_path = ROOT / "presets/fonts/Vazirmatn-Regular.ttf"
    candidate = font_library.add_font_file(font_path.name, font_path.read_bytes())
    approved = font_library.approve(candidate["id"])

    data = json.loads((ROOT / "samples/plans/captions.json").read_text())
    data["source"] = str(media_dir / "raw.mp4")
    data["canvas"]["caption_font"] = approved["family"]
    data["canvas"]["caption_font_id"] = approved["id"]
    plan, errors = validate_plan(data, check_media=True)
    assert not errors
    mlt, _ = build(plan, tmp_path, base_dir=tmp_path)
    project = ET.parse(build_kdenlive(mlt)).getroot()
    bin_ = project.find("playlist[@id='main_bin']")
    saved = props(bin_)
    assert saved["ai-render:caption_font_id"] == approved["id"]
    assert saved["ai-render:caption_font_family"] == "Vazirmatn"
    assert saved["ai-render:caption_font_sha256"] == approved["sha256"]
    assert saved["ai-render:captions_ass"] == "captions.ass"
    assert (tmp_path / saved["ai-render:caption_font_file"]).is_file()


def test_kdenlive_preserves_editable_boundary_transitions(tmp_path, media_dir):
    data = json.loads((ROOT / "samples/plans/cut.json").read_text())
    data["source"] = str(media_dir / "raw.mp4")
    data["transitions"] = [{
        "from_segment_id": "s1", "to_segment_id": "s2",
        "type": "directional", "duration_frames": 6, "direction": "up",
        "intensity": 0.75, "source": "manual", "locked": True,
    }]
    plan, errors = validate_plan(data, check_media=True)
    assert not errors, errors
    mlt, _ = build(plan, tmp_path)
    render = ET.parse(mlt).getroot()
    assert render.find("tractor[@id='v1']") is not None
    project = ET.parse(build_kdenlive(mlt)).getroot()
    v1 = project.find("tractor[@id='tractor2']")
    transitions = v1.findall("transition")
    saved = [props(item) for item in transitions]
    assert {item["mlt_service"] for item in saved} == {"qtblend", "mix"}
    assert next(item for item in saved if item["mlt_service"] == "qtblend")["ai-render:type"] == "directional"
    assert len(project.find("playlist[@id='playlist4']").findall("entry")) == 1
    assert len(project.find("playlist[@id='playlist5']").findall("entry")) == 1


def test_kdenlive_preserves_boundary_zoom_type(tmp_path, media_dir):
    data = json.loads((ROOT / "samples/plans/cut.json").read_text())
    data["source"] = str(media_dir / "raw.mp4")
    data["transitions"] = [{"from_segment_id": "s1", "to_segment_id": "s2",
        "type": "zoom", "duration_frames": 6, "zoom_mode": "zoom_in", "zoom_scale": 1.12,
        "source": "manual", "locked": True}]
    plan, errors = validate_plan(data, check_media=True)
    assert not errors, errors
    mlt, _ = build(plan, tmp_path)
    project = ET.parse(build_kdenlive(mlt)).getroot()
    v1 = project.find("tractor[@id='tractor2']")
    saved = [props(item) for item in v1.findall("transition")]
    assert next(item for item in saved if item["mlt_service"] == "qtblend")["ai-render:type"] == "zoom"
