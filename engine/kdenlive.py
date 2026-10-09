"""Write a Kdenlive sequence project from the render MLT graph.

The layout follows the Kdenlive test-suite's 24.11.70 project fixtures. The
render MLT remains the authority for clip positions, effects and media paths.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


KDENLIVE_VERSION = "24.11.70"  # version of the upstream reference documents
DOCUMENT_VERSION = "1.1"


def _prop(parent: ET.Element, name: str, value: object) -> None:
    ET.SubElement(parent, "property", name=name).text = str(value)


def _get(parent: ET.Element, name: str) -> str | None:
    return next((p.text for p in parent.findall("property") if p.get("name") == name), None)


def _time(frame: int, fps: int) -> str:
    milliseconds = round(frame * 1000 / fps)
    seconds, ms = divmod(milliseconds, 1000)
    minutes, sec = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02}:{minute:02}:{sec:02}.{ms:03}"


def _media_info(path: Path, fps: int) -> tuple[int, bool, bool]:
    probe = shutil.which("ffprobe")
    if not probe:
        raise RuntimeError("ffprobe is required to build Kdenlive media metadata")
    data = json.loads(subprocess.check_output([
        probe, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
        "-of", "json", str(path),
    ], text=True))
    frames = max(1, round(float(data["format"]["duration"]) * fps))
    kinds = {stream["codec_type"] for stream in data.get("streams", [])}
    return frames, "video" in kinds, "audio" in kinds


def kdenlive_path() -> str | None:
    for name in ("kdenlive", "Kdenlive"):
        if p := shutil.which(name):
            return p
    for path in ("/Applications/Kdenlive.app/Contents/MacOS/kdenlive",
                 "/Applications/kdenlive.app/Contents/MacOS/kdenlive"):
        if Path(path).exists():
            return path
    return None


def build_kdenlive(mlt_path: Path, out_path: Path | None = None) -> Path:
    """Turn the project's render MLT into an editable four-track sequence."""
    mlt_path = Path(mlt_path).resolve()
    out_path = Path(out_path) if out_path else mlt_path.with_suffix(".kdenlive")
    render = ET.parse(mlt_path).getroot()
    font_metadata = {p.get("name"): p.text or "" for p in render.findall("property")
                     if (p.get("name") or "").startswith("ai-render:caption")}
    style_metadata = {p.get("name"): p.text or "" for p in render.findall("property")
                      if (p.get("name") or "").startswith("ai-render:style_")}
    if font_metadata.get("ai-render:caption_font_relative_path"):
        font_metadata["ai-render:caption_font_file"] = font_metadata["ai-render:caption_font_relative_path"]
    profile = copy.deepcopy(render.find("profile"))
    if profile is None:
        raise ValueError("render MLT has no profile")
    fps = round(int(profile.get("frame_rate_num", "30")) /
                int(profile.get("frame_rate_den", "1")))
    source_tractor = render.find("tractor")
    if source_tractor is None:
        raise ValueError("render MLT has no tractor")
    total = int(source_tractor.get("out", "0")) + 1
    if total < 1:
        raise ValueError("render MLT has no timeline")
    sequence_id = "{" + str(uuid.uuid4()) + "}"
    root = ET.Element("mlt", {"LC_NUMERIC": "C", "producer": "main_bin",
                              "root": str(mlt_path.parent), "version": "7.28.0"})
    root.append(profile)
    end = _time(total - 1, fps)
    black = ET.SubElement(root, "producer", id="black_track", **{"in": "0", "out": end})
    for key, val in (("length", 2147483647), ("eof", "continue"),
                     ("resource", "black"), ("mlt_service", "color"),
                     ("kdenlive:playlistid", "black_track"), ("mlt_image_format", "rgba")):
        _prop(black, key, val)

    sources = {p.get("id"): p for p in render.findall("producer")}
    ids: dict[str, int] = {}
    for index, (old_id, producer) in enumerate(sources.items(), start=1):
        path = Path(_get(producer, "resource") or "").resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        frames, video, audio = _media_info(path, fps)
        ids[old_id] = index
        chain = ET.SubElement(root, "chain", id=old_id, out=_time(frames - 1, fps))
        for key, val in (("length", frames), ("eof", "pause"),
                         ("resource", path), ("mlt_service", "avformat-novalidate"),
                         ("seekable", 1), ("video_index", 0 if video else -1),
                         ("audio_index", 0 if audio else -1),
                         ("kdenlive:folderid", -1), ("kdenlive:id", index),
                         ("kdenlive:control_uuid", "{" + str(uuid.uuid4()) + "}"),
                         ("kdenlive:clip_type", 0 if video else 1),
                         ("kdenlive:duration", _time(frames, fps)),
                         ("kdenlive:clipname", path.name)):
            _prop(chain, key, val)

    track_ids = []
    # Kdenlive stores audio tracks below video tracks. Within each track the
    # two playlists are its alternating clip lanes.
    for number, (name, audio) in enumerate((("A2", True), ("A1", True),
                                           ("V1", False), ("V2", False))):
        old = render.find(f"playlist[@id='{name.lower()}']")
        transition_tractor = render.find("tractor[@id='v1']") if name == "V1" else None
        source_lanes = ([render.find("playlist[@id='v1a']"), render.find("playlist[@id='v1b']")]
                        if transition_tractor is not None else [old, None])
        if source_lanes[0] is None:
            raise ValueError(f"render MLT lacks {name}")
        lane_a = ET.SubElement(root, "playlist", id=f"playlist{number * 2}")
        lane_b = ET.SubElement(root, "playlist", id=f"playlist{number * 2 + 1}")
        if audio:
            _prop(lane_a, "kdenlive:audio_track", 1)
            _prop(lane_b, "kdenlive:audio_track", 1)
        for source_lane, target_lane in zip(source_lanes, (lane_a, lane_b)):
            if source_lane is None:
                continue
            for item in source_lane:
                if item.tag not in ("entry", "blank"):
                    continue
                entry = copy.deepcopy(item)
                if entry.tag == "entry":
                    if entry.get("in") is not None:
                        entry.set("in", _time(int(entry.get("in")), fps))
                    if entry.get("out") is not None:
                        entry.set("out", _time(int(entry.get("out")), fps))
                    _prop(entry, "kdenlive:id", ids[entry.get("producer")])
                    for filt in list(entry.findall("filter")):
                        service = filt.attrib.pop("mlt_service", None)
                        if service == "avfilter.afade":
                            entry.remove(filt)
                            continue
                        if service:
                            _prop(filt, "mlt_service", service)
                            _prop(filt, "kdenlive_id", "affine" if service == "affine" else service)
                        if name == "A1" and service == "volume":
                            level = next((p for p in filt.findall("property") if p.get("name") == "level"), None)
                            if level is not None:
                                fade_start = max(0, total - round(0.8 * fps))
                                last = (level.text or "0=-14").split(";")[-1].split("=")[-1]
                                level.text = (level.text or "") + f";{fade_start}={last};{total - 1}=-60"
                else:
                    entry.set("length", _time(int(entry.get("length", "0")), fps))
                target_lane.append(entry)
        track_id = f"tractor{number}"
        track_ids.append(track_id)
        tractor = ET.SubElement(root, "tractor", id=track_id, **{"in": "0", "out": end})
        if audio:
            _prop(tractor, "kdenlive:audio_track", 1)
        for key, val in (("kdenlive:trackheight", 67), ("kdenlive:timeline_active", 1),
                         ("kdenlive:collapsed", 0)):
            _prop(tractor, key, val)
        for lane in (lane_a, lane_b):
            ET.SubElement(tractor, "track", producer=lane.get("id"),
                          hide="video" if audio else "audio")
        if transition_tractor is not None:
            for source_transition in transition_tractor.findall("transition"):
                transition = copy.deepcopy(source_transition)
                service = transition.attrib.pop("mlt_service", None)
                if transition.get("in") is not None:
                    transition.set("in", _time(int(transition.get("in")), fps))
                if transition.get("out") is not None:
                    transition.set("out", _time(int(transition.get("out")), fps))
                if service:
                    _prop(transition, "mlt_service", service)
                    _prop(transition, "kdenlive_id", service)
                tractor.append(transition)

    sequence = ET.SubElement(root, "tractor", id=sequence_id, **{"in": "0", "out": end})
    for key, val in (("kdenlive:uuid", sequence_id), ("kdenlive:clipname", "Rafiei edit"),
                     ("kdenlive:sequenceproperties.hasAudio", 1),
                     ("kdenlive:sequenceproperties.hasVideo", 1),
                     ("kdenlive:sequenceproperties.activeTrack", 2),
                     ("kdenlive:sequenceproperties.tracksCount", 4),
                     ("kdenlive:sequenceproperties.tracks", 4),
                     ("kdenlive:sequenceproperties.documentuuid", sequence_id),
                     ("kdenlive:sequenceproperties.videoTarget", 3),
                     ("kdenlive:sequenceproperties.audioTarget", 1),
                     ("kdenlive:sequenceproperties.zoom", 10),
                     ("kdenlive:duration", _time(total, fps)),
                     ("kdenlive:maxduration", total), ("kdenlive:producer_type", 17),
                     ("kdenlive:id", len(ids) + 1), ("kdenlive:clip_type", 0),
                     ("kdenlive:folderid", 2)):
        _prop(sequence, key, val)
    ET.SubElement(sequence, "track", producer="black_track")
    for track_id in track_ids:
        ET.SubElement(sequence, "track", producer=track_id)
    for number, audio in enumerate((True, True, False, False), start=1):
        tr = ET.SubElement(sequence, "transition")
        for key, val in (("a_track", 0), ("b_track", number),
                         ("mlt_service", "mix" if audio else "qtblend"),
                         ("kdenlive_id", "mix" if audio else "qtblend"),
                         ("internal_added", 237), ("always_active", 1)):
            _prop(tr, key, val)
        if audio:
            _prop(tr, "accepts_blanks", 1)
            _prop(tr, "sum", 1)
    # Caption sidecars remain available for manual import. MLT subtitle
    # filters have no Kdenlive effect ID and cause a Clip Problems dialog.

    bin_playlist = ET.SubElement(root, "playlist", id="main_bin")
    for key, val in (("kdenlive:folder.-1.2", "Sequences"),
                     ("kdenlive:sequenceFolder", 2),
                     ("kdenlive:docproperties.documentid", uuid.uuid4().int >> 80),
                     ("kdenlive:docproperties.kdenliveversion", KDENLIVE_VERSION),
                     ("kdenlive:docproperties.version", DOCUMENT_VERSION),
                     ("kdenlive:docproperties.uuid", sequence_id),
                     ("kdenlive:docproperties.opensequences", sequence_id),
                     ("kdenlive:docproperties.activetimeline", sequence_id),
                     ("kdenlive:docproperties.profile", "custom"),
                     ("kdenlive:docproperties.audioChannels", 2),
                     ("xml_retain", 1)):
        _prop(bin_playlist, key, val)
    # The native subtitle filter is intentionally represented by sidecars in
    # Kdenlive, where it can be imported as an editable subtitle track. Keep
    # the selected font's stable identity and bundled job asset in the project
    # metadata so the user's choice survives project export and handoff.
    for key, val in font_metadata.items():
        _prop(bin_playlist, key, val)
    for key, val in style_metadata.items():
        _prop(bin_playlist, key, val)
    ET.SubElement(bin_playlist, "entry", producer=sequence_id, **{"in": "0", "out": end})
    for old_id in ids:
        ET.SubElement(bin_playlist, "entry", producer=old_id, **{"in": "0", "out": "0"})
    project = ET.SubElement(root, "tractor", id="project_tractor", **{"in": "0", "out": end})
    _prop(project, "kdenlive:projectTractor", 1)
    ET.SubElement(project, "track", producer=sequence_id, **{"in": "0", "out": end})

    ET.indent(root, space=" ")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


def open_in_kdenlive(mlt: Path) -> None:
    """Launch Kdenlive on the generated editable project."""
    mlt = Path(mlt).resolve()
    if not mlt.exists():
        raise FileNotFoundError(mlt)
    target = mlt if mlt.suffix == ".kdenlive" else build_kdenlive(mlt)
    if sys.platform == "darwin":
        if not kdenlive_path():
            raise RuntimeError("Kdenlive not found; install from kdenlive.org")
        subprocess.Popen(["open", "-a", "Kdenlive", str(target)])
    else:
        bin_ = kdenlive_path()
        if not bin_:
            raise RuntimeError("Kdenlive not found; install from kdenlive.org")
        subprocess.Popen([bin_, str(target)])
