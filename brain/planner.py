"""LLM-based edit plan generator.

Input: transcript + keep/remove ranges + style profile + user instruction.
Output: a valid plan.json ready for the engine.

The planner asks the LLM to:
- drop retakes, false starts and fillers (keep the last good take)
- choose punch-ins on key sentences and slow zooms elsewhere
- write short captions (2-5 words, timed from word timestamps → output timeline)
- propose B-roll moments as {at, duration, query}
- place whoosh SFX on cuts into B-roll and music ducking under speech
"""
from __future__ import annotations

import json
import logging
import math
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import yaml

from engine.schema import PROJECT_ROOT, EditPlan, format_error, validate_plan
from engine.effects import MOTIONS, LIGHTS, EFFECT_CATALOG, EFFECT_FAMILIES, families_for_llm
from engine.effects_v4 import MyEffectsPreset, EffectFeedback
from .llm import LLMUsage
from .ai_provider import get_provider
from .segment_analysis import analyse_segments
from .effect_score import critic_effect_pass
from .effect_score_v4 import select_effects_with_vision
from .signals import measure_segment_signals

log = logging.getLogger(__name__)


def _load_preset(name: str = "rafiei_reel") -> dict:
    preset_dir = (PROJECT_ROOT / "presets").resolve()
    p = (preset_dir / f"{name}.yaml").resolve()
    if p.parent != preset_dir or Path(name).name != name:
        raise ValueError(f"invalid style preset name: {name!r}")
    return yaml.safe_load(p.read_text())


_PERSIAN_CODES = {"fa", "per", "fas", "persian", "farsi"}


def _is_persian(lang: str) -> bool:
    return lang.lower().strip() in _PERSIAN_CODES


def _build_system_prompt(preset: dict, language: str = "en", analyses: Optional[list[dict]] = None,
                        font_options: Optional[list[dict[str, str]]] = None) -> str:
    persian = _is_persian(language)
    font_lines = "\n".join(
        "  - " + json.dumps(option, ensure_ascii=False)
        for option in (font_options or [])
    )
    font_rule = (
        "\n- Select canvas.caption_font or canvas.caption_font_id from the actual available fonts below. "
        "Choose a legible font and weight for this content's tone (for example, bold geometric for energetic "
        "claims, a clean neutral face for instructional speech, and a restrained display face only when the "
        "content supports it). Use transcript and content cues; do not invent names or trade readability for novelty.\n"
        f"Available fonts:\n{font_lines}"
    ) if font_lines else ""
    caption_lang_rule = (
        "\n- IMPORTANT: The video language is Persian (Farsi). Write ALL captions in Persian script "
        "(right-to-left, joined letters). Do NOT translate to English. "
        "Each caption must be authentic Persian text from the transcript. Choose only a listed font with Persian coverage."
        if persian else ""
    )

    # Build effect guidance: family names + pre-computed assignments when available
    if analyses:
        # Segment analyses already exist — skip effect details, tell the LLM effects are pre-assigned
        effect_block = (
            "- Visual effects for each segment have been pre-computed by the effect scorer. "
            "You MUST include a visual_effects entry for every segment using the provided analysis. "
            "Use the segment_id exactly as given. Valid types: <motion>__<light>. "
            f"Motions: {', '.join(MOTIONS)}. Light treatments: {', '.join(LIGHTS)}."
        )
    else:
        # No pre-analysis: give the LLM family descriptions to guide selection
        families = families_for_llm()
        fam_lines = "\n".join(
            f"  {f['family']}: energy={f['energy']} mood={f['mood']} — {f['description']} (example: {f['example_id']})"
            for f in families
        )
        effect_block = (
            f"- Give each segment one visual_effects entry. Type must be <motion>__<light>.\n"
            f"  Motions: {', '.join(MOTIONS)}. Light treatments: {', '.join(LIGHTS)}.\n"
            f"- Choose from these named effect families (pick the example_id or any variant):\n"
            f"{fam_lines}\n"
            f"- Use light treatments (lift, dim, pulse, fade, breath) — don't default to __neutral for everything.\n"
            f"- Do not use the same effect family more than twice in a row.\n"
            f"- Use punch_bright or flash at most once. Use pan/tilt/drift only if framing is confirmed."
        )

    return f"""You are Rafiei AI Editor — you turn raw video transcripts into edit plans.

Output a single JSON object matching the Edit Plan schema below. No markdown, no explanation — pure JSON only.

## Edit Plan JSON Schema
{{
  "version": "0.3",
  "style": "rafiei_reel",
  "canvas": {{"width": 1080, "height": 1920, "fps": 30, "caption_font": "<listed family>", "caption_font_id": "<listed id when selecting an approved font>"}},
  "source": "<relative path to raw video>",
  "segments": [
    {{"id": "s1", "in": <source_start_sec>, "out": <source_end_sec>,
      "zoom": {{"from": <1.0-1.20>, "to": <1.0-1.20>}}}}
  ],
  "visual_effects": [
    {{"segment_id": "s1", "type": "steady__neutral"}}
  ],
  "transitions": [
    {{"from_segment_id": "s1", "to_segment_id": "s2", "type": "hard_cut",
      "duration_frames": 0, "direction": "left", "intensity": 1.0,
      "zoom_mode": "zoom_in", "zoom_scale": 1.15,
      "source": "default", "locked": false}}
  ],
  "captions": [
    {{"start": <output_timeline_sec>, "end": <output_timeline_sec>,
      "text": "<2-5 words>", "style": "normal|emphasis|cta", "highlighted_word": "<exact word or phrase from text>"}}
  ],
  "broll": [
    {{"at": <output_timeline_sec>, "duration": <sec>, "file": "<existing B-roll file path>",
      "in": 0.0, "query": "<text description for future asset matching>"}}
  ],
  "music": {{
    "file": "<music file path>",
    "volume_db": {preset.get("music", {}).get("default_volume_db", -14)},
    "duck": [{{"start": <sec>, "end": <sec>, "volume_db": {preset.get("music", {}).get("duck_volume_db", -24)}}}]
  }},
  "sfx": [{{"at": <output_timeline_sec>, "file": "<sfx file path>", "volume_db": {preset.get("sfx", {}).get("whoosh_volume_db", -3)}}}],
  "export": {{"file": "exports/v1.mp4", "crf": 20}}
}}

## Style rules (from Rafiei Reel Style preset)
- Max seconds without a cut, visual change, or B-roll: {preset.get("editing", {}).get("max_static_sec", 4.0)}
{effect_block}
- The legacy segment.zoom field is retained for older plans; typed visual_effects take precedence.
- Caption length: {preset.get("captions", {}).get("min_words", 2)}-{preset.get("captions", {}).get("max_words", 5)} words each{caption_lang_rule}{font_rule}
- Mark one emphasis caption per key point, one CTA caption at the end
- Mark at most one short, exact, high-information word or phrase in each caption as highlighted_word. Prefer a concrete benefit, result, warning, or action; use JSON null when no word deserves emphasis. Never add words that were not spoken. The renderer will color this text with the style accent color.
- B-roll: ~{preset.get("broll", {}).get("default_duration_sec", 2.0)}s each, minimum {preset.get("broll", {}).get("min_gap_sec", 8.0)}s apart
- B-roll file paths must refer to existing media; never use a placeholder or invented path. If no real asset is available, omit that B-roll item.
- Place a whoosh SFX on each cut into B-roll
- Music ducks under all speech

## Content rules
- Drop retakes: when the speaker restarts a sentence, keep ONLY the last good take
- Drop false starts, fillers ("اِ", "uhm", "um", "hmm")
- Drop off-camera talk: setup chatter, take numbers, camera operator questions
  (e.g. "این دو، این یک… رکورد زدی الان دوباره؟", "چهارده رو اسکیپ می‌کنیم میایم رو پونزده",
   "بزن رکورد", "ضبط کردی؟", counting takes, crew coordination).
  These are NOT the speaker's message — cut them from the final edit.
- Remove pauses already identified in the remove_ranges
- Finish the edit on a complete sentence. If the source recording ends during
  an unfinished thought, omit that trailing thought instead of ending mid-speech.
- Segments use SOURCE timeline times (in/out refer to the raw video)
- Captions and B-roll use OUTPUT timeline times (after cuts/removals)
- The output timeline is the concatenation of kept segments in order
- Include one transition item for every adjacent segment pair. Use hard_cut
  with duration_frames 0 unless shot context clearly justifies a restrained
  crossfade, directional transition, or zoom. Use zoom only when the user's
  request or shot context supports it, and keep zoom_scale between 1.02 and 1.5.
  Rendered transitions overlap adjacent
  clips and shorten the output by duration_frames / canvas.fps.

## Critical timing rules
- segment.in and segment.out are in SOURCE video time
- caption.start, caption.end, broll.at, sfx.at, music.duck are in OUTPUT timeline time
- To convert: for each word, find which kept segment it falls in, then compute
  output_time = sum(duration of all preceding segments) + (word_source_time - segment.in)
- Captions must align with the spoken words' output times
- Captions should quote kept speech faithfully. Never invent or change a claim to make it read better. If the transcript is uncertain, keep the uncertainty visible for review.
- The total output duration in frames = sum(round(segment duration * fps))
  minus the duration_frames of every rendered transition
- All captions must end before the total output duration
- All broll.at + broll.duration must be <= total output duration
- All sfx.at must be <= total output duration"""


