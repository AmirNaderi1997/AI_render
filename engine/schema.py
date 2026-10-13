"""Edit Plan v0.1 — Pydantic models."""
from __future__ import annotations
from pathlib import Path
import math
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CaptionStyle = Literal["normal", "emphasis", "cta", "cover"]


class Canvas(BaseModel):
    # The MP4 renderer uses H.264's default 4:2:0 pixel format, which requires
    # even dimensions. Reject invalid canvases during plan validation rather
    # than failing late inside melt/libx264.
    width: int = Field(ge=2, multiple_of=2)
    height: int = Field(ge=2, multiple_of=2)
    fps: int = Field(ge=1, le=120)
    caption_font: Optional[str] = None
    # Stable reference into the approved Font Library. ``caption_font`` remains
    # for legacy plans and is also retained as the resolved family for editors.
    caption_font_id: Optional[str] = None


class Zoom(BaseModel):
    from_: float = Field(alias="from", ge=1.0, le=1.5, allow_inf_nan=False)
    to: float = Field(ge=1.0, le=1.5, allow_inf_nan=False)

    model_config = {"populate_by_name": True}


class Segment(BaseModel):
    id: str
    in_: float = Field(alias="in", ge=0.0, allow_inf_nan=False)
    out: float = Field(ge=0.0, allow_inf_nan=False)
    zoom: Zoom = Zoom(**{"from": 1.0, "to": 1.0})

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _check(self):
        if self.out <= self.in_:
            raise ValueError(f"segment {self.id}: out ({self.out}) must be > in ({self.in_})")
        return self

    @property
    def duration(self) -> float:
        return self.out - self.in_


class VisualEffect(BaseModel):
    segment_id: str
    type: str
    # User-pinned choices survive regeneration and automatic QC patches.
    locked: bool = False

    @field_validator("type")
    @classmethod
    def _known_effect(cls, value: str) -> str:
        from .effects_v4 import EXTENDED_EFFECTS, UNSUPPORTED_EFFECTS, is_renderable_effect
        if value in EXTENDED_EFFECTS:
            if not is_renderable_effect(value):
                raise ValueError(f"effect {value!r} cannot be rendered: {UNSUPPORTED_EFFECTS[value]}")
            return value
        from .effects import canonical_effect
        return canonical_effect(value)


TransitionType = Literal["hard_cut", "crossfade", "directional", "zoom"]
TransitionDirection = Literal["left", "right", "up", "down"]
ZoomTransitionMode = Literal["zoom_in", "zoom_out"]


class TransitionContext(BaseModel):
    output_kind: Literal["reel", "story", "post"] = "reel"
    style: Optional[Literal["auto", "none", "crossfade", "directional", "zoom"]] = None
    request: str = ""


class BoundaryTransition(BaseModel):
    """A frame-accurate overlap between two adjacent output segments.

    ``duration_frames`` is zero for a hard cut. For rendered transitions it is
    the number of shared output frames: the incoming segment starts that many
    frames before the outgoing segment ends, so the output is shortened by the
    same number of frames. ``direction`` and ``intensity`` are used only by the
    directional transition. Manual choices are persisted with ``locked=True``.
    """

    from_segment_id: str
    to_segment_id: str
    type: TransitionType = "hard_cut"
    duration_frames: int = Field(default=0, ge=0, le=30)
    direction: TransitionDirection = "left"
    intensity: float = Field(default=1.0, ge=0.5, le=1.0, allow_inf_nan=False)
    # Boundary zoom is intentionally distinct from Segment.zoom/VisualEffect.
    zoom_mode: ZoomTransitionMode = "zoom_in"
    zoom_scale: float = Field(default=1.15, ge=1.02, le=1.5, allow_inf_nan=False)
    source: Literal["default", "planner", "manual"] = "default"
    locked: bool = False

    @model_validator(mode="after")
    def _timing_matches_type(self):
        if self.type == "hard_cut" and self.duration_frames != 0:
            raise ValueError("hard_cut duration_frames must be 0")
        if self.type != "hard_cut" and self.duration_frames < 2:
            raise ValueError("rendered transitions require at least 2 frames")
        if self.source == "manual" and not self.locked:
            raise ValueError("manual transitions must be locked")
        return self



