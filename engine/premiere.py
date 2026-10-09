"""Export an Edit Plan as a Premiere-compatible Final Cut Pro 7 XML bundle.

Premiere imports the legacy ``xmeml`` interchange format.  The XML keeps the
source clips and boundary transitions editable; captions are supplied as an
SRT sidecar because xmeml title generators are not a reliable Premiere caption
interchange.  A JSON report makes every mapping (and its verification status)
explicit instead of silently flattening unsupported data.
"""
from __future__ import annotations

import json
import hashlib
import re
import math
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

from .schema import EditPlan


PREMIERE_XML = "project_premiere.xml"
PREMIERE_CAPTIONS = "premiere_captions.srt"
PREMIERE_REPORT = "premiere_transition_report.json"
PREMIERE_BUNDLE = "project_premiere.zip"
PREMIERE_README = "README.txt"
PREMIERE_VERIFICATION = "premiere_native_verification.json"


@dataclass(frozen=True)
class AttachedMusic:
    """Background music attached to a job (separate from plan.music)."""
    file: Path
    volume: float = 0.3      # linear, 0.0-1.0
    fade_in: float = 2.0     # seconds
    fade_out: float = 3.0    # seconds

_CAPABILITY_EVIDENCE = {
    "application": "Adobe Premiere Pro",
    "version": "25.3.0",
    "verified_on": "2026-10-04",
    "scope": "Historical mapping capability only; it does not verify a newly generated package.",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan_sha256(plan: EditPlan, out_dir: Path) -> str:
    """Hash the saved plan bytes when available, otherwise canonical plan JSON."""
    plan_path = out_dir / "plan.json"
    if plan_path.is_file():
        return _sha256(plan_path)
    return hashlib.sha256(
        plan.model_dump_json(by_alias=True, exclude_none=False).encode("utf-8")
    ).hexdigest()


def _render_sha256(out_dir: Path) -> str | None:
    exports = out_dir / "exports"
    if not exports.is_dir():
        return None
    candidates = []
    for path in exports.glob("v*.mp4"):
        match = re.fullmatch(r"v([0-9]+)\.mp4", path.name)
        if match and path.is_file() and not path.is_symlink():
            candidates.append((int(match.group(1)), path))
    if not candidates:
        return None
    return _sha256(max(candidates, key=lambda item: item[0])[1])


def _music_sha256(plan: EditPlan, out_dir: Path) -> str | None:
    if not plan.music:
        return None
    music_path = Path(plan.music.file)
    if not music_path.is_absolute():
        music_path = out_dir / music_path
    if music_path.is_file():
        return _sha256(music_path)
    return None


def _artifact_identity(plan: EditPlan, out_dir: Path) -> dict:
    return {
        "job_id": out_dir.name,
        "plan_sha256": _plan_sha256(plan, out_dir),
        "xml_sha256": _sha256(out_dir / PREMIERE_XML),
        "srt_sha256": _sha256(out_dir / PREMIERE_CAPTIONS),
        "render_sha256": _render_sha256(out_dir),
        "music_sha256": _music_sha256(plan, out_dir),
    }


def _validate_native_observations(record: dict) -> None:
    required = {
        "schema_version", "evidence_type", "job_id", "plan_sha256",
        "xml_sha256", "srt_sha256", "render_sha256", "premiere_version", "prproj_path",
        "verification_time", "verified_sequence_name", "observed_frame_count",
        "observed_geometry", "transition_observations", "caption_observations",
        "relink_observations", "effect_observations", "save_reopen",
        "evidence_screenshot_paths",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ValueError(f"native verification record missing: {', '.join(missing)}")
    if record["schema_version"] != "1.0":
        raise ValueError("unsupported native verification schema_version")
    if record["evidence_type"] != "operator_observed":
        raise ValueError("native verification must be identified as operator_observed")
    for key in ("job_id", "plan_sha256", "xml_sha256", "srt_sha256",
                "premiere_version", "prproj_path", "verification_time",
                "verified_sequence_name"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError(f"native verification {key} must be a non-empty string")
    for key in ("plan_sha256", "xml_sha256", "srt_sha256", "render_sha256"):
        value = record[key]
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
            raise ValueError(f"native verification {key} must be a SHA-256 hex digest")
    if not isinstance(record["observed_frame_count"], int) or record["observed_frame_count"] < 1:
        raise ValueError("native verification observed_frame_count must be positive")
    geometry = record["observed_geometry"]
    for key in ("width", "height", "fps", "pixel_aspect", "field_order", "audio_sample_rate"):
        if key not in geometry:
            raise ValueError(f"native verification observed_geometry missing {key}")
    if not isinstance(record["transition_observations"], list):
        raise ValueError("native verification transition_observations must be a list")
    allowed = {"exact_editable", "editable_fallback", "rendered_only", "unsupported"}
    seen_boundaries = set()
    for item in record["transition_observations"]:
        for key in ("boundary_index", "imported_type", "duration_frames", "classification"):
            if key not in item:
                raise ValueError(f"transition observation missing {key}")
        if item["classification"] not in allowed:
            raise ValueError("transition observation has invalid classification")
        if item["boundary_index"] in seen_boundaries:
            raise ValueError("duplicate transition observation boundary_index")
        seen_boundaries.add(item["boundary_index"])
    if not isinstance(record["evidence_screenshot_paths"], list) or not record["evidence_screenshot_paths"]:
        raise ValueError("native verification requires at least one evidence screenshot path")


def _planned_boundaries(plan: EditPlan) -> dict[int, dict]:
    transitions = {(item.from_segment_id, item.to_segment_id): item for item in plan.transitions}
    expected = {}
    for index in range(len(plan.segments) - 1):
        left, right = plan.segments[index:index + 2]
        transition = transitions.get((left.id, right.id))
        expected[index] = {
            "type": transition.type if transition else "hard_cut",
            "duration_frames": transition.duration_frames if transition else 0,
        }
    return expected


def _validate_observations_against_plan(plan: EditPlan, record: dict) -> None:
    """Reject structurally valid observations that contradict the saved plan.

    A native record is operator evidence, not a client-controlled certification
    switch.  In addition to hash binding, every boundary must be accounted for
    and its observed duration/classification must be compatible with the exact
    planned boundary it claims to describe.
    """
    expected = _planned_boundaries(plan)
    observed = {item["boundary_index"]: item for item in record["transition_observations"]}
    if set(observed) != set(expected):
        raise ValueError("native verification must observe every planned boundary exactly once")
    for index, planned in expected.items():
        item = observed[index]
        if item["duration_frames"] != planned["duration_frames"]:
            raise ValueError(f"boundary {index} observed duration does not match the plan")
        imported_type = item["imported_type"].strip().lower()
        classification = item["classification"]
        kind = planned["type"]
        if kind == "hard_cut" and (classification != "exact_editable" or imported_type != "cut"):
            raise ValueError(f"boundary {index} hard cut observation is inconsistent")
        if kind == "crossfade" and (
            classification != "exact_editable" or "cross dissolve" not in imported_type
        ):
            raise ValueError(f"boundary {index} crossfade observation is inconsistent")
        if kind == "directional" and (
            classification != "editable_fallback" or "cross dissolve" not in imported_type
        ):
            raise ValueError(f"boundary {index} directional fallback observation is inconsistent")
        if kind == "zoom" and classification == "editable_fallback" and "cross dissolve" not in imported_type:
            raise ValueError(f"boundary {index} zoom fallback must be an observed Cross Dissolve")
        if kind == "zoom" and classification == "exact_editable":
            raise ValueError(f"boundary {index} zoom cannot be certified as exact_editable")


def write_native_verification_record(plan: EditPlan, out_dir: Path, observations: dict) -> Path:
    """Persist validated operator observations bound to the current artifacts.

    This function is intentionally local-only: there is no web/API endpoint that
    accepts a client assertion and turns it into package verification.
    """
    out_dir = Path(out_dir)
    identity = _artifact_identity(plan, out_dir)
    record = {**observations, **identity, "schema_version": "1.0",
              "evidence_type": "operator_observed"}
    _validate_native_observations(record)
    _validate_observations_against_plan(plan, record)
    prproj_path = Path(record["prproj_path"])
    if not prproj_path.is_absolute() or not prproj_path.is_file():
        raise ValueError("native verification prproj_path must be an existing absolute file")
    for screenshot in record["evidence_screenshot_paths"]:
        screenshot_path = Path(screenshot)
        if not screenshot_path.is_absolute():
            screenshot_path = out_dir / screenshot_path
        if not screenshot_path.is_file():
            raise ValueError(f"native verification screenshot does not exist: {screenshot}")
    path = out_dir / PREMIERE_VERIFICATION
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)
    return path


def _current_verification(plan: EditPlan, out_dir: Path, identity: dict) -> dict:
    path = out_dir / PREMIERE_VERIFICATION
    if not path.is_file():
        return {"status": "unverified", "record_file": PREMIERE_VERIFICATION,
                "reason": "No hash-bound operator observation record exists."}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        _validate_native_observations(record)
        _validate_observations_against_plan(plan, record)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return {"status": "invalid", "record_file": PREMIERE_VERIFICATION,
                "reason": str(error)}
    mismatches = [key for key, expected in identity.items() if record.get(key) != expected]
    if mismatches:
        return {"status": "invalidated", "record_file": PREMIERE_VERIFICATION,
                "reason": "Artifact identity mismatch: " + ", ".join(mismatches),
                "mismatched_fields": mismatches}
    return {"status": "verified", "record_file": PREMIERE_VERIFICATION,
            "evidence_type": "operator_observed", "verification_time": record["verification_time"],
            "premiere_version": record["premiere_version"], "prproj_path": record["prproj_path"],
            "verified_sequence_name": record["verified_sequence_name"],
            "observed_frame_count": record["observed_frame_count"],
            "observed_geometry": record["observed_geometry"],
            "transition_observations": record["transition_observations"],
            "caption_observations": record["caption_observations"],
            "relink_observations": record["relink_observations"],
            "effect_observations": record["effect_observations"],
            "save_reopen": record["save_reopen"],
            "evidence_screenshot_paths": record["evidence_screenshot_paths"]}


def _text(parent: ET.Element, tag: str, value: object) -> ET.Element:
    node = ET.SubElement(parent, tag)
    # ElementTree serializes XML 1.0 control characters verbatim. A source
    # filename or segment label containing one makes Premiere reject the file.
    node.text = ''.join(ch for ch in str(value) if ch in '\t\n\r' or
                        ord(ch) >= 0x20 and not 0xD800 <= ord(ch) <= 0xDFFF
                        and ord(ch) not in (0xFFFE, 0xFFFF))
    return node


def _rate(parent: ET.Element, fps: int) -> ET.Element:
    rate = ET.SubElement(parent, "rate")
    _text(rate, "timebase", fps)
    _text(rate, "ntsc", "FALSE")
    return rate


def _resolve(path: str, base_dir: Path) -> Path:
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()


def _transition_effect(parent: ET.Element) -> None:
    effect = ET.SubElement(parent, "effect")
    # Premiere Pro 25.3.0 silently substituted Cross Dissolve when an xmeml v5
    # transition declared ``Slide``.  Direction and intensity did not survive
    # the import.  Emit the verified fallback ourselves so the XML never claims
    # an editable mapping that Premiere cannot reproduce accurately.  The MLT
    # render still contains the requested directional transition and the JSON
    # transfer report records the fallback at the exact boundary.
    name, effect_id, category = "Cross Dissolve", "Cross Dissolve", "Dissolve"
    _text(effect, "name", name)
    _text(effect, "effectid", effect_id)
    _text(effect, "effectcategory", category)
    _text(effect, "effecttype", "transition")
    _text(effect, "mediatype", "video")
    _text(effect, "startratio", 0)
    _text(effect, "endratio", 1)


def _audio_transition(parent: ET.Element) -> None:
    effect = ET.SubElement(parent, "effect")
    _text(effect, "name", "Cross Fade (+3dB)")
    _text(effect, "effectid", "Cross Fade (+3dB)")
    _text(effect, "effectcategory", "Cross Fades")
    _text(effect, "effecttype", "transition")
    _text(effect, "mediatype", "audio")
    _text(effect, "startratio", 0)
    _text(effect, "endratio", 1)


def _srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(plan: EditPlan, path: Path) -> None:
    blocks = []
    for index, caption in enumerate(plan.captions, 1):
        blocks.append(
            f"{index}\n{_srt_time(caption.start)} --> {_srt_time(caption.end)}\n"
            f"{caption.text.strip()}"
        )
    path.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")


def _add_file(clip: ET.Element, file_id: str, source: Path, source_frames: int,
              fps: int, width: int, height: int, define: bool,
              pathurl: str, has_source_audio: bool = True) -> None:
    file_node = ET.SubElement(clip, "file", {"id": file_id})
    if not define:
        return
    _text(file_node, "name", source.name)
    _text(file_node, "pathurl", pathurl)
    _rate(file_node, fps)
    _text(file_node, "duration", source_frames)
    media = ET.SubElement(file_node, "media")
    video = ET.SubElement(media, "video")
    sample = ET.SubElement(video, "samplecharacteristics")
    _rate(sample, fps)
    _text(sample, "width", width)
    _text(sample, "height", height)
    _text(sample, "anamorphic", "FALSE")
    _text(sample, "pixelaspectratio", "square")
    _text(sample, "fielddominance", "none")
    if has_source_audio:
        audio = ET.SubElement(media, "audio")
        sample = ET.SubElement(audio, "samplecharacteristics")
        _text(sample, "depth", 16)
        _text(sample, "samplerate", 48000)
        _text(audio, "channelcount", 2)


def _link_av(clip: ET.Element, segment_id: str, index: int, has_source_audio: bool) -> None:
    pairs = [("video", f"video-{segment_id}")]
    if has_source_audio:
        pairs.append(("audio", f"audio-{segment_id}"))
    for media_type, ref in pairs:
        link = ET.SubElement(clip, "link")
        _text(link, "linkclipref", ref)
        _text(link, "mediatype", media_type)
        _text(link, "trackindex", 1)
        _text(link, "clipindex", index + 1)


def _add_clip(track: ET.Element, *, segment, index: int, start: int, end: int,
              previous_overlap: bool, next_overlap: bool, fps: int, source: Path,
              source_frames: int, width: int, height: int, media_type: str,
              define_file: bool, source_pathurl: str, has_source_audio: bool) -> None:
    clip = ET.SubElement(track, "clipitem", {"id": f"{media_type}-{segment.id}"})
    _text(clip, "name", f"{segment.id} · {source.name}")
    _text(clip, "duration", end - start)
    _rate(clip, fps)
    _text(clip, "start", -1 if previous_overlap else start)
    _text(clip, "end", -1 if next_overlap else end)
    source_in = round(segment.in_ * fps)
    _text(clip, "in", source_in)
    _text(clip, "out", source_in + (end - start))
    _add_file(clip, "source-1", source, source_frames, fps, width, height,
              define_file, source_pathurl, has_source_audio)
    _link_av(clip, segment.id, index, has_source_audio)
    if media_type == "audio":
        source_track = ET.SubElement(clip, "sourcetrack")
        _text(source_track, "mediatype", "audio")
        _text(source_track, "trackindex", 1)


def _add_transition(track: ET.Element, transition, start: int, end: int,
                    fps: int, media_type: str) -> None:
    item = ET.SubElement(track, "transitionitem")
    _text(item, "name", "Audio crossfade" if media_type == "audio" else transition.type)
    _rate(item, fps)
    _text(item, "start", start)
    _text(item, "end", end)
    _text(item, "alignment", "center")
    if media_type == "audio":
        _audio_transition(item)
    else:
        _transition_effect(item)


def _track(plan: EditPlan, media_parent: ET.Element, media_type: str, source: Path,
           source_frames: int, source_pathurl: str, has_source_audio: bool) -> None:
    container = ET.SubElement(media_parent, media_type)
    if media_type == "video":
        fmt = ET.SubElement(container, "format")
        sample = ET.SubElement(fmt, "samplecharacteristics")
        _rate(sample, plan.canvas.fps)
        _text(sample, "width", plan.canvas.width)
        _text(sample, "height", plan.canvas.height)
        _text(sample, "anamorphic", "FALSE")
        _text(sample, "pixelaspectratio", "square")
        _text(sample, "fielddominance", "none")
    track = ET.SubElement(container, "track")
    transitions = {(item.from_segment_id, item.to_segment_id): item for item in plan.transitions}
    cursor = 0
    for index, segment in enumerate(plan.segments):
        previous = None if index == 0 else transitions.get((plan.segments[index - 1].id, segment.id))
        next_ = None if index + 1 == len(plan.segments) else transitions.get((segment.id, plan.segments[index + 1].id))
        previous_frames = previous.duration_frames if previous and previous.type != "hard_cut" else 0
        next_frames = next_.duration_frames if next_ and next_.type != "hard_cut" else 0
        start = cursor - previous_frames
        end = start + round(segment.duration * plan.canvas.fps)
        _add_clip(
            track, segment=segment, index=index, start=start, end=end,
            previous_overlap=bool(previous_frames), next_overlap=bool(next_frames),
            fps=plan.canvas.fps, source=source, source_frames=source_frames,
            width=plan.canvas.width, height=plan.canvas.height, media_type=media_type,
            define_file=(media_type == "video" and index == 0),
            source_pathurl=source_pathurl, has_source_audio=has_source_audio,
        )
        if next_frames:
            _add_transition(track, next_, end - next_frames, end, plan.canvas.fps, media_type)
        cursor = end
    _text(track, "enabled", "TRUE")
    _text(track, "locked", "FALSE")


def _report(plan: EditPlan, source: Path, identity: dict,
            current_verification: dict, source_reference: str | None = None) -> dict:
    rows = []
    transitions = {(t.from_segment_id, t.to_segment_id): t for t in plan.transitions}
    edit_plan_id = getattr(plan, "id", None) or plan.export.file
    plan_fingerprint = identity["plan_sha256"]
    fps = plan.canvas.fps
    cursor = 0
    segment_starts: dict[str, int] = {}
    for index, segment in enumerate(plan.segments):
        segment_starts[segment.id] = cursor
        cursor += round(segment.duration * fps)
        if index < len(plan.segments) - 1:
            next_item = transitions.get((segment.id, plan.segments[index + 1].id))
            if next_item:
                cursor -= next_item.duration_frames
    for index in range(len(plan.segments) - 1):
        left, right = plan.segments[index:index + 2]
        transition = transitions.get((left.id, right.id))
        kind = transition.type if transition else "hard_cut"
        frames = transition.duration_frames if transition else 0
        start = segment_starts[right.id]
        verified_mapping = kind in {"hard_cut", "crossfade", "directional"}
        classification = ("exact_editable" if kind in {"hard_cut", "crossfade"}
                          else "editable_fallback" if kind == "directional"
                          else "unverified")
        if kind == "zoom":
            representation = "Candidate Cross Dissolve (native zoom-boundary import unverified)"
            explanation = "Zoom is rendered in the authoritative MP4. The XML proposes a Cross Dissolve, but this zoom-boundary mapping has not passed native import, save, and reopen verification."
            native_status = "unverified"
        elif kind == "directional":
            representation = "Cross Dissolve"
            explanation = "Premiere Pro 25.3.0 imports the overlap as Cross Dissolve; direction and intensity remain in the rendered MP4."
            native_status = "verified_baseline"
        elif kind == "crossfade":
            representation = "Cross Dissolve + Cross Fade (+3dB)"
            explanation = "Native FCP7 XML import preserves the planned video and audio overlap."
            native_status = "verified_baseline"
        else:
            representation = "Cut"
            explanation = "Adjacent clips meet with no overlap."
            native_status = "verified_baseline"
        observation = next((item for item in current_verification.get(
            "transition_observations", []) if item.get("boundary_index") == index), None)
        current = ({"status": "verified", "classification": observation["classification"],
                    "observation": observation}
                   if current_verification.get("status") == "verified" and observation else
                   {"status": "unverified", "classification": "unverified",
                    "reason": current_verification.get("reason", "No observation for this boundary.")})
        rows.append({
            "edit_plan_id": edit_plan_id,
            "boundary_index": index, "from_segment_id": left.id,
            "to_segment_id": right.id, "plan_type": kind,
            "duration_frames": frames,
            "planned_frame_range": {"start": start, "end_exclusive": start + frames},
            "direction": transition.direction if transition and kind == "directional" else None,
            "intensity": transition.intensity if transition and kind == "directional" else None,
            "zoom_mode": transition.zoom_mode if transition and kind == "zoom" else None,
            "zoom_scale": transition.zoom_scale if transition and kind == "zoom" else None,
            "requested_behavior": {"type": kind, "duration_frames": frames,
                "direction": transition.direction if transition and kind == "directional" else None,
                "intensity": transition.intensity if transition and kind == "directional" else None,
                "zoom_mode": transition.zoom_mode if transition and kind == "zoom" else None,
                "zoom_scale": transition.zoom_scale if transition and kind == "zoom" else None,
                "source": transition.source if transition else "default",
                "locked": transition.locked if transition else False},
            "premiere_representation": representation,
            # Keep the legacy field's terse value for existing report readers.
            "premiere_mapping": ("Cross Dissolve" if kind in {"crossfade", "directional", "zoom"} else "Cut"),
            "audio_mapping": "Cross Fade (+3dB)" if frames else "None",
            "classification": classification,
            "capability_classification": classification,
            "current_artifact_verification": current,
            "status": {"exact_editable": "supported", "editable_fallback": "fallback", "unverified": "unverified"}[classification],
            "explanation": explanation, "note": explanation,
            "native_verification": {"status": native_status,
                "application": "Adobe Premiere Pro" if verified_mapping else None,
                "version": "25.3.0" if verified_mapping else None,
                "verified_on": "2026-10-04" if verified_mapping else None,
                "scope": "historical_capability" if verified_mapping else "none"},
        })
    caption_observation = current_verification.get("caption_observations", {})
    captions_current_verified = (
        current_verification.get("status") == "verified"
        and caption_observation.get("content_timing_classification") == "sidecar_editable"
        and caption_observation.get("caption_track_visible") is True
        and caption_observation.get("persisted_after_reopen") is True
    )
    captions = [{
        "edit_plan_id": edit_plan_id, "caption_index": i,
        "planned_timing_seconds": {"start": caption.start, "end": caption.end},
        "planned_frame_range": {"start": round(caption.start * fps), "end_exclusive": round(caption.end * fps)},
        "requested_behavior": {"text": caption.text, "style": caption.style},
        "premiere_representation": "UTF-8 SRT sidecar; import separately as caption track",
        "classification": "sidecar_editable",
        "capability_classification": "sidecar_editable",
        "current_artifact_verification": (
            {"status": "verified", "classification": "sidecar_editable",
             "observation": caption_observation}
            if captions_current_verified else
            {"status": "unverified", "classification": "unverified",
             "reason": current_verification.get("reason", "Caption track/content/timing/reopen inspection incomplete.")}
        ),
        "explanation": "Text and output-timeline timing are editable after importing the SRT. SRT does not carry AI Render font, weight, outline, or placement styling.",
        "native_verification": {"status": "unverified", "application": None, "version": None, "verified_on": None},
    } for i, caption in enumerate(plan.captions)]
    effects = []
    for effect in plan.visual_effects:
        segment = next(s for s in plan.segments if s.id == effect.segment_id)
        start = segment_starts[segment.id]
        frames = round(segment.duration * fps)
        effect_observation = next((item for item in current_verification.get(
            "effect_observations", []) if item.get("segment_id") == effect.segment_id
            and item.get("effect_type") == effect.type), None)
        effects.append({
            "edit_plan_id": edit_plan_id, "segment_id": effect.segment_id, "effect_type": effect.type,
            "planned_frame_range": {"start": start, "end_exclusive": start + frames},
            "requested_behavior": {"type": effect.type},
            "premiere_representation": "None; retained in rendered MP4",
            "classification": "rendered_only",
            "capability_classification": "rendered_only",
            "current_artifact_verification": (
                {"status": "verified", "classification": effect_observation.get("classification", "rendered_only"),
                 "observation": effect_observation}
                if current_verification.get("status") == "verified" and effect_observation else
                {"status": "unverified", "classification": "unverified",
                 "reason": current_verification.get("reason", "No current effect observation.")}
            ),
            "explanation": "No editable Premiere mapping has been natively verified for this effect.",
            "native_verification": {"status": "not_attempted", "application": None, "version": None, "verified_on": None},
        })
    for segment in plan.segments:
        if abs(segment.zoom.from_ - 1.0) < 1e-6 and abs(segment.zoom.to - 1.0) < 1e-6:
            continue
        start = segment_starts[segment.id]
        frames = round(segment.duration * fps)
        effect_observation = next((item for item in current_verification.get(
            "effect_observations", []) if item.get("segment_id") == segment.id
            and item.get("effect_type") == "legacy_segment_zoom"), None)
        effects.append({
            "edit_plan_id": edit_plan_id, "segment_id": segment.id, "effect_type": "legacy_segment_zoom",
            "planned_frame_range": {"start": start, "end_exclusive": start + frames},
            "requested_behavior": {"type": "legacy_segment_zoom", "from_scale": segment.zoom.from_, "to_scale": segment.zoom.to},
            "premiere_representation": "None; retained in rendered MP4",
            "classification": "rendered_only",
            "capability_classification": "rendered_only",
            "current_artifact_verification": (
                {"status": "verified", "classification": effect_observation.get("classification", "rendered_only"),
                 "observation": effect_observation}
                if current_verification.get("status") == "verified" and effect_observation else
                {"status": "unverified", "classification": "unverified",
                 "reason": current_verification.get("reason", "No current effect observation.")}
            ),
            "explanation": "Legacy per-segment zoom remains in the authoritative render; no editable Premiere mapping is defined.",
            "native_verification": {"status": "not_attempted", "application": None, "version": None, "verified_on": None},
        })
    warnings = [row["explanation"] for row in rows if row["classification"] == "editable_fallback"]
    if effects:
        warnings.append("Segment visual effects are retained in the rendered MP4 and are rendered_only in Premiere.")
    if captions:
        warnings.append("Captions are delivered as premiere_captions.srt and must be imported separately; SRT styling is limited.")
    if not source.is_absolute():
        warnings.append("Source media path is relative; relink media in Premiere if the package is moved.")
    warnings.append("The rendered MP4 is visually authoritative wherever a feature is not transferred exactly.")
    generated_at = datetime.now(timezone.utc).isoformat()
    classifications = [r["classification"] for r in rows] + [c["classification"] for c in captions] + [e["classification"] for e in effects]
    component_rows = rows + captions + effects
    all_components_verified = all(
        item["current_artifact_verification"]["status"] == "verified"
        for item in component_rows
    )
    geometry = current_verification.get("observed_geometry", {})
    sequence_verified = (
        current_verification.get("status") == "verified"
        and current_verification.get("observed_frame_count") == plan.output_frames
        and geometry.get("width") == plan.canvas.width
        and geometry.get("height") == plan.canvas.height
        and float(geometry.get("fps", 0)) == float(fps)
        and current_verification.get("save_reopen", {}).get("status") == "verified"
    )
    relink_verified = current_verification.get("relink_observations", {}).get("status") == "verified"
    fully_current_verified = all_components_verified and sequence_verified and relink_verified
    result = ("current_artifact_verified_with_limitations" if fully_current_verified
              else "awaiting_current_artifact_verification")
    return {
        "schema_version": "1.0",
        "created_at": generated_at,
        "edit_plan_version": plan.version,
        "edit_plan_id": edit_plan_id,
        "edit_plan_sha256": plan_fingerprint,
        "format": "Final Cut Pro 7 XML Interchange (xmeml v5)",
        "source": str(source),
        "source_media": {"path": source_reference or str(source),
            "reference_type": "relative_package_path" if source_reference else "absolute_file_url",
            "portable": bool(source_reference), "relink_required_when_moved": not bool(source_reference)},
        "sequence": {"name": "AI Render editable sequence", "fps": fps,
            "width": plan.canvas.width, "height": plan.canvas.height,
            "output_frames": plan.output_frames,
            "duration_seconds": plan.output_duration},
        "fps": plan.canvas.fps,
        "output_frames": plan.output_frames,
        "output_duration_seconds": plan.output_duration,
        "generated_files": [
            {"filename": PREMIERE_XML, "role": "FCP7 XML interchange sequence"},
            {"filename": PREMIERE_CAPTIONS, "role": "editable caption sidecar"},
            {"filename": PREMIERE_REPORT, "role": "compatibility manifest"},
            {"filename": PREMIERE_README, "role": "Premiere import instructions"},
            {"filename": PREMIERE_BUNDLE, "role": "all-in-one ZIP package"},
        ],
        "artifact_identity": identity,
        "historical_capability_evidence": {
            **_CAPABILITY_EVIDENCE,
            "exact": ["hard_cut", "crossfade"],
            "fallback": ["directional"],
            "unverified": ["zoom", "captions", "visual_effects", "fresh_sequence_duration", "package_relinking"],
        },
        "current_artifact_verification": {
            **current_verification,
            "fully_verified": fully_current_verified,
            "sequence_contract_verified": sequence_verified,
            "relink_verified": relink_verified,
        },
        "native_verification": {
            "application": "Adobe Premiere Pro",
            "version": "25.3.0",
            "verified_on": "2026-10-04",
            "scope": "Historical baseline only: hard cuts, crossfades, and directional Cross Dissolve fallback. Fresh package verification is reported separately in current_artifact_verification.",
            "exact": ["hard_cut", "crossfade"],
            "fallback": ["directional"],
            "unverified": ["zoom", "captions", "visual_effects", "fresh_sequence_duration", "package_relinking"],
        },
        "transitions": rows,
        "captions": {"count": len(captions), "delivery": "sidecar", "filename": PREMIERE_CAPTIONS,
            "components": captions,
            "styling": {"transfers": [], "does_not_transfer": ["font", "weight", "outline", "placement", "RTL styling"]}},
        "visual_effects": effects,
        "package_portability": {"media_embedded": True, "source_reference": source_reference or str(source),
            "relink_instructions": "Extract the package contents together; XML media references are relative to the package root."},
        "overall_result": result,
        "warnings": warnings,
    }


def validate_manifest(report: dict) -> None:
    """Deterministic validation for the compatibility manifest contract."""
    classifications = {"exact_editable", "editable_fallback", "sidecar_editable", "rendered_only", "unsupported", "unverified"}
    for key in ("schema_version", "created_at", "edit_plan_version", "source_media", "sequence", "generated_files", "native_verification", "historical_capability_evidence", "current_artifact_verification", "artifact_identity", "transitions", "captions", "visual_effects", "package_portability", "overall_result", "warnings"):
        if key not in report:
            raise ValueError(f"compatibility manifest missing {key}")
    for kind, entries in (("transition", report["transitions"]), ("visual effect", report["visual_effects"])):
        for index, entry in enumerate(entries):
            if entry.get("classification") not in classifications:
                raise ValueError(f"{kind}[{index}] has invalid classification")
            for key in ("edit_plan_id", "planned_frame_range", "requested_behavior", "premiere_representation", "classification", "capability_classification", "current_artifact_verification", "explanation", "native_verification"):
                if key not in entry:
                    raise ValueError(f"{kind}[{index}] missing {key}")
    for index, entry in enumerate(report["captions"].get("components", [])):
        if entry.get("classification") not in classifications:
            raise ValueError(f"caption[{index}] has invalid classification")
        for key in ("edit_plan_id", "planned_timing_seconds", "planned_frame_range", "requested_behavior", "premiere_representation", "classification", "capability_classification", "current_artifact_verification", "explanation", "native_verification"):
            if key not in entry:
                raise ValueError(f"caption[{index}] missing {key}")


def _audio_clipitem(track: ET.Element, fps: int, *, clip_id: str, file_id: str, label: str,
                    path: Path, pathurl: str, start: int, frames: int, file_frames: int,
                    define_file: bool = True) -> ET.Element:
    """Add an audio clipitem with an "Audio Levels" filter; return its level <parameter>."""
    clip = ET.SubElement(track, "clipitem", {"id": clip_id})
    _text(clip, "name", label)
    _text(clip, "duration", frames)
    _rate(clip, fps)
    _text(clip, "start", start)
    _text(clip, "end", start + frames)
    _text(clip, "in", 0)
    _text(clip, "out", frames)

    file_node = ET.SubElement(clip, "file", {"id": file_id})
    if define_file:  # repeat uses of one file reference it by id only
        _text(file_node, "name", path.name)
        _text(file_node, "pathurl", pathurl)
        _rate(file_node, fps)
        _text(file_node, "duration", file_frames)
        media = ET.SubElement(file_node, "media")
        audio = ET.SubElement(media, "audio")
        sample = ET.SubElement(audio, "samplecharacteristics")
        _text(sample, "depth", 16)
        _text(sample, "samplerate", 48000)
        _text(audio, "channelcount", 2)

    source_track = ET.SubElement(clip, "sourcetrack")
    _text(source_track, "mediatype", "audio")
    _text(source_track, "trackindex", 1)

    volume_filter = ET.SubElement(clip, "filter")
    effect = ET.SubElement(volume_filter, "effect")
    _text(effect, "name", "Audio Levels")
    _text(effect, "effectid", "audiolevels")
    _text(effect, "effectcategory", "Audio")
    _text(effect, "effecttype", "audio")
    _text(effect, "mediatype", "audio")

    param = ET.SubElement(effect, "parameter", {"authoringApp": "PremierePro"})
    _text(param, "parameterid", "level")
    _text(param, "name", "Level")
    return param


def _keyframe(param: ET.Element, when: int, value: object) -> None:
    kf = ET.SubElement(param, "keyframe")
    _text(kf, "when", when)
    _text(kf, "value", value)


def _music_track(plan: EditPlan, audio_parent: ET.Element, base: Path,
                 pathurl: str) -> Path | None:
    """Add a music audio track to the FCP7 XML if the plan has music. Returns the music file path."""
    if not plan.music:
        return None
    music_path = _resolve(plan.music.file, base)
    if not music_path.is_file():
        return None
    from .probe import probe_duration
    fps, output_frames = plan.canvas.fps, plan.output_frames
    try:
        file_frames = max(1, round(probe_duration(music_path) * fps))
    except (OSError, subprocess.CalledProcessError, ValueError):
        file_frames = output_frames  # Older placeholder-media unit fixtures.

    base_db = plan.music.volume_db
    ramp_frames = max(1, round(0.3 * fps))
    points = [(0, base_db), (output_frames, base_db)]
    for duck in plan.music.duck:
        start, end = round(duck.start * fps), round(duck.end * fps)
        points.extend([(max(0, start - ramp_frames), base_db),
                       (start, duck.volume_db), (end, duck.volume_db),
                       (min(output_frames, end + ramp_frames), base_db)])
    points = sorted(dict(points).items())

    def level_at(frame: int) -> float:
        for left, right in zip(points, points[1:]):
            if left[0] <= frame <= right[0]:
                if left[0] == right[0]:
                    return float(right[1])
                ratio = (frame - left[0]) / (right[0] - left[0])
                return float(left[1]) + ratio * (float(right[1]) - float(left[1]))
        return float(points[-1][1])

    track = ET.SubElement(audio_parent, "track")
    position, index = 0, 0
    while position < output_frames:
        frames = min(file_frames, output_frames - position)
        param = _audio_clipitem(
            track, fps, clip_id="audio-music" if index == 0 else f"audio-music-{index}",
            file_id="music-file-1", label=f"Music · {music_path.name}",
            path=music_path, pathurl=pathurl, start=position, frames=frames,
            file_frames=file_frames, define_file=index == 0)
        _text(param, "value", level_at(position))
        if plan.music.duck:
            frames_to_write = {position, position + frames}
            frames_to_write.update(t for t, _ in points if position < t < position + frames)
            for frame in sorted(frames_to_write):
                _keyframe(param, frame - position, round(level_at(frame), 3))
        position += frames
        index += 1

    _text(track, "enabled", "TRUE")
    _text(track, "locked", "FALSE")
    return music_path


_SILENCE_DB = -60


def _linear_to_db(volume: float) -> float:
    return _SILENCE_DB if volume <= 0 else max(_SILENCE_DB, round(20 * math.log10(volume), 2))


def _attached_music_track(plan: EditPlan, audio_parent: ET.Element, attached: AttachedMusic,
                          pathurl: str) -> Path | None:
    """Add the attached background music as its own audio track.

    Mirrors the ffmpeg mix: the track is repeated until it covers the sequence,
    the volume is the mix volume, and the fades are Audio Levels keyframes (fade
    in on the first clip, fade out on the last).
    """
    from .probe import probe_duration
    path = Path(attached.file)
    if not path.is_file():
        return None
    fps, total = plan.canvas.fps, plan.output_frames
    music_frames = max(1, round(probe_duration(path) * fps))
    fade_in, fade_out = round(attached.fade_in * fps), round(attached.fade_out * fps)
    if fade_in + fade_out > total:  # same proportional shrink as brain.music
        scale = total / (fade_in + fade_out)
        fade_in, fade_out = int(fade_in * scale), int(fade_out * scale)
    base_db = _linear_to_db(attached.volume)

    track = ET.SubElement(audio_parent, "track")
    position, index = 0, 0
    while position < total:
        frames = min(music_frames, total - position)
        param = _audio_clipitem(
            track, fps, clip_id=f"audio-attached-music-{index}", file_id="attached-music-file-1",
            label=f"Background Music · {path.name}", path=path, pathurl=pathurl,
            start=position, frames=frames, file_frames=music_frames, define_file=index == 0)
        _text(param, "value", base_db)
        first, last = index == 0, position + frames >= total
        if first and fade_in > 0:
            fi = min(fade_in, frames)
            _keyframe(param, 0, _SILENCE_DB)
            _keyframe(param, fi, base_db)
        if last and fade_out > 0:
            fo = min(fade_out, frames)
            _keyframe(param, frames - fo, base_db)
            _keyframe(param, frames, _SILENCE_DB)
        position += frames
        index += 1
    _text(track, "enabled", "TRUE")
    _text(track, "locked", "FALSE")
    return path


def _sfx_tracks(plan: EditPlan, audio_parent: ET.Element, base: Path,
                pathurls: dict[Path, str]) -> list[Path]:
    """Serialize each narration/SFX cue on its own output-timeline audio track."""
    from .probe import probe_duration

    paths: list[Path] = []
    fps = plan.canvas.fps
    for index, sfx in enumerate(plan.sfx):
        path = _resolve(sfx.file, base)
        if not path.is_file():
            continue
        clip_duration = max(1, round(probe_duration(path) * fps))
        start = max(0, round(sfx.at * fps))
        duration = min(clip_duration, max(0, plan.output_frames - start))
        if duration <= 0:
            continue
        track = ET.SubElement(audio_parent, "track")
        clip = ET.SubElement(track, "clipitem", {"id": f"audio-sfx-{index}"})
        _text(clip, "name", f"Narration / SFX · {path.name}")
        _text(clip, "duration", duration)
        _rate(clip, fps)
        _text(clip, "start", start)
        _text(clip, "end", start + duration)
        _text(clip, "in", 0)
        _text(clip, "out", duration)
        file_node = ET.SubElement(clip, "file", {"id": f"sfx-file-{index}"})
        _text(file_node, "name", path.name)
        _text(file_node, "pathurl", pathurls[path.resolve()])
        _rate(file_node, fps)
        _text(file_node, "duration", clip_duration)
        media = ET.SubElement(file_node, "media")
        audio = ET.SubElement(media, "audio")
        sample = ET.SubElement(audio, "samplecharacteristics")
        _text(sample, "depth", 16)
        _text(sample, "samplerate", 48000)
        _text(audio, "channelcount", 2)
        source_track = ET.SubElement(clip, "sourcetrack")
        _text(source_track, "mediatype", "audio")
        _text(source_track, "trackindex", 1)
        volume_filter = ET.SubElement(clip, "filter")
        effect = ET.SubElement(volume_filter, "effect")
        _text(effect, "name", "Audio Levels")
        _text(effect, "effectid", "audiolevels")
        _text(effect, "effectcategory", "Audio")
        _text(effect, "effecttype", "audio")
        _text(effect, "mediatype", "audio")
        param = ET.SubElement(effect, "parameter", {"authoringApp": "PremierePro"})
        _text(param, "parameterid", "level")
        _text(param, "name", "Level")
        _text(param, "value", sfx.volume_db)
        _text(track, "enabled", "TRUE")
        _text(track, "locked", "FALSE")
        paths.append(path)
    return paths


def _broll_tracks(plan: EditPlan, video_parent: ET.Element, base: Path,
                  pathurls: dict[Path, str]) -> list[Path]:
    """Place B-roll on video tracks at its output-timeline position."""
    paths = []
    fps = plan.canvas.fps
    for index, item in enumerate(plan.broll):
        path = _resolve(item.file, base)
        if not path.is_file():
            raise FileNotFoundError(f"Premiere B-roll media is missing: {path}")
        start = round(item.at * fps)
        frames = round(item.duration * fps)
        source_in = round(item.in_ * fps)
        if frames <= 0 or start + frames > plan.output_frames:
            raise ValueError(f"Premiere B-roll timing is outside the sequence: {index}")
        track = ET.SubElement(video_parent, "track")
        clip = ET.SubElement(track, "clipitem", {"id": f"video-broll-{index}"})
        _text(clip, "name", f"B-roll · {path.name}")
        _text(clip, "duration", frames)
        _rate(clip, fps)
        for tag, value in (("start", start), ("end", start + frames),
                           ("in", source_in), ("out", source_in + frames)):
            _text(clip, tag, value)
        file_node = ET.SubElement(clip, "file", {"id": f"broll-file-{index}"})
        _text(file_node, "name", path.name)
        _text(file_node, "pathurl", pathurls[path.resolve()])
        _rate(file_node, fps)
        _text(file_node, "duration", source_in + frames)
        _text(track, "enabled", "TRUE")
        _text(track, "locked", "FALSE")
        paths.append(path)
    return paths


def build_premiere(plan: EditPlan, out_dir: Path, base_dir: Path | None = None,
                   attached_music: AttachedMusic | None = None) -> Path:
    """Write XML, SRT, report and zip bundle; return the bundle path.

    `attached_music` (the job's post-render background music) becomes an extra
    audio track next to any plan.music track."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = Path(base_dir) if base_dir else out_dir
    source = _resolve(plan.source, base)
    from .probe import has_audio
    try:
        source_has_audio = has_audio(source)
    except (OSError, subprocess.CalledProcessError, ValueError):
        # Old hand-authored plans and unit fixtures can use placeholder bytes.
        # The API validates real media before export.
        source_has_audio = True
    source_frames = max(round(max(segment.out for segment in plan.segments) * plan.canvas.fps), 1)

    bundled_media: dict[Path, str] = {}
    media_paths = [source]
    media_paths.extend(_resolve(item.file, base) for item in plan.broll)
    if plan.music:
        media_paths.append(_resolve(plan.music.file, base))
    media_paths.extend(_resolve(item.file, base) for item in plan.sfx)
    if attached_music is not None and Path(attached_music.file).is_file():
        media_paths.append(Path(attached_music.file))
    for path in media_paths:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Premiere media is missing: {resolved}")
        if resolved not in bundled_media:
            digest = _sha256(resolved)[:12]
            bundled_media[resolved] = PurePosixPath("media", f"{digest}-{resolved.name}").as_posix()

    root = ET.Element("xmeml", {"version": "5"})
    sequence = ET.SubElement(root, "sequence", {"id": "ai-render-sequence"})
    _text(sequence, "name", "AI Render editable sequence")
    _text(sequence, "duration", plan.output_frames)
    _rate(sequence, plan.canvas.fps)
    _text(sequence, "in", 0)
    _text(sequence, "out", plan.output_frames)
    media = ET.SubElement(sequence, "media")
    source_pathurl = bundled_media[source.resolve()]
    _track(plan, media, "video", source, source_frames, source_pathurl, source_has_audio)
    if source_has_audio:
        _track(plan, media, "audio", source, source_frames, source_pathurl, source_has_audio)
    else:
        ET.SubElement(media, "audio")
    broll_paths = _broll_tracks(plan, media.find("video"), base, bundled_media)

    # Find the <audio> element that _track just created for the main audio
    audio_container = media.find("audio")
    music_path = _music_track(
        plan, audio_container, base,
        bundled_media[_resolve(plan.music.file, base).resolve()] if plan.music else "",
    )
    attached_path = None
    if attached_music is not None and Path(attached_music.file).is_file():
        attached_path = _attached_music_track(
            plan, audio_container, attached_music, bundled_media[Path(attached_music.file).resolve()])
    sfx_paths = _sfx_tracks(plan, audio_container, base, bundled_media)

    xml_path = out_dir / PREMIERE_XML
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    xml_path.write_bytes(
        b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + b"\n"
    )

    srt_path = out_dir / PREMIERE_CAPTIONS
    _write_srt(plan, srt_path)
    identity = _artifact_identity(plan, out_dir)
    current_verification = _current_verification(plan, out_dir, identity)
    report_path = out_dir / PREMIERE_REPORT
    report = _report(plan, source, identity, current_verification,
                     source_reference=bundled_media[source.resolve()])
    validate_manifest(report)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Include cleaned audio if denoise is enabled.
    denoise_audio_path = None
    if plan.denoise and plan.denoise.get("enabled") and plan.denoise.get("audio_file"):
        candidate = _resolve(plan.denoise["audio_file"], base)
        if not candidate.is_file():
            raise FileNotFoundError(f"Premiere cleaned narration is missing: {candidate}")
        denoise_audio_path = candidate

    readme = (
        "AI Render Premiere Pro export\n\n"
        "1. Unzip this archive, keeping the media folder beside project_premiere.xml.\n"
        "2. In Premiere Pro, create a new project and choose File > Import, then select project_premiere.xml.\n"
        "3. Import premiere_captions.srt and place it on a Caption track.\n"
        "4. Inspect the editable sequence, audio tracks, and media links, then save the project as a .prproj file.\n\n"
        "AI Render supplies FCP7 XML interchange, not a native .prproj file. "
        "See premiere_transition_report.json for mappings and limitations.\n"
    )

    bundle = out_dir / PREMIERE_BUNDLE
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (xml_path, srt_path, report_path):
            archive.write(path, arcname=path.name)
        archive.writestr(PREMIERE_README, readme)
        for path in dict.fromkeys([source, *([music_path] if music_path else []),
                                   *([attached_path] if attached_path else []), *sfx_paths, *broll_paths]):
            archive.write(path, arcname=bundled_media[path.resolve()])
        if denoise_audio_path:
            archive.write(denoise_audio_path, arcname=denoise_audio_path.name)
    return bundle
