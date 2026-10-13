"""Typed, validated edit operations on an EditPlan dict.

Every change to a plan — from the UI, a chat assistant, or QC — is expressed as
an ``EditOperation``. Each operation is a small Pydantic model whose ``apply``
returns a new plan dict; ``apply_operations`` runs a batch atomically (any
error leaves the input untouched) and can return a diff instead of committing.

Times on operations are output-timeline seconds unless a field says otherwise.
Segment output spans are computed frame-accurately, including transition
overlaps, the same way ``engine.build_mlt`` lays out clips.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from .schema import validate_plan

Actor = Literal["user", "ai"]
FRAME_EPS = 1e-6


class OperationError(ValueError):
    """An operation could not be applied; ``index`` is its batch position."""

    def __init__(self, message: str, index: Optional[int] = None):
        super().__init__(message)
        self.index = index


class LockedError(OperationError):
    """The operation would change an item the user locked."""


@dataclass
class OpContext:
    """Who is applying operations and whether locked items are protected.

    Locks protect user choices from automatic edits (AI generation, chat, QC).
    A direct user edit may change a locked item.
    """

    actor: Actor = "user"
    respect_locks: bool = False


# ---------------------------------------------------------------------------
# Output-timeline helpers
# ---------------------------------------------------------------------------

@dataclass
class SegmentSpan:
    index: int
    id: str
    start: float          # output seconds
    end: float            # output seconds (exclusive)
    source_in: float
    source_out: float


def _fps(plan: dict) -> int:
    return int((plan.get("canvas") or {}).get("fps", 30))


def segment_spans(plan: dict) -> list[SegmentSpan]:
    """Output-time span of each segment, honoring transition overlaps."""
    fps = _fps(plan)
    segments = plan.get("segments") or []
    overlaps = {(t["from_segment_id"], t["to_segment_id"]): int(t.get("duration_frames", 0))
                for t in plan.get("transitions") or []}
    spans, cursor = [], 0
    for i, seg in enumerate(segments):
        frames = round((seg["out"] - seg["in"]) * fps)
        spans.append(SegmentSpan(i, seg["id"], cursor / fps, (cursor + frames) / fps, seg["in"], seg["out"]))
        cursor += frames
        if i < len(segments) - 1:
            cursor -= overlaps.get((seg["id"], segments[i + 1]["id"]), 0)
    return spans


def output_duration(plan: dict) -> float:
    spans = segment_spans(plan)
    return spans[-1].end if spans else 0.0


def segments_in_range(plan: dict, t_start: float, t_end: float) -> list[SegmentSpan]:
    """Segments whose output span overlaps [t_start, t_end) by more than a frame."""
    min_overlap = 1.0 / _fps(plan) - FRAME_EPS
    return [s for s in segment_spans(plan)
            if min(s.end, t_end) - max(s.start, t_start) >= min_overlap]


def _overlaps(start: float, end: float, t_start: float, t_end: float) -> bool:
    return start < t_end - FRAME_EPS and end > t_start + FRAME_EPS


def _segment(plan: dict, segment_id: str) -> dict:
    for seg in plan.get("segments") or []:
        if seg["id"] == segment_id:
            return seg
    raise OperationError(f"unknown segment: {segment_id}")


def _caption(plan: dict, index: int) -> dict:
    captions = plan.get("captions") or []
    if not 0 <= index < len(captions):
        raise OperationError(f"caption index out of range: {index}")
    return captions[index]


def _effect_for(plan: dict, segment_id: str) -> Optional[dict]:
    return next((e for e in plan.get("visual_effects") or [] if e.get("segment_id") == segment_id), None)


def _guard(ctx: OpContext, item: Optional[dict], what: str) -> None:
    if ctx.respect_locks and item and item.get("locked"):
        raise LockedError(f"{what} is locked")


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

class _Op(BaseModel):
    model_config = {"extra": "forbid"}

    def apply(self, plan: dict, ctx: OpContext) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError


class SetEffect(_Op):
    op: Literal["set_effect"] = "set_effect"
    segment_id: str
    effect: str

    def apply(self, plan, ctx):
        _segment(plan, self.segment_id)
        existing = _effect_for(plan, self.segment_id)
        _guard(ctx, existing, f"effect on segment {self.segment_id}")
        if existing:
            existing["type"] = self.effect
        else:
            plan.setdefault("visual_effects", []).append({"segment_id": self.segment_id, "type": self.effect})
        return plan


class SetEffectRange(_Op):
    op: Literal["set_effect_range"] = "set_effect_range"
    t_start: float = Field(ge=0)
    t_end: float = Field(gt=0)
    effect: str

    @model_validator(mode="after")
    def _order(self):
        if self.t_end <= self.t_start:
            raise ValueError("t_end must be > t_start")
        return self

    def apply(self, plan, ctx):
        spans = segments_in_range(plan, self.t_start, self.t_end)
        if not spans:
            raise OperationError(f"no segment in output range {self.t_start}-{self.t_end}s")
        for span in spans:
            plan = SetEffect(segment_id=span.id, effect=self.effect).apply(plan, ctx)
        return plan


class SetCaptionText(_Op):
    op: Literal["set_caption_text"] = "set_caption_text"
    index: int = Field(ge=0)
    text: str

    def apply(self, plan, ctx):
        cap = _caption(plan, self.index)
        _guard(ctx, cap, f"caption {self.index}")
        cap["text"] = self.text
        # A highlight that no longer appears in the text would fail validation.
        if cap.get("highlighted_word") and cap["highlighted_word"] not in self.text:
            cap["highlighted_word"] = None
        return plan


class MoveCaptions(_Op):
    op: Literal["move_captions"] = "move_captions"
    t_start: float = Field(ge=0)
    t_end: float = Field(gt=0)
    position: Literal["bottom", "top"]

    def apply(self, plan, ctx):
        hit = [c for c in plan.get("captions") or [] if _overlaps(c["start"], c["end"], self.t_start, self.t_end)]
        if not hit:
            raise OperationError(f"no caption in output range {self.t_start}-{self.t_end}s")
        for cap in hit:
            _guard(ctx, cap, f"caption at {cap['start']}s")
        for cap in hit:
            cap["position"] = self.position
        return plan


class SetHighlight(_Op):
    op: Literal["set_highlight"] = "set_highlight"
    index: int = Field(ge=0)
    word: Optional[str] = None

    def apply(self, plan, ctx):
        cap = _caption(plan, self.index)
        _guard(ctx, cap, f"caption {self.index}")
        cap["highlighted_word"] = self.word
        return plan


class SetTransition(_Op):
    op: Literal["set_transition"] = "set_transition"
    from_segment_id: str
    to_segment_id: str
    type: Literal["hard_cut", "crossfade", "directional", "zoom"]
    duration_frames: Optional[int] = Field(default=None, ge=0, le=30)
    direction: Optional[Literal["left", "right", "up", "down"]] = None
    intensity: Optional[float] = None
    zoom_mode: Optional[Literal["zoom_in", "zoom_out"]] = None
    zoom_scale: Optional[float] = None

    def apply(self, plan, ctx):
        transitions = plan.setdefault("transitions", [])
        pair = (self.from_segment_id, self.to_segment_id)
        existing = next((t for t in transitions
                         if (t["from_segment_id"], t["to_segment_id"]) == pair), None)
        _guard(ctx, existing, f"transition {pair[0]} -> {pair[1]}")
        item = existing if existing is not None else {"from_segment_id": pair[0], "to_segment_id": pair[1]}
        item["type"] = self.type
        if self.type == "hard_cut":
            item["duration_frames"] = 0
        else:
            item["duration_frames"] = self.duration_frames or item.get("duration_frames") or 6
        for name in ("direction", "intensity", "zoom_mode", "zoom_scale"):
            value = getattr(self, name)
            if value is not None:
                item[name] = value
        # Manual transitions must be locked (schema rule); AI edits stay unlocked.
        if ctx.actor == "user":
            item["source"], item["locked"] = "manual", True
        else:
            item["source"], item["locked"] = "planner", False
        if existing is None:
            transitions.append(item)
        return plan


class SetMusicVolume(_Op):
    op: Literal["set_music_volume"] = "set_music_volume"
    volume_db: float = Field(ge=-80.0, le=12.0)

    def apply(self, plan, ctx):
        music = plan.get("music")
        if not music:
            raise OperationError("plan has no music")
        _guard(ctx, music, "music")
        music["volume_db"] = self.volume_db
        return plan


class AddDuck(_Op):
    op: Literal["add_duck"] = "add_duck"
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    volume_db: float = Field(default=-24.0, ge=-80.0, le=12.0)

    def apply(self, plan, ctx):
        music = plan.get("music")
        if not music:
            raise OperationError("plan has no music")
        _guard(ctx, music, "music")
        duck = music.setdefault("duck", [])
        if any(_overlaps(d["start"], d["end"], self.start, self.end) for d in duck):
            raise OperationError(f"duck range {self.start}-{self.end}s overlaps an existing one")
        duck.append({"start": round(self.start, 3), "end": round(self.end, 3), "volume_db": self.volume_db})
        duck.sort(key=lambda d: d["start"])
        return plan


class RemoveBroll(_Op):
    op: Literal["remove_broll"] = "remove_broll"
    index: int = Field(ge=0)

    def apply(self, plan, ctx):
        broll = plan.get("broll") or []
        if not 0 <= self.index < len(broll):
            raise OperationError(f"broll index out of range: {self.index}")
        broll.pop(self.index)
        return plan


class RemoveRange(_Op):
    """Cut [t_start, t_end) out of the output, trimming or splitting segments.

    Later captions, B-roll, SFX, music ducks, cover and poster shift left by the
    removed output duration; events inside the cut are dropped or clipped.
    New boundaries created by the cut are hard cuts.
    """

    op: Literal["remove_range"] = "remove_range"
    t_start: float = Field(ge=0)
    t_end: float = Field(gt=0)

    @model_validator(mode="after")
    def _order(self):
        if self.t_end <= self.t_start:
            raise ValueError("t_end must be > t_start")
        return self

    def apply(self, plan, ctx):
        t0, t1 = self.t_start, self.t_end
        fps = _fps(plan)
        if ctx.respect_locks:
            for span in segments_in_range(plan, t0, t1):
                _guard(ctx, _effect_for(plan, span.id), f"effect on segment {span.id}")
            for cap in plan.get("captions") or []:
                if _overlaps(cap["start"], cap["end"], t0, t1):
                    _guard(ctx, cap, f"caption at {cap['start']}s")
        old_duration = output_duration(plan)
        ids = {s["id"] for s in plan["segments"]}
        new_segments: list[dict] = []
        for span, seg in zip(segment_spans(plan), plan["segments"]):
            if not _overlaps(span.start, span.end, t0, t1):
                new_segments.append(seg)
                continue
            cut_in = seg["in"] + max(0.0, t0 - span.start)
            cut_out = seg["in"] + min(span.end, t1) - span.start
            head = {**seg, "out": round(cut_in, 3)} if cut_in - seg["in"] >= 1 / fps else None
            tail = {**seg, "in": round(cut_out, 3)} if seg["out"] - cut_out >= 1 / fps else None
            if head and tail:
                tail["id"] = _unique_id(f"{seg['id']}b", ids)
                ids.add(tail["id"])
                effect = _effect_for(plan, seg["id"])
                if effect:
                    plan["visual_effects"].append({**effect, "segment_id": tail["id"]})
            new_segments.extend(x for x in (head, tail) if x)
        if not new_segments:
            raise OperationError("cannot remove the whole video")
        plan["segments"] = new_segments
        kept = {s["id"] for s in new_segments}
        plan["visual_effects"] = [e for e in plan.get("visual_effects") or [] if e["segment_id"] in kept]
        adjacent = {(a["id"], b["id"]) for a, b in zip(new_segments, new_segments[1:])}
        plan["transitions"] = [t for t in plan.get("transitions") or []
                               if (t["from_segment_id"], t["to_segment_id"]) in adjacent]
        if plan.get("cover") and plan["cover"].get("source_segment_id") not in (None, *kept):
            plan["cover"]["source_segment_id"] = None
        _shift_events(plan, t0, t1, old_duration - output_duration(plan))
        return plan


class TrimSegment(_Op):
    """Shrink one segment's source range; only shortening is supported."""

    op: Literal["trim_segment"] = "trim_segment"
    segment_id: str
    source_in: Optional[float] = Field(default=None, ge=0)
    source_out: Optional[float] = Field(default=None, gt=0)

    def apply(self, plan, ctx):
        seg = _segment(plan, self.segment_id)
        new_in = seg["in"] if self.source_in is None else self.source_in
        new_out = seg["out"] if self.source_out is None else self.source_out
        if new_in < seg["in"] - FRAME_EPS or new_out > seg["out"] + FRAME_EPS:
            raise OperationError("trim_segment can only shorten a segment")
        if new_out <= new_in:
            raise OperationError("trim would remove the whole segment; use remove_range")
        span = next(s for s in segment_spans(plan) if s.id == self.segment_id)
        # Trim the tail first so the head cut's output times stay valid.
        if new_out < seg["out"] - FRAME_EPS:
            plan = RemoveRange(t_start=span.start + (new_out - seg["in"]), t_end=span.end).apply(plan, ctx)
        if new_in > seg["in"] + FRAME_EPS:
            plan = RemoveRange(t_start=span.start, t_end=span.start + (new_in - seg["in"])).apply(plan, ctx)
        return plan


