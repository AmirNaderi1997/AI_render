"""Kdenlive project topology checked against the saved KDE fixtures."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from engine.build_mlt import build
from engine.kdenlive import build_kdenlive
from engine.schema import validate_plan


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