class Caption(BaseModel):
    start: float = Field(ge=0.0, allow_inf_nan=False)
    end: float = Field(ge=0.0, allow_inf_nan=False)
    text: str
    style: CaptionStyle = "normal"
    position: Literal["bottom", "top"] = "bottom"
    # A single exact word or short phrase from the caption to accent in the
    # rich subtitle renderer. None keeps the caption as a single colour.
    highlighted_word: Optional[str] = None
    locked: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError(f"caption {self.text!r}: end must be > start")
        return self

    @field_validator("text")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("caption text must not be empty")
        return value

    @field_validator("highlighted_word")
    @classmethod
    def _valid_highlight(cls, value: Optional[str], info):
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        return value

    @model_validator(mode="after")
    def _highlight_is_in_caption(self):
        if self.highlighted_word and self.highlighted_word not in self.text:
            raise ValueError("highlighted_word must appear exactly in caption text")
        return self


class Cover(BaseModel):
    """Opening-title text selected from an existing transcript caption."""

    text: str = Field(min_length=1)
    start: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    end: float = Field(default=2.5, gt=0.0, allow_inf_nan=False)
    source_caption_index: Optional[int] = Field(default=None, ge=0)
    source_segment_id: Optional[str] = None
    reason: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError("cover end must be > start")
        return self


class Poster(BaseModel):
    """Text burned onto the still image shown before the video plays."""

    text: str = Field(min_length=1)
    frame_time: float = Field(default=1.0, ge=0.0, allow_inf_nan=False)
    source_caption_index: Optional[int] = Field(default=None, ge=0)
    rating_version: int = Field(default=0, ge=0)
    reason: Optional[str] = None
    # A selected hook can also remain visible in vertical video. Editors may
    # turn this off for footage where it would cover important content.
    show_in_video: bool = True


class Broll(BaseModel):
    at: float = Field(ge=0.0, allow_inf_nan=False)
    duration: float = Field(gt=0.0, allow_inf_nan=False)
    file: str = Field(min_length=1)
    in_: float = Field(alias="in", default=0.0, ge=0.0, allow_inf_nan=False)
    query: Optional[str] = None

    model_config = {"populate_by_name": True}