LockTarget = Literal["effect", "caption", "music", "transition"]


class _LockOp(_Op):
    target: LockTarget
    segment_id: Optional[str] = None       # effect
    index: Optional[int] = Field(default=None, ge=0)  # caption
    from_segment_id: Optional[str] = None  # transition
    to_segment_id: Optional[str] = None

    def _item(self, plan: dict) -> dict:
        if self.target == "effect":
            if not self.segment_id:
                raise OperationError("effect lock needs segment_id")
            item = _effect_for(plan, self.segment_id)
            if item is None:
                raise OperationError(f"segment {self.segment_id} has no effect to lock")
            return item
        if self.target == "caption":
            if self.index is None:
                raise OperationError("caption lock needs index")
            return _caption(plan, self.index)
        if self.target == "music":
            if not plan.get("music"):
                raise OperationError("plan has no music")
            return plan["music"]
        pair = (self.from_segment_id, self.to_segment_id)
        item = next((t for t in plan.get("transitions") or []
                     if (t["from_segment_id"], t["to_segment_id"]) == pair), None)
        if item is None:
            raise OperationError(f"no transition {pair[0]} -> {pair[1]}")
        return item

    def apply(self, plan, ctx):
        if ctx.actor != "user":
            raise OperationError("only a user can lock or unlock")
        item = self._item(plan)
        item["locked"] = self.op == "lock"
        if self.target == "transition":
            # The schema requires manual transitions to be locked.
            item["source"] = "manual" if item["locked"] else (
                "planner" if item.get("source") == "manual" else item.get("source", "default"))
        return plan


