"""Reviewable, provenance-preserving visual style profiles.

Library records live below jobs/ so they persist with the local app while staying
out of source control. Drafts never affect planning until explicitly approved
and selected for a job.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .captions import load_style
from .schema import PROJECT_ROOT

ROOT = PROJECT_ROOT / "jobs" / "style-library"
DRAFTS = ROOT / "drafts"
PROFILES = ROOT / "profiles"
ASSETS = ROOT / "assets"
for _path in (DRAFTS, PROFILES, ASSETS):
    _path.mkdir(parents=True, exist_ok=True)

ALLOWED_TOP = {"learned"}


def _id() -> str:
    return uuid.uuid4().hex[:16]


def _safe_name(value: str) -> str:
    name = re.sub(r"[^\w .-]+", "", value, flags=re.UNICODE).strip(" .-")
    return name[:80] or "Learned style"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_style(style: Any) -> dict:
    if not isinstance(style, dict) or not style:
        raise ValueError("style file must contain a non-empty YAML or JSON mapping")
    unknown = set(style) - (set(load_style("rafiei_reel")) | ALLOWED_TOP)
    if unknown:
        raise ValueError("unsupported style sections: " + ", ".join(sorted(unknown)))
    # Merge into the current canonical preset so partial, older style files stay usable.
    merged = _deep_merge(load_style("rafiei_reel"), style)
    captions = merged.get("captions", {})
    if not isinstance(captions, dict):
        raise ValueError("captions must be a mapping")
    if not isinstance(captions.get("base", {}), dict):
        raise ValueError("captions.base must be a mapping")
    styles = captions.get("styles", {})
    if not isinstance(styles, dict):
        raise ValueError("captions.styles must be a mapping")
    numeric_ranges = {
        "size": (1, 512), "outline": (0, 64), "shadow": (0, 128),
        "margin_sides": (0, 540), "margin_bottom": (0, 1920), "weight": (100, 900),
        "primary_size": (1, 512), "primary_y": (0, 1920), "primary_height": (1, 1920),
        "accent_size": (1, 512), "accent_y": (0, 1920), "accent_height": (1, 1920),
        "split_min_words": (1, 20),
    }

    def finite_number(value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            return math.isfinite(float(value))
        except (OverflowError, ValueError):
            return False

    groups = [("captions.base", captions.get("base", {}))]
    groups.extend((f"captions.styles.{name}", value) for name, value in styles.items())
    for group_name, group in groups:
        if not isinstance(group, dict):
            raise ValueError("caption styles must be mappings")
        for key in ("colour", "outline_colour", "background_colour", "primary_colour", "accent_colour"):
            if key in group and not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", str(group[key])):
                raise ValueError(f"{group_name}.{key} must be a #RRGGBB or #RRGGBBAA colour")
        for key, (minimum, maximum) in numeric_ranges.items():
            if key not in group:
                continue
            value = group[key]
            if not finite_number(value) or not minimum <= value <= maximum:
                raise ValueError(f"{group_name}.{key} must be a finite number from {minimum} to {maximum}")
        for key in ("font", "font_style"):
            if key in group and (not isinstance(group[key], str) or not group[key].strip()):
                raise ValueError(f"{group_name}.{key} must be a non-empty string")
        for key in ("bold", "enabled"):
            if key in group and not isinstance(group[key], bool):
                raise ValueError(f"{group_name}.{key} must be a boolean")

    render = merged.get("render", {})
    if not isinstance(render, dict):
        raise ValueError("render must be a mapping")
    for key in ("crf", "preview_crf"):
        if key in render:
            value = render[key]
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 51:
                raise ValueError(f"render.{key} must be an integer from 0 to 51")
    if "preview_scale" in render:
        value = render["preview_scale"]
        if not finite_number(value) or not 0.1 <= value <= 1.0:
            raise ValueError("render.preview_scale must be a finite number from 0.1 to 1.0")
    if "loudness_lufs" in render:
        value = render["loudness_lufs"]
        if not finite_number(value) or not -70 <= value <= 0:
            raise ValueError("render.loudness_lufs must be a finite number from -70 to 0")
    presets = {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
               "slow", "slower", "veryslow", "placebo"}
    if "preset" in render and (not isinstance(render["preset"], str) or render["preset"] not in presets):
        raise ValueError("render.preset is not a supported H.264 preset")
    if "audio_bitrate" in render and (not isinstance(render["audio_bitrate"], str)
            or not re.fullmatch(r"[1-9]\d{0,3}[kKmM]", render["audio_bitrate"])):
        raise ValueError("render.audio_bitrate must look like 192k or 1M")
    if "canvas" in style and not isinstance(style["canvas"], dict):
        raise ValueError("canvas must be a mapping")
    return merged


def _deep_merge(left: dict, right: dict) -> dict:
    result = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _draft(name: str, source: dict, profile: dict, evidence: list[dict]) -> dict:
    draft = {
        "id": _id(), "style_id": None, "name": _safe_name(name), "state": "draft",
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "source": source, "evidence": evidence, "profile": profile,
    }
    draft["style_id"] = draft["id"]
    _json(DRAFTS / f"{draft['id']}.json", draft)
    return draft


def _palette(image: Any) -> list[str]:
    colors = image.convert("RGB").resize((96, 96)).quantize(colors=6).convert("RGB")
    return ["#%02X%02X%02X" % tuple(color) for _, color in colors.getcolors(96 * 96)[:6]]


def import_snapshots(files: list[tuple[str, bytes]], name: str = "Snapshot style") -> dict:
    try:
        from PIL import Image, ImageFilter, ImageStat
        from io import BytesIO
    except ImportError as exc:
        raise RuntimeError("Pillow is required for snapshot analysis") from exc
    if not files:
        raise ValueError("upload at least one snapshot")
    evidences, palettes, dimensions, visual_clues = [], [], [], []
    hashes = []
    for filename, data in files[:20]:
        try:
            image = Image.open(BytesIO(data)).convert("RGB")
        except Exception as exc:
            raise ValueError(f"invalid image {filename!r}") from exc
        digest = _sha(data); hashes.append(digest)
        asset = ASSETS / f"{digest[:20]}.jpg"
        image.save(asset, quality=92)
        palettes.extend(_palette(image)); dimensions.append(image.size)
        edge = image.convert("L").filter(ImageFilter.FIND_EDGES)
        bands = [edge.crop((0, int(image.height * y0), image.width, int(image.height * y1)))
                 for y0, y1 in ((.55, .70), (.70, .85), (.85, 1.0))]
        edge_scores = [sum(ImageStat.Stat(band).mean) / 255 for band in bands]
        likely_band = max(range(len(edge_scores)), key=edge_scores.__getitem__)
        visual_clues.append({"caption_band_candidate": [0.55, 0.70, 0.85][likely_band],
                             "edge_density_by_lower_band": [round(score, 3) for score in edge_scores],
                             "method": "image edge density heuristic; requires visual confirmation"})
        evidences.append({"kind": "snapshot", "asset": asset.name, "source_name": Path(filename).name,
                          "sha256": digest, "supports": ["palette", "framing", "caption_layout", "typography_clues"]})
    palette = [color for color, _ in Counter(palettes).most_common(8)]
    ratios = [w / h for w, h in dimensions]
    ratio = sum(ratios) / len(ratios)
    profile = {"learned": {"palette": palette, "framing": {"observed_aspect_ratio": round(ratio, 3),
               "image_count": len(dimensions)}, "caption_layout": {
                   "status": "heuristic_candidate", "candidate_region_y_fraction": round(
                       sum(v["caption_band_candidate"] for v in visual_clues) / len(visual_clues), 3),
                   "basis": "lower-image edge density; requires visual confirmation"},
               "typography_clues": {"status": "heuristic_candidate", "font_identity": "unknown",
                                    "candidates": visual_clues},
               "timing": {"status": "unknown", "value": None},
               "motion": {"status": "unknown", "value": None}}}
    return _draft(name, {"type": "snapshots", "sha256": hashes}, profile, evidences)


def import_reference_video(filename: str, data: bytes, name: str = "Video reference") -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
        raise ValueError("unsupported reference video type")
    digest = _sha(data); video = ASSETS / f"reference-{digest[:20]}{suffix}"
    video.write_bytes(data)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                            "-of", "json", str(video)], capture_output=True, text=True, timeout=30)
    if probe.returncode:
        video.unlink(missing_ok=True)
        raise ValueError("could not read reference video")
    info = json.loads(probe.stdout); duration = float(info.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise ValueError("reference video has no duration")
    step = max(0.5, duration / 24)
    marks = sorted(set([round(i * step, 3) for i in range(int(duration / step) + 1)] + [max(0, duration - .05)]))[:25]
    evidences = []
    previous = None; cuts = []; motion_diffs = []
    try:
        from PIL import Image, ImageChops, ImageStat
        from io import BytesIO
    except ImportError as exc:
        raise RuntimeError("Pillow is required for reference analysis") from exc
    palettes = []
    for i, seconds in enumerate(marks):
        image_proc = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(video), "-frames:v", "1",
                                     "-vf", "scale=320:-1", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                                    capture_output=True, timeout=30)
        if image_proc.returncode or not image_proc.stdout:
            continue
        image = Image.open(BytesIO(image_proc.stdout)).convert("RGB")
        frame_path = ASSETS / f"{digest[:12]}-frame-{i}.jpg"; image.save(frame_path, quality=90)
        palettes.extend(_palette(image))
        diff = None
        if previous is not None:
            diff = round(sum(ImageStat.Stat(ImageChops.difference(previous, image)).mean) / 3 / 255, 4)
            motion_diffs.append(diff)
            if diff > .28: cuts.append(round(seconds, 2))
        evidences.append({"kind": "video_frame", "asset": frame_path.name, "at_seconds": round(seconds, 3),
                          "source_range": [round(max(0, seconds - .5), 3), round(min(duration, seconds + .5), 3)],
                          "supports": ["palette", "framing", "caption_treatment"], "frame_difference": diff})
        previous = image
    if not evidences:
        raise ValueError("no reference frames could be sampled")
    streams = info.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_info = {"status": "no_audio_stream", "mean_volume_db": None, "max_volume_db": None}
    if any(s.get("codec_type") == "audio" for s in streams):
        audio_proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vn", "-af", "volumedetect",
                                     "-f", "null", "-"], capture_output=True, text=True, timeout=60)
        log = audio_proc.stderr
        mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", log)
        peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", log)
        audio_info = {"status": "measured" if audio_proc.returncode == 0 else "analysis_failed",
                      "mean_volume_db": float(mean.group(1)) if mean else None,
                      "max_volume_db": float(peak.group(1)) if peak else None}
        evidences.append({"kind": "audio_measurement", "source_range": [0, round(duration, 3)],
                          "supports": ["audio_level_characteristics"], "measurement": audio_info})
    profile = {"learned": {"palette": [c for c, _ in Counter(palettes).most_common(8)],
               "framing": {"width": video_stream.get("width"), "height": video_stream.get("height")},
               "timing": {"status": "observed_samples", "sample_times": marks, "candidate_cut_changes": cuts},
               "motion": {"status": "observed_samples", "mean_frame_difference": round(sum(motion_diffs)/len(motion_diffs), 4) if motion_diffs else None},
               "transitions": {"status": "candidate_cut_changes", "ranges": cuts},
               "caption_treatment": {"status": "visual_review_required"},
               "audio": audio_info}}
    return _draft(name, {"type": "reference_video", "asset": video.name, "sha256": digest,
                         "duration_seconds": duration}, profile, evidences)


def import_style_file(filename: str, data: bytes, name: str | None = None) -> dict:
    if len(data) > 2_000_000:
        raise ValueError("style file must be at most 2 MB")
    try:
        parsed = yaml.safe_load(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError("style file must be valid UTF-8 YAML or JSON") from exc
    profile = _validate_style(parsed)
    digest = _sha(data)
    return _draft(name or Path(filename).stem, {"type": "style_file", "source_name": Path(filename).name,
                                                "sha256": digest, "original": parsed}, profile,
                  [{"kind": "style_file", "sha256": digest, "supports": ["all profile fields"]}])


def list_library() -> dict:
    drafts = [json.loads(p.read_text()) for p in sorted(DRAFTS.glob("*.json"))]
    profiles = [json.loads(p.read_text()) for p in sorted(PROFILES.glob("*.json"))]
    return {"drafts": drafts, "profiles": profiles}


def get_draft(draft_id: str) -> dict:
    path = DRAFTS / f"{draft_id}.json"
    if not path.is_file(): raise KeyError(draft_id)
    return json.loads(path.read_text())


def remove_draft(draft_id: str) -> dict:
    draft = get_draft(draft_id)
    if draft.get("state") != "draft":
        raise ValueError("approved style drafts are retained as provenance")
    (DRAFTS / f"{draft_id}.json").unlink()
    return {"ok": True, "id": draft_id, "state": "deleted"}


def update_draft(draft_id: str, body: dict) -> dict:
    draft = get_draft(draft_id)
    if draft.get("state") != "draft": raise ValueError("approved profile drafts are immutable")
    draft["name"] = _safe_name(str(body.get("name", draft["name"])))
    profile = body.get("profile", draft["profile"])
    if not isinstance(profile, dict): raise ValueError("profile must be a mapping")
    # Validate renderer fields while retaining analysis-only observations.
    learned = profile.get("learned")
    renderer = {k: v for k, v in profile.items() if k != "learned"}
    draft["profile"] = {**(_validate_style(renderer) if renderer else load_style("rafiei_reel")),
                         **({"learned": learned} if learned is not None else {})}
    _json(DRAFTS / f"{draft_id}.json", draft)
    return draft


def approve_draft(draft_id: str) -> dict:
    draft = get_draft(draft_id)
    profile = draft["profile"]
    learned = profile.get("learned")
    renderer = {k: v for k, v in profile.items() if k != "learned"}
    draft["profile"] = {**(_validate_style(renderer) if renderer else load_style("rafiei_reel")),
                         **({"learned": learned} if learned is not None else {})}
    style_id = draft.get("style_id") or draft_id
    profile_paths = list(PROFILES.glob("*.json")) + list((ROOT / "archive" / "profiles").glob("*.json"))
    siblings = [json.loads(p.read_text()) for p in profile_paths
                if json.loads(p.read_text()).get("style_id") == style_id]
    version = max([int(p.get("version", 0)) for p in siblings] + [0]) + 1
    approved = {"style_id": style_id, "version": version, "name": draft["name"], "state": "approved",
                "approved_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                "source": draft["source"], "evidence": draft["evidence"], "profile": draft["profile"]}
    _json(PROFILES / f"{style_id}-v{version}.json", approved)
    draft["state"] = "approved"; draft["approved_version"] = version
    _json(DRAFTS / f"{draft_id}.json", draft)
    return approved


def fork_profile(style_id: str, version: int) -> dict:
    approved = get_profile(style_id, version)
    draft = _draft(approved["name"], approved["source"], approved["profile"], approved["evidence"])
    draft["style_id"] = style_id
    _json(DRAFTS / f"{draft['id']}.json", draft)
    return draft


def get_profile(style_id: str, version: int) -> dict:
    path = PROFILES / f"{style_id}-v{version}.json"
    if not path.is_file():
        # Removed profiles stay available to jobs that pinned an immutable
        # version before it was removed from the active library.
        path = ROOT / "archive" / "profiles" / f"{style_id}-v{version}.json"
    if not path.is_file(): raise KeyError(style_id)
    return json.loads(path.read_text())


def remove_profile(style_id: str, version: int) -> dict:
    path = PROFILES / f"{style_id}-v{version}.json"
    if not path.is_file():
        raise KeyError(style_id)
    archive = ROOT / "archive" / "profiles"
    archive.mkdir(parents=True, exist_ok=True)
    destination = archive / path.name
    os.replace(path, destination)
    return {"ok": True, "style_id": style_id, "version": version, "state": "archived"}


def resolve_preset(style_id: str, version: int) -> dict:
    profile = get_profile(style_id, version)
    base = load_style("rafiei_reel")
    # Learned analysis metadata is not renderer configuration.
    render_profile = {k: v for k, v in profile["profile"].items() if k in set(base)}
    return _deep_merge(base, render_profile)


def evidence_path(asset: str) -> Path:
    path = (ASSETS / Path(asset).name).resolve()
    if path.parent != ASSETS.resolve() or not path.is_file(): raise KeyError(asset)
    return path