def _build_user_prompt(
    transcript: dict,
    keep_ranges: list[tuple[float, float]],
    remove_ranges: list[tuple[float, float]],
    source_path: str,
    music_file: Optional[str],
    sfx_file: Optional[str],
    instruction: str = "",
    output_kind: str = "reel",
    transition_request: str = "",
    transition_style: str = "auto",
) -> str:
    words_text = json.dumps(transcript["words"][:500], ensure_ascii=False)
    sentences_text = json.dumps(transcript["sentences"], ensure_ascii=False)

    parts = [
        f"## Source video\nPath: {source_path}",
        f"Language: {transcript.get('language', 'unknown')}",
        f"Duration: {transcript.get('duration', 0):.2f}s",
        f"\n## Transcript (words)\n{words_text}",
        f"\n## Sentences\n{sentences_text}",
        f"\n## Keep ranges (source time)\n{json.dumps(keep_ranges)}",
        f"\n## Remove ranges (source time)\n{json.dumps(remove_ranges)}",
        f"\n## Requested output kind\n{output_kind}",
    ]

    parts.append(
        f"\n## Transition policy\nFormat: {output_kind}. "
        f"{TRANSITION_FORMAT_GUIDE.get(output_kind, TRANSITION_FORMAT_GUIDE['reel'])}\n"
        f"Selected transition style: {transition_style}."
    )
    if transition_request:
        parts.append(f"\n## User transition request\n{transition_request}")

    if music_file:
        parts.append(f"\n## Available assets\nMusic: {music_file}")
    if sfx_file:
        parts.append(f"Whoosh SFX: {sfx_file}")

    if instruction:
        parts.append(f"\n## User instruction\n{instruction}")

    parts.append(
        "\nNow produce the Edit Plan JSON. Remember: segments use source times, "
        "captions/broll/sfx use output timeline times. Ensure all times are valid."
    )
    return "\n".join(parts)


def source_to_output_time(
    source_time: float,
    segments: list[dict],
) -> Optional[float]:
    """Convert a source-video timestamp to the output-timeline timestamp.

    Returns None if the source_time falls outside all kept segments.
    """
    acc = 0.0
    for seg in segments:
        seg_in = seg.get("in", seg.get("in_", 0))
        seg_out = seg.get("out", 0)
        if seg_in <= source_time <= seg_out:
            return round(acc + (source_time - seg_in), 3)
        acc += seg_out - seg_in
    return None


def output_to_source_time(
    output_time: float,
    segments: list[dict],
) -> Optional[float]:
    """Convert an output-timeline timestamp back to source time."""
    acc = 0.0
    for seg in segments:
        seg_in = seg.get("in", seg.get("in_", 0))
        seg_out = seg.get("out", 0)
        seg_dur = seg_out - seg_in
        if acc + seg_dur >= output_time - 1e-6:
            return round(seg_in + (output_time - acc), 3)
        acc += seg_dur
    return None


TRANSITION_STYLES = ("auto", "none", "crossfade", "directional", "zoom")
TRANSITION_FORMAT_CAPS = {"post": 8, "story": 10, "reel": 12}
TRANSITION_FORMAT_GUIDE = {
    "reel": "Fast-paced; short crossfades, directional moves, or subtle boundary zooms at energy shifts are fine.",
    "story": "Short and punchy; use transitions sparingly and keep them brief.",
    "post": "Clean and restrained; prefer hard cuts or very short crossfades.",
}