class Lock(_LockOp):
    op: Literal["lock"] = "lock"


class Unlock(_LockOp):
    op: Literal["unlock"] = "unlock"


EditOperation = Annotated[
    Union[SetEffect, SetEffectRange, SetCaptionText, MoveCaptions, SetHighlight, SetTransition,
          SetMusicVolume, AddDuck, RemoveBroll, RemoveRange, TrimSegment, Lock, Unlock],
    Field(discriminator="op"),
]
_ADAPTER = TypeAdapter(list[EditOperation])


def parse_operations(raw: list[dict]) -> list[_Op]:
    """Parse operation dicts; raises pydantic.ValidationError on bad input."""
    return _ADAPTER.validate_python(raw)


# ---------------------------------------------------------------------------
# Batch application
# ---------------------------------------------------------------------------

@dataclass
class ApplyResult:
    plan: dict
    diff: list[dict] = field(default_factory=list)
    operations: list[dict] = field(default_factory=list)


def apply_operations(
    plan: dict,
    operations: list[Union[_Op, dict]],
    ctx: Optional[OpContext] = None,
    *,
    base_dir: Optional[Path] = None,
    check_media: bool = False,
) -> ApplyResult:
    """Apply a batch atomically. The input plan is never mutated.

    Each operation's result is schema-validated so the failing operation is
    named; the final plan is validated once more (with media checks when
    requested). Any failure raises ``OperationError`` with the batch index.
    """
    ctx = ctx or OpContext()
    ops = [op if isinstance(op, _Op) else parse_operations([op])[0] for op in operations]
    if not ops:
        raise OperationError("no operations given")
    working = copy.deepcopy(plan)
    for i, op in enumerate(ops):
        try:
            working = op.apply(working, ctx)
        except OperationError as exc:
            exc.index = i
            raise
        _, errors = validate_plan(working, check_media=False)
        if errors:
            raise OperationError(f"{op.op}: " + "; ".join(errors), index=i)
    if check_media:
        _, errors = validate_plan(working, base_dir=base_dir, check_media=True)
        if errors:
            raise OperationError("; ".join(errors))
    return ApplyResult(plan=working, diff=plan_diff(plan, working),
                       operations=[op.model_dump(exclude_none=True) for op in ops])


