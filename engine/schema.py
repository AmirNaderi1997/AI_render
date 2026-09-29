"""Edit Plan v0.1 — Pydantic models."""
from __future__ import annotations
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CaptionStyle = Literal["normal", "emphasis", "cta"]


class Canvas(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)


class Zoom(BaseModel):
    from_: float = Field(alias="from", ge=1.0, le=1.5)
    to: float = Field(ge=1.0, le=1.5)

    model_config = {"populate_by_name": True}


class Segment(BaseModel):
    id: str
    in_: float = Field(alias="in", ge=0.0)
    out: float = Field(ge=0.0)
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


class Caption(BaseModel):
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str
    style: CaptionStyle = "normal"

    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError(f"caption {self.text!r}: end must be > start")
        return self


class Broll(BaseModel):
    at: float = Field(ge=0.0)
    duration: float = Field(gt=0.0)
    file: str
    in_: float = Field(alias="in", default=0.0, ge=0.0)

    model_config = {"populate_by_name": True}


class DuckRange(BaseModel):
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    volume_db: float

    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError("duck range: end must be > start")
        return self


class Music(BaseModel):
    file: str
    volume_db: float = -14
    duck: List[DuckRange] = []


class Sfx(BaseModel):
    at: float = Field(ge=0.0)
    file: str
    volume_db: float = -3


class Export(BaseModel):
    file: str
    crf: int = Field(default=20, ge=0, le=51)


class EditPlan(BaseModel):
    version: str = "0.1"
    style: str = "rafiei_reel"
    canvas: Canvas
    source: str
    segments: List[Segment]
    captions: List[Caption] = []
    broll: List[Broll] = []
    music: Optional[Music] = None
    sfx: List[Sfx] = []
    export: Export

    @field_validator("segments")
    @classmethod
    def _segments_nonempty(cls, v):
        if not v:
            raise ValueError("segments must be non-empty")
        return v

    @property
    def output_duration(self) -> float:
        return sum(s.duration for s in self.segments)


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
    base = Path(base_dir) if base_dir else Path.cwd()

    def resolve(p: str) -> Path:
        pp = Path(p)
        return pp if pp.is_absolute() else (base / pp)

    if check_media:
        from .probe import probe_duration

        files = [("source", plan.source)]
        for i, b in enumerate(plan.broll):
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
                src_dur = probe_duration(resolve(plan.source))
                for i, seg in enumerate(plan.segments):
                    if seg.out > src_dur + 1e-3:
                        errors.append(f"segments[{i}].out ({seg.out}) exceeds source duration ({src_dur:.3f}s)")
            except Exception as e:
                errors.append(f"source: could not probe duration: {e}")

    # output-timeline bounds
    out_dur = plan.output_duration
    for i, c in enumerate(plan.captions):
        if c.end > out_dur + 1e-3:
            errors.append(f"captions[{i}].end ({c.end}) exceeds output duration ({out_dur:.3f}s)")
    for i, b in enumerate(plan.broll):
        if b.at + b.duration > out_dur + 1e-3:
            errors.append(f"broll[{i}]: at+duration ({b.at + b.duration}) exceeds output duration ({out_dur:.3f}s)")
    for i, s in enumerate(plan.sfx):
        if s.at > out_dur + 1e-3:
            errors.append(f"sfx[{i}].at ({s.at}) exceeds output duration ({out_dur:.3f}s)")
    if plan.music:
        for i, d in enumerate(plan.music.duck):
            if d.end > out_dur + 1e-3:
                errors.append(f"music.duck[{i}].end ({d.end}) exceeds output duration ({out_dur:.3f}s)")

    return (plan if not errors else None), errors