def _suggest_transitions(
    plan_data: dict,
    analyses: list[dict],
    locked_transitions: Optional[list[dict]] = None,
    output_kind: str = "reel",
    transition_request: str = "",
    transition_style: str = "auto",
) -> None:
    """Create one conservative, typed item for each adjacent boundary."""
    segments = plan_data.get("segments") or []
    if len(segments) < 2:
        plan_data["transitions"] = []
        return
    fps = int((plan_data.get("canvas") or {}).get("fps", 30))
    analysis = {item.get("segment_id"): item for item in analyses}
    locked = {
        (item.get("from_segment_id"), item.get("to_segment_id")): item
        for item in (locked_transitions or [])
        if item.get("locked")
    }
    model_choices = {
        (item.get("from_segment_id"), item.get("to_segment_id")): item
        for item in (plan_data.get("transitions") or [])
        if item.get("type") in {"hard_cut", "crossfade", "directional", "zoom"}
    }
    suggestions = []
    review = []
    for index, (outgoing, incoming) in enumerate(zip(segments, segments[1:])):
        pair = (outgoing["id"], incoming["id"])
        if pair in locked:
            item = dict(locked[pair])
            item["source"] = "manual"
            item["locked"] = True
            suggestions.append(item)
            review.append({"boundary_index": index, "source": "manual", "reason": "locked manual choice"})
            continue
        left = analysis.get(outgoing["id"], {})
        right = analysis.get(incoming["id"], {})
        left_energy = int(left.get("energy", 2) or 2)
        right_energy = int(right.get("energy", 2) or 2)
        segment_frames = [round((seg["out"] - seg["in"]) * fps) for seg in (outgoing, incoming)]
        max_overlap = max(0, min(30, min(segment_frames) // 3))
        item = {"from_segment_id": pair[0], "to_segment_id": pair[1],
                "type": "hard_cut", "duration_frames": 0, "direction": "left",
                "intensity": 1.0, "source": "default", "locked": False}
        reason = "quiet hard cut preserves speech and framing"
        model_choice = model_choices.get(pair)
        if transition_style == "none":
            reason = "user selected no transitions (hard cuts only)"
        elif transition_style in ("crossfade", "directional", "zoom"):
            if max_overlap >= 2:
                frames = max(2, min(6, max_overlap,
                                    TRANSITION_FORMAT_CAPS.get(output_kind, 10)))
                item.update(type=transition_style, duration_frames=frames,
                            direction=(model_choice or {}).get("direction", "left"),
                            intensity=0.75, zoom_mode=(model_choice or {}).get("zoom_mode", "zoom_in"),
                            zoom_scale=(model_choice or {}).get("zoom_scale", 1.12), source="planner")
                reason = f"user selected {transition_style} transitions for {output_kind}"
            else:
                reason = "segment too short for the selected transition; hard cut"
        elif model_choice:
            requested_type = model_choice.get("type", "hard_cut")
            requested_frames = int(model_choice.get("duration_frames", 0) or 0)
            if requested_type == "hard_cut":
                requested_frames = 0
            elif max_overlap >= 2:
                format_cap = TRANSITION_FORMAT_CAPS.get(output_kind, 10)
                requested_frames = max(2, min(requested_frames or 6, max_overlap, format_cap))
            else:
                requested_type, requested_frames = "hard_cut", 0
            item.update(type=requested_type, duration_frames=requested_frames,
                        direction=model_choice.get("direction", "left"),
                        intensity=max(0.5, min(1.0, float(model_choice.get("intensity", 1.0)))),
                        zoom_mode=model_choice.get("zoom_mode", "zoom_in"),
                        zoom_scale=max(1.02, min(1.5, float(model_choice.get("zoom_scale", 1.15)))),
                        source="planner")
            reason = f"AI selected for {output_kind} shot context"
            if transition_request:
                reason += "; considered the user's transition request"
        elif max_overlap >= 6 and bool(right.get("is_turning_point")) and right_energy >= 4:
            item.update(type="directional", duration_frames=min(8, max_overlap),
                        direction="left", intensity=0.75, source="planner")
            reason = "directional transition marks a high-energy turning point"
        elif max_overlap >= 6 and left_energy <= 2 and right_energy <= 2 \
                and right.get("role") in {"reflection", "conclusion", "emotion"}:
            item.update(type="crossfade", duration_frames=min(10, max_overlap), source="planner")
            reason = "short crossfade joins two low-energy related shots"
        suggestions.append(item)
        review.append({"boundary_index": index, "source": item["source"], "reason": reason})
    plan_data["transitions"] = suggestions
    plan_data["transition_analysis"] = review
    plan_data["transition_context"] = {
        "output_kind": output_kind,
        "request": transition_request,
        "style": transition_style,
        "supported_types": ["hard_cut", "crossfade", "directional", "zoom"],
    }
    plan_data["version"] = "0.3"


def _retime_for_transition_overlaps(plan_data: dict) -> None:
    """Map model-authored concatenated output times onto the overlap timeline."""
    transitions = {(item["from_segment_id"], item["to_segment_id"]): int(item["duration_frames"])
                   for item in plan_data.get("transitions", [])}
    if not any(transitions.values()):
        return
    segments = plan_data.get("segments") or []
    fps = int((plan_data.get("canvas") or {}).get("fps", 30))
    legacy_starts, output_starts = [], []
    legacy_cursor = output_cursor = 0.0
    for index, segment in enumerate(segments):
        legacy_starts.append(legacy_cursor)
        output_starts.append(output_cursor)
        duration = segment["out"] - segment["in"]
        legacy_cursor += duration
        output_cursor += round(duration * fps) / fps
        if index < len(segments) - 1:
            output_cursor -= transitions.get((segment["id"], segments[index + 1]["id"]), 0) / fps

    def convert(value: float) -> float:
        value = float(value)
        index = len(segments) - 1
        for candidate in range(len(segments) - 1):
            boundary = legacy_starts[candidate + 1]
            if value < boundary - 1e-9:
                index = candidate
                break
        return round(max(0.0, min(output_cursor, output_starts[index] + value - legacy_starts[index])), 3)

    for event in plan_data.get("captions", []):
        event["start"], event["end"] = convert(event["start"]), convert(event["end"])
    for event in plan_data.get("broll", []):
        old_end = event["at"] + event["duration"]
        event["at"] = convert(event["at"])
        event["duration"] = round(max(0.001, convert(old_end) - event["at"]), 3)
    for event in plan_data.get("sfx", []):
        event["at"] = convert(event["at"])
    if plan_data.get("music"):
        for event in plan_data["music"].get("duck", []):
            event["start"], event["end"] = convert(event["start"]), convert(event["end"])


def _usable_audio_asset(path: Path) -> bool:
    """Return whether a file exists and ffprobe confirms usable audio + duration."""
    from engine.probe import probe

    path = Path(path)
    if not path.is_file():
        return False
    try:
        if path.stat().st_size <= 0:
            return False
        info = probe(path)
        duration = float(info.get("format", {}).get("duration", 0))
        return (
            math.isfinite(duration)
            and duration > 0
            and any(stream.get("codec_type") == "audio" for stream in info.get("streams", []))
        )
    except Exception as exc:
        log.debug("skipping unusable audio asset %s: %s", path, exc)
        return False


def _find_asset(job_dir: Path, kind: str) -> Optional[str]:
    """Find the first playable audio asset in the job or project directories."""

    search_dirs = [
        Path(job_dir) / kind,
        PROJECT_ROOT / "assets" / kind,
        PROJECT_ROOT / "samples" / "media",
    ]
    extensions = (".mp3", ".wav", ".ogg", ".m4a")
    for d in search_dirs:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in extensions and _usable_audio_asset(f):
                return str(f.resolve())
    return None


def _ensure_visual_effects(plan_data: dict) -> None:
    """Give future plans a restrained visual rhythm if a model omits effects."""
    pattern = ("steady__neutral", "punch__neutral", "slow_pull__neutral",
               "steady__lift_soft", "steady__pulse_start", "slow_push__neutral")
    provided = list(plan_data.get("visual_effects") or [])
    chosen = {effect.get("segment_id") for effect in provided}
    for i, segment in enumerate(plan_data.get("segments", [])):
        if segment["id"] not in chosen:
            provided.append({"segment_id": segment["id"],
                             "type": "steady__neutral" if segment["out"] - segment["in"] < 0.5
                             else pattern[i % len(pattern)]})
    plan_data["visual_effects"] = provided
    effects_by_segment = {effect.get("segment_id"): effect for effect in provided}
    ordered = [effects_by_segment.get(seg["id"]) for seg in plan_data.get("segments", [])]
    for i in range(2, len(ordered)):
        current = ordered[i]
        if current and current.get("type") == ordered[i-1].get("type") == ordered[i-2].get("type"):
            current["type"] = "steady__neutral" if current["type"] != "steady__neutral" else "slow_push__neutral"
    plan_data["version"] = "0.2"
    plan_data["effect_review"] = [
        {"segment_id": effect["segment_id"], "reason": "check_subject_framing"}
        for effect in provided if EFFECT_CATALOG.get(effect.get("type"), {}).get("needs_framing_review")
    ]


def _caption_review(plan_data: dict, transcript: dict) -> list[dict]:
    """Flag caption text or timing that cannot be supported by ASR words."""
    segments = plan_data.get("segments", [])
    warnings = []
    def normalize(value: str) -> str:
        value = value.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
        return " ".join(re.findall(r"\w+", value.lower()))
    for index, caption in enumerate(plan_data.get("captions", [])):
        source_words = []
        for word in transcript.get("words", []):
            midpoint = (word["start"] + word["end"]) / 2
            output_time = source_to_output_time(midpoint, segments)
            if output_time is not None and caption["start"] - 0.1 <= output_time <= caption["end"] + 0.1:
                source_words.append(word)
        source_text = " ".join(word["w"] for word in source_words)
        similarity = SequenceMatcher(None, normalize(caption["text"]), normalize(source_text)).ratio()
        low_confidence = any(word.get("prob", 1) < 0.6 and not word.get("reviewed")
                             for word in source_words)
        if not source_words or similarity < 0.68 or low_confidence:
            warnings.append({"caption_index": index, "source_text": source_text,
                             "reason": "no_matching_words" if not source_words else
                                       "low_confidence" if low_confidence else "text_mismatch"})
    return warnings


def _extract_keyframes(segments: list[dict], raw_video: Path, keyframe_dir: Path) -> Path:
    """Extract 512px keyframes from segment midpoints using ffmpeg.

    Returns keyframe_dir path (created if needed).
    """
    keyframe_dir.mkdir(parents=True, exist_ok=True)

    for seg in segments:
        seg_id = seg["id"]
        in_time = seg["in"]
        out_time = seg["out"]
        midpoint = (in_time + out_time) / 2.0

        keyframe_path = keyframe_dir / f"{seg_id}.jpg"

        # Extract 1 keyframe at midpoint, scale to 512 width (maintain aspect)
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(midpoint), "-i", str(raw_video),
                "-vf", "scale=512:-1",
                "-vframes", "1",
                "-q:v", "3",
                str(keyframe_path),
            ], capture_output=True, check=True, timeout=5)
            log.debug(f"Extracted keyframe for {seg_id} at {midpoint:.2f}s to {keyframe_path.name}")
        except subprocess.TimeoutExpired:
            log.warning(f"Keyframe extraction timed out for {seg_id}")
        except Exception as e:
            log.warning(f"Failed to extract keyframe for {seg_id}: {e}")

    return keyframe_dir