def plan_diff(before: Any, after: Any, path: str = "") -> list[dict]:
    """Minimal JSON-path diff: [{path, before, after}] (missing values are None)."""
    if isinstance(before, dict) and isinstance(after, dict):
        out = []
        for key in list(before) + [k for k in after if k not in before]:
            out += plan_diff(before.get(key), after.get(key), f"{path}.{key}" if path else key)
        return out
    if isinstance(before, list) and isinstance(after, list):
        out = []
        for i in range(max(len(before), len(after))):
            out += plan_diff(before[i] if i < len(before) else None,
                             after[i] if i < len(after) else None, f"{path}[{i}]")
        return out
    return [] if before == after else [{"path": path, "before": before, "after": after}]


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _unique_id(base: str, taken: set[str]) -> str:
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}{n}", n + 1
    return candidate


def _shift_events(plan: dict, t0: float, t1: float, removed: float) -> None:
    """Remap output-time events after cutting [t0, t1) (``removed`` seconds)."""
    new_duration = output_duration(plan)
    min_len = 1.0 / _fps(plan)

    def at(t: float) -> float:
        if t <= t0:
            return t
        if t < t1:
            return t0
        return max(t0, t - removed)

    def span(start: float, end: float) -> Optional[tuple[float, float]]:
        s, e = at(start), min(at(end), new_duration)
        return (round(s, 3), round(e, 3)) if e - s >= min_len else None

    captions = []
    for cap in plan.get("captions") or []:
        r = span(cap["start"], cap["end"])
        if r:
            cap["start"], cap["end"] = r
            captions.append(cap)
    plan["captions"] = captions

    broll = []
    for b in plan.get("broll") or []:
        r = span(b["at"], b["at"] + b["duration"])
        if r:
            if t0 <= b["at"] < t1:
                # The clip's head was cut, so start later in the B-roll asset.
                b["in"] = round(b.get("in", 0.0) + (t1 - b["at"]), 3)
            b["at"], b["duration"] = r[0], round(r[1] - r[0], 3)
            broll.append(b)
    plan["broll"] = broll

    plan["sfx"] = [{**s, "at": round(at(s["at"]), 3)} for s in plan.get("sfx") or []
                   if not (t0 <= s["at"] < t1) and at(s["at"]) < new_duration]

    if plan.get("music"):
        duck = []
        for d in plan["music"].get("duck") or []:
            r = span(d["start"], d["end"])
            if r:
                d["start"], d["end"] = r
                duck.append(d)
        plan["music"]["duck"] = duck

    if plan.get("cover"):
        r = span(plan["cover"].get("start", 0.0), plan["cover"].get("end", 2.5))
        if r:
            plan["cover"]["start"], plan["cover"]["end"] = r
        else:
            plan["cover"] = None
    if plan.get("poster"):
        t = at(plan["poster"].get("frame_time", 1.0))
        plan["poster"]["frame_time"] = round(min(t, max(0.0, new_duration - min_len)), 3)