class DuckRange(BaseModel):
    start: float = Field(ge=0.0, allow_inf_nan=False)
    end: float = Field(ge=0.0, allow_inf_nan=False)
    volume_db: float = Field(ge=-80.0, le=12.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError("duck range: end must be > start")
        return self


class Music(BaseModel):
    file: str = Field(min_length=1)
    volume_db: float = Field(default=-14, ge=-80.0, le=12.0, allow_inf_nan=False)
    duck: List[DuckRange] = []
    locked: bool = False


class Sfx(BaseModel):
    at: float = Field(ge=0.0, allow_inf_nan=False)
    file: str = Field(min_length=1)
    volume_db: float = Field(default=-3, ge=-80.0, le=12.0, allow_inf_nan=False)


class Export(BaseModel):
    file: str = Field(min_length=1)
    crf: int = Field(default=20, ge=0, le=51)


class EditPlan(BaseModel):
    version: str = "0.1"
    style: str = "rafiei_reel"
    canvas: Canvas
    source: str
    segments: List[Segment]
    visual_effects: List[VisualEffect] = []
    # Optional for backwards compatibility. Absence means legacy hard cuts.
    transitions: List[BoundaryTransition] = []
    # Present on newly generated plans; omitted for older hand-authored plans.
    transition_context: Optional[TransitionContext] = None
    cover: Optional[Cover] = None
    poster: Optional[Poster] = None
    captions: List[Caption] = []
    broll: List[Broll] = []
    music: Optional[Music] = None
    sfx: List[Sfx] = []
    denoise: Optional[dict] = None
    export: Export
    content_type: Optional[str] = None
    source_type: Optional[str] = None
    generation_meta: Optional[dict] = None

    @field_validator("segments")
    @classmethod
    def _segments_nonempty(cls, v):
        if not v:
            raise ValueError("segments must be non-empty")
        return v

    @model_validator(mode="after")
    def _effects_match_segments(self):
        ids = [s.id for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment ids must be unique")
        effect_ids = [e.segment_id for e in self.visual_effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise ValueError("one visual effect per segment is allowed")
        unknown = set(effect_ids) - set(ids)
        if unknown:
            raise ValueError(f"visual effect references unknown segments: {sorted(unknown)}")
        if self.cover and self.cover.source_segment_id and self.cover.source_segment_id not in ids:
            raise ValueError(f"cover references unknown segment: {self.cover.source_segment_id}")
        boundaries = {(self.segments[i].id, self.segments[i + 1].id): i
                      for i in range(len(self.segments) - 1)}
        seen: set[tuple[str, str]] = set()
        overlap_by_segment = {segment.id: 0 for segment in self.segments}
        for transition in self.transitions:
            pair = (transition.from_segment_id, transition.to_segment_id)
            if pair not in boundaries:
                raise ValueError(
                    "transition must reference adjacent segments in output order: "
                    f"{transition.from_segment_id} -> {transition.to_segment_id}"
                )
            if pair in seen:
                raise ValueError(f"one transition per boundary is allowed: {pair[0]} -> {pair[1]}")
            seen.add(pair)
            overlap_by_segment[pair[0]] += transition.duration_frames
            overlap_by_segment[pair[1]] += transition.duration_frames
        fps = self.canvas.fps
        if self.transition_context:
            frame_cap = {"reel": 12, "story": 10, "post": 8}[self.transition_context.output_kind]
            for transition in self.transitions:
                if transition.duration_frames > frame_cap:
                    raise ValueError(
                        f"transition duration exceeds {frame_cap}-frame "
                        f"{self.transition_context.output_kind} cap"
                    )
        for segment in self.segments:
            frames = round(segment.duration * fps)
            if frames < 1:
                raise ValueError(f"segment {segment.id} is shorter than one output frame")
            if overlap_by_segment[segment.id] >= frames:
                raise ValueError(
                    f"transition overlaps consume all frames of segment {segment.id}: "
                    f"{overlap_by_segment[segment.id]} >= {frames}"
                )
        return self

    @property
    def output_duration(self) -> float:
        frames = sum(round(s.duration * self.canvas.fps) for s in self.segments)
        frames -= sum(t.duration_frames for t in self.transitions)
        return frames / self.canvas.fps

    @property
    def output_frames(self) -> int:
        return round(self.output_duration * self.canvas.fps)


# Alias for callers preferring the shorter name.
Plan = EditPlan


def format_error(exc: ValidationError) -> List[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append(f"{loc}: {err['msg']}")
    return out


def validate_plan(data: dict, base_dir: Optional[Path] = None, check_media: bool = True) -> tuple[Optional[EditPlan], List[str]]:
    """Validate a plan dict. Returns (plan, errors). Runs media/duration checks if check_media."""
    try:
        plan = EditPlan(**data)
    except ValidationError as e:
        return None, format_error(e)

    errors: List[str] = []
    if plan.canvas.caption_font_id:
        try:
            from .font_library import resolve_font
            resolve_font(plan.canvas.caption_font_id)
        except Exception as e:
            errors.append(f"canvas.caption_font_id: {e}")
    base = Path(base_dir) if base_dir else Path.cwd()

    def resolve(p: str) -> Path:
        pp = Path(p)
        return pp if pp.is_absolute() else (base / pp)

    if check_media:
        from .probe import probe

        files = [("source", plan.source)]
        if plan.denoise and plan.denoise.get("enabled") and plan.denoise.get("audio_file"):
            files.append(("denoise.audio_file", plan.denoise["audio_file"]))
        for i, b in enumerate(plan.broll):
            if not b.query:
                files.append((f"broll[{i}].file", b.file))
        if plan.music:
            files.append(("music.file", plan.music.file))
        for i, s in enumerate(plan.sfx):
            files.append((f"sfx[{i}].file", s.file))

        for path_field, rel in files:
            ap = resolve(rel)
            if not ap.exists():
                errors.append(f"{path_field}: file not found: {ap}")

        # source duration check
        if not any(e.startswith("source:") for e in errors):
            try:
                source_path = resolve(plan.source)
                source_info = probe(source_path)
                if not any(stream.get("codec_type") == "video"
                           for stream in source_info.get("streams", [])):
                    errors.append("source: file contains no video stream")
                src_dur = float(source_info.get("format", {}).get("duration", 0))
                if not math.isfinite(src_dur) or src_dur <= 0:
                    errors.append("source: file has no positive duration")
                for i, seg in enumerate(plan.segments):
                    if seg.out > src_dur + 1e-3:
                        errors.append(f"segments[{i}].out ({seg.out}) exceeds source duration ({src_dur:.3f}s)")
            except Exception as e:
                errors.append(f"source: could not probe duration: {e}")

        # Existing music, SFX, and B-roll must contain the stream their MLT
        # producer needs. File existence alone only defers decoder failures to
        # the background render worker, where the user gets a late generic error.
        for path_field, rel in files[1:]:
            media_path = resolve(rel)
            if not media_path.is_file():
                continue
            try:
                streams = probe(media_path).get("streams", [])
                expected = "video" if path_field.startswith("broll[") else "audio"
                if not any(stream.get("codec_type") == expected for stream in streams):
                    errors.append(f"{path_field}: file contains no {expected} stream")
                elif path_field.startswith("broll["):
                    try:
                        broll_index = int(path_field[len("broll["):].split("]", 1)[0])
                        broll = plan.broll[broll_index]
                        asset_duration = float(probe(media_path).get("format", {}).get("duration", 0))
                        if not math.isfinite(asset_duration) or asset_duration <= 0:
                            errors.append(f"{path_field}: file has no positive duration")
                        elif broll.in_ + broll.duration > asset_duration + 1e-3:
                            errors.append(
                                f"{path_field}: in+duration ({broll.in_ + broll.duration:.3f}s) "
                                f"exceeds asset duration ({asset_duration:.3f}s)"
                            )
                    except Exception as e:
                        errors.append(f"{path_field}: could not probe duration: {e}")
            except Exception as e:
                errors.append(f"{path_field}: could not probe media: {e}")

    # output-timeline bounds
    out_dur = plan.output_duration
    for i, c in enumerate(plan.captions):
        if c.end > out_dur + 1e-3:
            errors.append(f"captions[{i}].end ({c.end}) exceeds output duration ({out_dur:.3f}s)")
    if plan.cover and plan.cover.end > out_dur + 1e-3:
        errors.append(f"cover.end ({plan.cover.end}) exceeds output duration ({out_dur:.3f}s)")
    if plan.poster and plan.poster.frame_time >= out_dur:
        errors.append(f"poster.frame_time ({plan.poster.frame_time}) exceeds output duration ({out_dur:.3f}s)")
    for i, b in enumerate(plan.broll):
        if b.at + b.duration > out_dur + 1e-3:
            errors.append(f"broll[{i}]: at+duration ({b.at + b.duration}) exceeds output duration ({out_dur:.3f}s)")
    for i, s in enumerate(plan.sfx):
        if s.at > out_dur + 1e-3:
            errors.append(f"sfx[{i}].at ({s.at}) exceeds output duration ({out_dur:.3f}s)")
        elif s.at >= out_dur:
            errors.append(f"sfx[{i}].at ({s.at}) is at or beyond output duration ({out_dur:.3f}s)")
    if plan.music:
        for i, d in enumerate(plan.music.duck):
            if d.end > out_dur + 1e-3:
                errors.append(f"music.duck[{i}].end ({d.end}) exceeds output duration ({out_dur:.3f}s)")

    return (plan if not errors else None), errors