def _apply_scored_effects(plan_data: dict, analyses: list[dict], transcript: dict, preset: dict, raw_video: Optional[Path] = None) -> LLMUsage:
    """Run the effect scorer + critic pass, write results into plan_data in-place.

    Uses V4 vision-aware scorer with user preferences.
    Returns combined LLM usage from both calls.
    """
    segments = plan_data.get("segments", [])
    if not segments or not analyses:
        return LLMUsage()

    # Load My Effects preferences if available
    my_effects = MyEffectsPreset()
    feedback = EffectFeedback()
    selection_locked = bool(my_effects.selected_rafiei_style)

    keyframe_dir = None
    if not selection_locked and raw_video and raw_video.exists():
        keyframe_dir = raw_video.parent.parent / "keyframes"
        keyframe_dir.mkdir(exist_ok=True)
        chosen_indices = {0, len(segments) // 2, len(segments) - 1}
        _extract_keyframes([segments[i] for i in sorted(chosen_indices)], raw_video, keyframe_dir)

    # Call V4 scorer with text-based scoring
    vision_usages = []
    scored_v4 = select_effects_with_vision(
        segments, analyses, keyframe_dir, preset,
        my_effects=my_effects,
        feedback=feedback, vision_usage=vision_usages,
    )

    # Convert V4 output to critic-compatible format
    scored_effects = []
    for eff_v4 in scored_v4:
        scored_effects.append({
            "segment_id": eff_v4["segment_id"],
            "type": eff_v4["type"],
            "_family": eff_v4.get("family", "still"),
            "_reason": eff_v4.get("reason", ""),
            "_intensity": 2,  # Placeholder
            "_source": eff_v4.get("source", "analysis"),
            "_vision": eff_v4.get("vision"),
        })

    # Apply critic pass
    total_dur = sum(s.get("out", 0) - s.get("in", 0) for s in segments)
    no_zoom = any("زوم نکن" in rule.get("text", "") or "no zoom" in rule.get("text", "").lower()
                  for rule in my_effects.rules)
    if selection_locked or no_zoom:
        crit_usage = LLMUsage()
    else:
        original_types = {effect["segment_id"]: effect["type"] for effect in scored_effects}
        scored_effects, crit_usage = critic_effect_pass(scored_effects, analyses, total_dur, preset)
        for effect in scored_effects:
            if effect["type"] != original_types.get(effect["segment_id"]):
                effect["_source"] = "rule"

    plan_data["visual_effects"] = [
        {"segment_id": e["segment_id"], "type": e["type"]}
        for e in scored_effects
    ]
    if selection_locked:
        # Typed effects are authoritative, but also neutralise the legacy zoom
        # field so the saved plan and visual editor cannot show a conflicting
        # AI-generated zoom direction.
        for segment in plan_data.get("segments", []):
            segment["zoom"] = {"from": 1.0, "to": 1.0}
    # Save debug metadata separately so it doesn't fail schema validation
    plan_data["effect_analysis"] = [
        {
            "segment_id": e["segment_id"],
            "family": e.get("_family", ""),
            "reason": e.get("_reason", ""),
            "source": e.get("_source", "analysis"),
            "vision": e.get("_vision"),
            "intensity": e.get("_intensity", 2),
            "emphasis_start": e.get("_emphasis_start"),
        }
        for e in scored_effects
    ]

    combined = LLMUsage()
    combined.input_tokens = crit_usage.input_tokens + sum(u.input_tokens for u in vision_usages)
    combined.output_tokens = crit_usage.output_tokens + sum(u.output_tokens for u in vision_usages)
    combined.model = crit_usage.model or (vision_usages[-1].model if vision_usages else "")
    combined.elapsed_sec = crit_usage.elapsed_sec + sum(u.elapsed_sec for u in vision_usages)
    return combined


def _enforce_effect_dislikes(plan_data: dict, dislikes: set[str]) -> None:
    """Apply user exclusions after scoring, critic edits, and fallback choices."""
    from engine.effects_v4 import EFFECT_FAMILIES_V4
    excluded = set(dislikes)
    for family in dislikes:
        excluded.update(EFFECT_FAMILIES_V4.get(family, {}).get("ids", []))
    replacement = next((candidate for candidate in ("steady__neutral", "slow_push__neutral", "slow_pull__neutral")
                        if candidate not in excluded), None)
    if replacement is None:
        return
    for effect in plan_data.get("visual_effects", []):
        if effect.get("type") in excluded:
            effect["type"] = replacement


def _enforce_selected_effect(plan_data: dict, selected_effect: Optional[str]) -> None:
    """Make one explicit My Effects choice authoritative for every segment."""
    if not selected_effect:
        return
    plan_data["visual_effects"] = [
        {"segment_id": segment["id"], "type": selected_effect}
        for segment in plan_data.get("segments", [])
    ]
    for segment in plan_data.get("segments", []):
        segment["zoom"] = {"from": 1.0, "to": 1.0}
    plan_data["effect_analysis"] = [
        {
            "segment_id": segment["id"],
            "family": "user_selected",
            "reason": f"Locked by My Effects selection: {selected_effect}",
            "source": "my_effects_selection",
            "vision": None,
            "intensity": 2,
            "emphasis_start": None,
        }
        for segment in plan_data.get("segments", [])
    ]


def _output_segment_marks(plan_data: dict) -> tuple[list[tuple[float, float, str]], float]:
    """Return output-timeline segment ranges using the same frame math as MLT."""
    segments = plan_data.get("segments") or []
    fps = max(1, int((plan_data.get("canvas") or {}).get("fps", 30)))
    transitions = {
        (item.get("from_segment_id"), item.get("to_segment_id")): int(item.get("duration_frames", 0))
        for item in plan_data.get("transitions", [])
    }
    marks: list[tuple[float, float, str]] = []
    cursor = 0
    for index, segment in enumerate(segments):
        start = cursor
        duration_frames = round((float(segment.get("out", 0)) - float(segment.get("in", 0))) * fps)
        end = start + max(0, duration_frames)
        marks.append((start / fps, end / fps, segment["id"]))
        cursor = end
        if index < len(segments) - 1:
            cursor -= transitions.get((segment["id"], segments[index + 1]["id"]), 0)
    return marks, max(0, cursor) / fps


POSTER_RATING_VERSION = 2


def _apply_poster(plan_data: dict, analyses: list[dict]) -> None:
    """Pick the most hook-worthy caption for the poster image.

    Hook words (Persian negation/curiosity phrases) get the strongest bonus
    so sentences like «سرمایه اولیه نمیخواد» always beat generic ones like
    «کدوم رو انتخاب میکنید».
    """
    show_in_video = (plan_data.get("poster") or {}).get("show_in_video", True)
    plan_data.pop("cover", None)          # cover removed, poster only

    captions = plan_data.get("captions") or []
    segments = plan_data.get("segments") or []
    if not captions or not segments:
        plan_data.pop("poster", None)
        return

    ranges, output_duration = _output_segment_marks(plan_data)
    fps = max(1, int((plan_data.get("canvas") or {}).get("fps", 30)))
    analysis_by_id = {a.get("segment_id"): a for a in analyses}

    role_bonus = {"hook": 15, "claim": 12, "contrast": 10, "question": 12, "emotion": 8}
    semantic_hook_markers = (
        "لازم نیست", "نمیخواد", "نمی‌خواد", "نمیخواهد", "نمی‌خواهد", "نداره", "بدون",
        "چرا", "راز", "اشتباه",
    )

    def score_caption(caption: dict) -> tuple[int, dict]:
        text = " ".join(str(caption.get("text", "")).split())
        mid = (float(caption.get("start", 0)) + float(caption.get("end", 0))) / 2
        sid = next((s for a, b, s in reversed(ranges) if a - 1e-6 <= mid <= b + 1e-6), None)
        analysis = analysis_by_id.get(sid, {})
        words = text.split()
        score = int(analysis.get("shareability_score", 5)) * 2   # lowered weight
        score += role_bonus.get(analysis.get("role"), 0)
        # A question mark is only punctuation, not evidence that the sentence is
        # poster-worthy.  Questions already receive their role bonus above;
        # reserving this dominant bonus for meaningful hook language prevents a
        # generic question from outranking a concrete, surprising benefit.
        score += 50 if any(m in text for m in semantic_hook_markers) else 0
        score += 6 if 3 <= len(words) <= 7 else (-10 if len(words) > 10 or len(words) < 2 else 0)
        return score, analysis

    ranked = [(score_caption(c), i, c) for i, c in enumerate(captions) if str(c.get("text", "")).strip()]
    if not ranked:
        plan_data.pop("poster", None)
        return
    (best_score, analysis), best_idx, best = max(ranked, key=lambda r: (r[0][0], -r[1]))

    plan_data["poster"] = {
        "text": " ".join(str(best["text"]).split()),
        "frame_time": round(min(
            max((float(best.get("start", 0)) + float(best.get("end", 0))) / 2, 0.0),
            max(0.0, output_duration - 1 / fps),
        ), 3),
        "source_caption_index": best_idx,
        "rating_version": POSTER_RATING_VERSION,
        "show_in_video": show_in_video,
        "reason": (f"Hook score {best_score}: shareability "
                   f"{analysis.get('shareability_score', 5)}/10, role {analysis.get('role', 'unknown')}"),
    }


def refresh_stale_poster_rating(plan_data: dict) -> bool:
    """Apply the current deterministic poster scorer to an older saved plan."""
    poster = plan_data.get("poster") or {}
    if int(poster.get("rating_version") or 0) >= POSTER_RATING_VERSION:
        return False
    _apply_poster(plan_data, [])
    return True


def generate_plan_local(
    job,
    *,
    style: str = "rafiei_reel",
    output_kind: str = "reel",
    caption_font: Optional[str] = None,
    caption_font_id: Optional[str] = None,
    transition_style: str = "auto",
    transition_request: str = "",
    style_ref: Optional[dict] = None,
    duration: Optional[float] = None,
    reason: str = "no external LLM provider available",
    transcript: Optional[dict] = None,
) -> dict:
    """Build a one-scene plan (full video, original audio, no narration/SFX) without any LLM.

    Returns the same plan dict structure as the external provider path.
    """
    if duration is None:
        from engine.probe import probe_duration
        duration = probe_duration(job.dir / "raw" / job.raw_name)
    duration = float(duration)
    if duration <= 0:
        raise ValueError("source video has no positive duration")

    from .ai_provider import LocalFallbackProvider
    plan_data, _usage = LocalFallbackProvider(reason).generate_plan({
        "duration": duration,
        "source_rel": f"raw/{job.raw_name}",
        "preset_name": style,
        "output_kind": output_kind,
        "caption_font": caption_font,
        "caption_font_id": caption_font_id,
        "transition_style": transition_style,
        "transition_request": transition_request,
        "style_ref": style_ref,
    }, transcript or {"duration": duration})
    if transcript and _trim_incomplete_source_tail(plan_data, transcript):
        _clamp_output_events(plan_data)
    _apply_poster(plan_data, [])
    return plan_data


def generate_plan(
    job_dir: Path,
    transcript: dict,
    keep_ranges: list[tuple[float, float]],
    remove_ranges: list[tuple[float, float]],
    source_rel: str,
    preset_name: str = "rafiei_reel",
    instruction: str = "",
    caption_font: Optional[str] = None,
    caption_font_id: Optional[str] = None,
    style_profile: Optional[dict] = None,
    style_ref: Optional[dict] = None,
    learned_profile: Optional[dict] = None,
    locked_transitions: Optional[list[dict]] = None,
    output_kind: str = "reel",
    transition_request: str = "",
    transition_style: str = "auto",
    max_retries: int = 3,
    on_progress: Optional[callable] = None,
) -> tuple[dict, LLMUsage]:
    """Generate and validate an edit plan using the LLM.

    Returns (plan_dict, total_usage). Retries up to *max_retries* on validation failure.

    V2 improvements:
    - Segment analysis (role/energy/emotion) runs before effect selection
    - Effect scorer picks top-3 families per segment, LLM chooses from those
    - Critic pass fixes obvious pacing issues (same family twice, static overrun)
    """
    preset = _load_preset(preset_name)
    if style_profile:
        from engine.style_library import _deep_merge
        preset = _deep_merge(preset, {k: v for k, v in style_profile.items() if k != "learned"})

    # Stage 5: overlay learned style profile if available and no explicit style pinned
    learned_few_shot = []
    if not style_profile:
        try:
            from brain.style_profile import merge_with_preset
            learned = learned_profile
            if learned and learned.get("enabled", True) and learned.get("learned_metrics", {}).get("sufficient"):
                preset = merge_with_preset(preset, learned)
                learned_few_shot = learned.get("few_shot_examples", [])
                log.info("applied learned style profile (%d references)",
                         learned["learned_metrics"].get("sample_count", 0))
        except Exception as exc:
            log.warning("learned style profile load failed: %s", exc)

    music_file = _find_asset(job_dir, "music")
    sfx_file = _find_asset(job_dir, "sfx")

    lang = transcript.get("language", "en")

    # Pass no analyses yet — LLM produces layout + segments first, effects second
    try:
        from engine.font_library import planner_font_options
        font_options = planner_font_options(persian=_is_persian(lang))
    except Exception as exc:
        log.warning("caption font inventory unavailable: %s", exc)
        font_options = []
    system_prompt = _build_system_prompt(preset, language=lang, analyses=None,
                                         font_options=font_options)

    # Stage 5: append few-shot examples from learned style
    if learned_few_shot:
        examples_text = "\n\n## Learned editing style examples\n"
        examples_text += "These examples show the user's preferred editing rhythm from their reference reels:\n"
        for ex in learned_few_shot[:3]:
            examples_text += (
                f"\n- Reference: {ex.get('source', 'unknown')} "
                f"({ex.get('total_duration', 0)}s, {ex.get('segment_count', 0)} segments, "
                f"avg cut {ex.get('avg_cut_length', 0)}s)\n"
            )
        examples_text += "\nMatch this pacing and cut rhythm in your plan."
        system_prompt += examples_text
    user_prompt = _build_user_prompt(
        transcript, keep_ranges, remove_ranges,
        source_rel, music_file, sfx_file, instruction, output_kind, transition_request,
        transition_style,
    )

    total_usage = LLMUsage()
    last_errors: list[str] = []
    provider = get_provider()
    provider_context = {
        "job_dir": str(job_dir),
        "duration": transcript.get("duration", 0),
        "source_rel": source_rel,
        "preset_name": preset_name,
        "output_kind": output_kind,
        "caption_font": caption_font,
        "caption_font_id": caption_font_id,
        "transition_style": transition_style,
        "transition_request": transition_request,
        "style_ref": style_ref,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }

    for attempt in range(1, max_retries + 1):
        if on_progress:
            on_progress(f"planning (attempt {attempt}/{max_retries})")

        if attempt > 1 and last_errors:
            user_prompt_with_errors = (
                user_prompt
                + f"\n\n## Previous attempt had validation errors — fix them:\n"
                + "\n".join(f"- {e}" for e in last_errors)
            )
        else:
            user_prompt_with_errors = user_prompt

        try:
            provider_context["user_prompt"] = user_prompt_with_errors
            plan_data, usage = provider.generate_plan(provider_context, transcript)
        except Exception as e:
            log.error("AI provider call failed (attempt %d): %s", attempt, e)
            last_errors = [str(e)]
            continue

        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.model = usage.model
        total_usage.elapsed_sec += usage.elapsed_sec

        # Provider-level connection/timeout handling returns the same validated
        # local plan used by the no-key path. Do not decorate it with hosted
        # analysis calls; it must remain a predictable zero-network fallback.
        if (plan_data.get("generation_meta") or {}).get("provider") == "local":
            if _trim_incomplete_source_tail(plan_data, transcript):
                _clamp_output_events(plan_data)
            _apply_poster(plan_data, [])
            plan, errors = validate_plan(plan_data, base_dir=job_dir, check_media=False)
            if errors:
                raise ValueError("; ".join(errors))
            return plan_data, total_usage

        # Clamp segment.out to source duration so renders never exceed it
        _clamp_segments(plan_data, job_dir, source_rel)
        _trim_incomplete_source_tail(plan_data, transcript)

        # --- Smarter effect selection (V2) ---
        segments = plan_data.get("segments", [])
        analyses: list[dict] = []
        if segments:
            if on_progress:
                on_progress("analysing segments…")
            try:
                # Measure audio signals per segment (loudness + speech rate)
                src_path = Path(source_rel) if Path(source_rel).is_absolute() else (job_dir / source_rel)
                try:
                    seg_signals = measure_segment_signals(src_path, segments, transcript)
                except Exception as sig_exc:
                    log.debug("signals measurement skipped: %s", sig_exc)
                    seg_signals = []

                analyses, anlys_usage = analyse_segments(
                    segments, transcript,
                    source_captions=plan_data.get("captions"),
                    signals=seg_signals,
                )
                total_usage.input_tokens += anlys_usage.input_tokens
                total_usage.output_tokens += anlys_usage.output_tokens
                total_usage.elapsed_sec += anlys_usage.elapsed_sec

                if on_progress:
                    on_progress("selecting effects…")
                eff_usage = _apply_scored_effects(plan_data, analyses, transcript, preset, raw_video=src_path)
                total_usage.input_tokens += eff_usage.input_tokens
                total_usage.output_tokens += eff_usage.output_tokens
                total_usage.elapsed_sec += eff_usage.elapsed_sec
            except Exception as exc:
                log.warning("smarter effect selection failed: %s — using _ensure_visual_effects", exc)
                _ensure_visual_effects(plan_data)
        else:
            _ensure_visual_effects(plan_data)

        # The critic or a fallback plan can introduce an effect after scoring.
        # Keep explicit My Effects dislikes authoritative in the saved plan.
        from engine.effects_v4 import MyEffectsPreset
        my_effects = MyEffectsPreset()
        _enforce_selected_effect(plan_data, my_effects.selected_rafiei_style)
        _enforce_effect_dislikes(plan_data, my_effects.dislikes)

        _suggest_transitions(plan_data, analyses, locked_transitions, output_kind,
                             transition_request, transition_style)
        _retime_for_transition_overlaps(plan_data)
        _clamp_output_events(plan_data)
        _apply_poster(plan_data, analyses)
        if caption_font:
            plan_data.setdefault("canvas", {})["caption_font"] = caption_font
        if caption_font_id:
            from engine.font_library import resolve_font
            selected_font = resolve_font(caption_font_id)
            plan_data.setdefault("canvas", {})["caption_font_id"] = caption_font_id
            plan_data["canvas"]["caption_font"] = selected_font["family"]
        if style_ref:
            plan_data["style_profile"] = dict(style_ref)
        plan_data.setdefault("style", preset_name)
        plan_data["caption_review"] = _caption_review(plan_data, transcript)

        plan, errors = validate_plan(plan_data, base_dir=job_dir, check_media=False)

        media_warnings = _check_media_soft(plan_data, job_dir)

        if not errors:
            log.info("plan validated on attempt %d", attempt)
            if media_warnings:
                log.warning("media warnings: %s", media_warnings)

            # Stage 3: resolve broll queries + missing music/sfx from library
            try:
                from .asset_match import resolve_plan_assets
                resolutions = resolve_plan_assets(plan_data, base_dir=job_dir)
                resolved_count = len(resolutions.get("broll", []))
                if resolved_count:
                    log.info("resolved %d broll queries from library", resolved_count)
            except Exception as exc:
                log.warning("asset resolution skipped: %s", exc)

            # A selected empty/corrupt optional track should not turn a valid
            # generated edit into a late MLT/ffprobe failure. Keep valid user
            # assets untouched; omit only tracks that cannot be decoded.
            music = plan_data.get("music")
            if music and music.get("file"):
                music_path = Path(music["file"])
                if not music_path.is_absolute():
                    job_local = Path(job_dir) / music_path
                    music_path = job_local if job_local.exists() else PROJECT_ROOT / music_path
                if not _usable_audio_asset(music_path):
                    plan_data["music"] = None
                    plan_data.setdefault("asset_warnings", []).append(
                        "Music was omitted because the selected file has no decodable audio stream."
                    )
                    log.warning("omitted unusable optional music file %s", music_path)

            valid_sfx = []
            for sound in plan_data.get("sfx", []):
                sfx_path = Path(sound.get("file", ""))
                if not sfx_path.is_absolute():
                    job_local = Path(job_dir) / sfx_path
                    sfx_path = job_local if job_local.exists() else PROJECT_ROOT / sfx_path
                if _usable_audio_asset(sfx_path):
                    valid_sfx.append(sound)
                else:
                    plan_data.setdefault("asset_warnings", []).append(
                        f"SFX at {sound.get('at', '?')}s was omitted because its file has no decodable audio stream."
                    )
                    log.warning("omitted unusable optional SFX file %s", sfx_path)
            plan_data["sfx"] = valid_sfx

            return plan_data, total_usage

        log.warning("plan invalid (attempt %d): %s", attempt, errors)
        last_errors = errors

    raise ValueError(
        f"Failed to generate a valid plan after {max_retries} attempts. "
        f"Final errors: {'; '.join(last_errors)}"
    )


def _clamp_segments(plan_data: dict, job_dir: Path, source_rel: str) -> None:
    """Clamp segment.out to source file duration (in-place)."""
    src = Path(source_rel)
    src_path = src if src.is_absolute() else (job_dir / src)
    if not src_path.exists():
        return
    try:
        from engine.probe import probe_duration
        src_dur = probe_duration(src_path)
    except Exception:
        return
    for seg in plan_data.get("segments", []):
        seg_in = seg.get("in", 0)
        seg_out = seg.get("out", 0)
        if seg_out > src_dur:
            seg["out"] = round(src_dur, 6)
        if seg_in > src_dur:
            seg["in"] = round(src_dur, 6)


def _trim_incomplete_source_tail(plan_data: dict, transcript: dict) -> bool:
    """Omit a source-truncated final thought when a completed sentence precedes it.

    Only act when both the last recognized word and the unfinished sentence
    reach the recording's end. A deliberate edit that already stops earlier is
    left alone. This does not try to repair missing speech in the source.
    """
    sentences = transcript.get("sentences") or []
    words = transcript.get("words") or []
    segments = plan_data.get("segments") or []
    duration = float(transcript.get("duration") or 0)
    if len(sentences) < 2 or not words or not segments or duration <= 0:
        return False
    last = sentences[-1]
    text = str(last.get("text") or "").rstrip(" \t\n\r\"'»”")
    if not text or text.endswith((".", "!", "?", "؟", "۔")):
        return False
    if abs(duration - float(last.get("end") or 0)) > 0.15 or abs(duration - float(words[-1].get("end") or 0)) > 0.15:
        return False
    if float(segments[-1]["out"]) < float(last.get("start") or 0) + 0.15:
        return False
    previous = sentences[-2]
    previous_text = str(previous.get("text") or "").rstrip(" \t\n\r\"'»”")
    if not previous_text.endswith((".", "!", "?", "؟", "۔")):
        return False
    cut_at = float(previous.get("end") or 0)
    fps = int((plan_data.get("canvas") or {}).get("fps", 30))
    if fps <= 0 or cut_at <= 0 or cut_at > float(last.get("start") or 0):
        return False
    kept = []
    for segment in segments:
        if float(segment["in"]) >= cut_at - 1 / fps:
            break
        item = dict(segment)
        item["out"] = min(float(item["out"]), cut_at)
        if round((item["out"] - float(item["in"])) * fps) >= 1:
            kept.append(item)
    if not kept or kept[-1]["out"] >= segments[-1]["out"]:
        return False
    plan_data["segments"] = kept
    ids = {segment["id"] for segment in kept}
    plan_data["visual_effects"] = [effect for effect in plan_data.get("visual_effects", [])
                                   if effect.get("segment_id") in ids]
    if (plan_data.get("cover") or {}).get("source_segment_id") not in ids:
        plan_data.pop("cover", None)
    log.info("trimmed source-truncated final thought at %.3fs", cut_at)
    return True


def _clamp_output_events(plan_data: dict) -> None:
    """Trim model output events to the duration of its kept source segments."""
    fps = int((plan_data.get("canvas") or {}).get("fps", 30))
    duration = sum(round((s["out"] - s["in"]) * fps) for s in plan_data.get("segments", [])) / fps
    duration -= sum(int(t.get("duration_frames", 0)) for t in plan_data.get("transitions", [])) / fps
    for key in ("captions",):
        events = []
        for event in plan_data.get(key, []):
            if event["start"] >= duration:
                continue
            event["end"] = round(min(event["end"], duration), 3)
            if event["end"] > event["start"]:
                events.append(event)
        plan_data[key] = events
    if plan_data.get("music"):
        ducks = []
        for duck in plan_data["music"].get("duck", []):
            if duck["start"] >= duration:
                continue
            duck["end"] = round(min(duck["end"], duration), 3)
            if duck["end"] > duck["start"]:
                ducks.append(duck)
        plan_data["music"]["duck"] = ducks
    plan_data["broll"] = [item for item in plan_data.get("broll", []) if item["at"] < duration]
    for broll in plan_data["broll"]:
        broll["duration"] = round(max(0.001, min(broll["duration"], duration - broll["at"])), 3)
    plan_data["sfx"] = [item for item in plan_data.get("sfx", []) if item["at"] < duration]


def _check_media_soft(plan_data: dict, job_dir: Path) -> list[str]:
    """Non-fatal media checks (files may not exist yet for B-roll)."""
    warnings = []
    source = plan_data.get("source", "")
    sp = Path(source) if Path(source).is_absolute() else (job_dir / source)
    if not sp.exists():
        warnings.append(f"source not found: {source}")
    return warnings