# ---------------------------------------------------------------------------
# Locks across regeneration
# ---------------------------------------------------------------------------
# A regenerated plan has new segments and a new output timeline, so locked
# items are carried by their *source* time and re-anchored onto the new plan.

def _to_source(spans: list[SegmentSpan], t: float, end: bool = False) -> Optional[float]:
    for s in spans:
        if (s.start <= t < s.end) or (end and s.start < t <= s.end + FRAME_EPS):
            return round(s.source_in + (t - s.start), 3)
    return None


def _to_output(spans: list[SegmentSpan], src: float) -> Optional[float]:
    for s in spans:
        if s.source_in - FRAME_EPS <= src <= s.source_out + FRAME_EPS:
            return round(s.start + (src - s.source_in), 3)
    return None


def _anchor(spans, start: float, end: float) -> dict:
    return {"source_start": _to_source(spans, start), "source_end": _to_source(spans, end, end=True)}


def _reanchor(spans, anchor: dict) -> Optional[tuple[float, float]]:
    if anchor.get("source_start") is None or anchor.get("source_end") is None:
        return None
    start, end = _to_output(spans, anchor["source_start"]), _to_output(spans, anchor["source_end"])
    if start is None or end is None or end <= start:
        return None
    return start, end


def extract_locked(plan: Optional[dict]) -> dict:
    """Locked effects, captions and music of a plan, anchored to source time."""
    if not plan:
        return {}
    spans = segment_spans(plan)
    by_id = {s["id"]: s for s in plan.get("segments") or []}
    effects = [{"effect": dict(e), "source_in": by_id[e["segment_id"]]["in"],
                "source_out": by_id[e["segment_id"]]["out"]}
               for e in plan.get("visual_effects") or [] if e.get("locked") and e.get("segment_id") in by_id]
    captions = [{"caption": dict(c), **_anchor(spans, c["start"], c["end"])}
                for c in plan.get("captions") or [] if c.get("locked")]
    music = None
    if (plan.get("music") or {}).get("locked"):
        music = {"music": copy.deepcopy(plan["music"]),
                 "duck": [_anchor(spans, d["start"], d["end"]) for d in plan["music"].get("duck") or []]}
    locked = {"effects": effects, "captions": captions, "music": music}
    return locked if effects or captions or music else {}


def merge_locked(plan: dict, locked: Optional[dict]) -> list[str]:
    """Re-apply locked items onto a freshly generated plan, in place.

    Returns human-readable notes for locked items that no longer fit (their
    source footage was cut from the new plan).
    """
    if not locked:
        return []
    dropped: list[str] = []
    spans = segment_spans(plan)

    for item in locked.get("effects") or []:
        best, best_overlap = None, 0.0
        for seg in plan.get("segments") or []:
            overlap = min(seg["out"], item["source_out"]) - max(seg["in"], item["source_in"])
            if overlap > best_overlap:
                best, best_overlap = seg, overlap
        if best is None or best_overlap < 0.5 * min(best["out"] - best["in"],
                                                     item["source_out"] - item["source_in"]):
            dropped.append(f"locked effect {item['effect']['type']} (source {item['source_in']}s)")
            continue
        effects = [e for e in plan.get("visual_effects") or [] if e.get("segment_id") != best["id"]]
        effects.append({**item["effect"], "segment_id": best["id"], "locked": True})
        plan["visual_effects"] = effects

    for item in locked.get("captions") or []:
        r = _reanchor(spans, item)
        if r is None:
            dropped.append(f"locked caption {item['caption']['text']!r}")
            continue
        captions = [c for c in plan.get("captions") or [] if c.get("locked") or not _overlaps(c["start"], c["end"], *r)]
        captions.append({**item["caption"], "start": r[0], "end": r[1], "locked": True})
        plan["captions"] = sorted(captions, key=lambda c: c["start"])

    if locked.get("music"):
        music = locked["music"]["music"]
        duck = []
        for d, anchor in zip(music.get("duck") or [], locked["music"]["duck"]):
            r = _reanchor(spans, anchor)
            if r:
                duck.append({**d, "start": r[0], "end": r[1]})
        music["duck"] = duck
        plan["music"] = music
    return dropped
