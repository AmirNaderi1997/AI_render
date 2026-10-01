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
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import yaml

from engine.schema import PROJECT_ROOT, EditPlan, format_error, validate_plan
from engine.effects import MOTIONS, LIGHTS, EFFECT_CATALOG, EFFECT_FAMILIES, families_for_llm
from .llm import LLMUsage, chat_json
from .segment_analysis import analyse_segments
from .effect_score import select_effects_with_llm, critic_effect_pass
from .signals import measure_segment_signals

log = logging.getLogger(__name__)


def _load_preset(name: str = "rafiei_reel") -> dict:
    p = PROJECT_ROOT / "presets" / f"{name}.yaml"
    return yaml.safe_load(p.read_text())


_PERSIAN_CODES = {"fa", "per", "fas", "persian", "farsi"}


def _is_persian(lang: str) -> bool:
    return lang.lower().strip() in _PERSIAN_CODES


def _build_system_prompt(preset: dict, language: str = "en", analyses: Optional[list[dict]] = None) -> str:
    persian = _is_persian(language)
    caption_lang_rule = (
        "\n- IMPORTANT: The video language is Persian (Farsi). Write ALL captions in Persian script "
        "(right-to-left, joined letters). Do NOT translate to English. "
        "Use Vazirmatn font. Each caption must be authentic Persian text from the transcript."
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
  "version": "0.2",
  "style": "rafiei_reel",
  "canvas": {{"width": 1080, "height": 1920, "fps": 30}},
  "source": "<relative path to raw video>",
  "segments": [
    {{"id": "s1", "in": <source_start_sec>, "out": <source_end_sec>,
      "zoom": {{"from": <1.0-1.20>, "to": <1.0-1.20>}}}}
  ],
  "visual_effects": [
    {{"segment_id": "s1", "type": "steady__neutral"}}
  ],
  "captions": [
    {{"start": <output_timeline_sec>, "end": <output_timeline_sec>,
      "text": "<2-5 words>", "style": "normal|emphasis|cta"}}
  ],
  "broll": [
    {{"at": <output_timeline_sec>, "duration": <sec>, "file": "broll/placeholder.mp4",
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
- Caption length: {preset.get("captions", {}).get("min_words", 2)}-{preset.get("captions", {}).get("max_words", 5)} words each{caption_lang_rule}
- Mark one emphasis caption per key point, one CTA caption at the end
- B-roll: ~{preset.get("broll", {}).get("default_duration_sec", 2.0)}s each, minimum {preset.get("broll", {}).get("min_gap_sec", 8.0)}s apart
- Place a whoosh SFX on each cut into B-roll
- Music ducks under all speech

## Content rules
- Drop retakes: when the speaker restarts a sentence, keep ONLY the last good take
- Drop false starts, fillers ("اِ", "uhm", "um", "hmm")
- Remove pauses already identified in the remove_ranges
- Segments use SOURCE timeline times (in/out refer to the raw video)
- Captions and B-roll use OUTPUT timeline times (after cuts/removals)
- The output timeline is the concatenation of kept segments in order

## Critical timing rules
- segment.in and segment.out are in SOURCE video time
- caption.start, caption.end, broll.at, sfx.at, music.duck are in OUTPUT timeline time
- To convert: for each word, find which kept segment it falls in, then compute
  output_time = sum(duration of all preceding segments) + (word_source_time - segment.in)
- Captions must align with the spoken words' output times
- Captions should quote kept speech faithfully. Never invent or change a claim to make it read better. If the transcript is uncertain, keep the uncertainty visible for review.
- The total output duration = sum of all segment durations
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
    ]

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


def _find_asset(job_dir: Path, kind: str) -> Optional[str]:
    """Find a music/sfx file in the job's asset directories or project samples."""
    search_dirs = [
        PROJECT_ROOT / "assets" / kind,
        PROJECT_ROOT / "samples" / "media",
    ]
    extensions = (".mp3", ".wav", ".ogg", ".m4a")
    for d in search_dirs:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in extensions:
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


def _apply_scored_effects(plan_data: dict, analyses: list[dict], transcript: dict, preset: dict) -> LLMUsage:
    """Run the effect scorer + critic pass, write results into plan_data in-place.

    Returns combined LLM usage from both calls.
    """
    segments = plan_data.get("segments", [])
    if not segments or not analyses:
        return LLMUsage()

    scored_effects, sel_usage = select_effects_with_llm(segments, analyses, transcript, preset)

    # Convert scorer output → plan visual_effects (strip private _family/_reason keys)
    total_dur = sum(s.get("out", 0) - s.get("in", 0) for s in segments)
    scored_effects, crit_usage = critic_effect_pass(scored_effects, analyses, total_dur, preset)

    plan_data["visual_effects"] = [
        {"segment_id": e["segment_id"], "type": e["type"]}
        for e in scored_effects
    ]
    # Save debug metadata separately so it doesn't fail schema validation
    plan_data["effect_analysis"] = [
        {
            "segment_id": e["segment_id"],
            "family": e.get("_family", ""),
            "reason": e.get("_reason", ""),
            "intensity": e.get("_intensity", 2),
            "emphasis_start": e.get("_emphasis_start"),
        }
        for e in scored_effects
    ]

    combined = LLMUsage()
    combined.input_tokens = sel_usage.input_tokens + crit_usage.input_tokens
    combined.output_tokens = sel_usage.output_tokens + crit_usage.output_tokens
    combined.model = sel_usage.model or crit_usage.model
    combined.elapsed_sec = sel_usage.elapsed_sec + crit_usage.elapsed_sec
    return combined


def generate_plan(
    job_dir: Path,
    transcript: dict,
    keep_ranges: list[tuple[float, float]],
    remove_ranges: list[tuple[float, float]],
    source_rel: str,
    preset_name: str = "rafiei_reel",
    instruction: str = "",
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

    music_file = _find_asset(job_dir, "music")
    sfx_file = _find_asset(job_dir, "sfx")

    lang = transcript.get("language", "en")

    # Pass no analyses yet — LLM produces layout + segments first, effects second
    system_prompt = _build_system_prompt(preset, language=lang, analyses=None)
    user_prompt = _build_user_prompt(
        transcript, keep_ranges, remove_ranges,
        source_rel, music_file, sfx_file, instruction,
    )

    total_usage = LLMUsage()
    last_errors: list[str] = []

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
            plan_data, usage = chat_json(system_prompt, user_prompt_with_errors)
        except Exception as e:
            log.error("LLM call failed (attempt %d): %s", attempt, e)
            last_errors = [str(e)]
            continue

        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.model = usage.model
        total_usage.elapsed_sec += usage.elapsed_sec

        # Clamp segment.out to source duration so renders never exceed it
        _clamp_segments(plan_data, job_dir, source_rel)

        # --- Smarter effect selection (V2) ---
        segments = plan_data.get("segments", [])
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
                eff_usage = _apply_scored_effects(plan_data, analyses, transcript, preset)
                total_usage.input_tokens += eff_usage.input_tokens
                total_usage.output_tokens += eff_usage.output_tokens
                total_usage.elapsed_sec += eff_usage.elapsed_sec
            except Exception as exc:
                log.warning("smarter effect selection failed: %s — using _ensure_visual_effects", exc)
                _ensure_visual_effects(plan_data)
        else:
            _ensure_visual_effects(plan_data)

        plan_data["caption_review"] = _caption_review(plan_data, transcript)

        plan, errors = validate_plan(plan_data, base_dir=job_dir, check_media=False)

        media_warnings = _check_media_soft(plan_data, job_dir)

        if not errors:
            log.info("plan validated on attempt %d", attempt)
            if media_warnings:
                log.warning("media warnings: %s", media_warnings)
            return plan_data, total_usage

        log.warning("plan invalid (attempt %d): %s", attempt, errors)
        last_errors = errors

    raise ValueError(
        f"Failed to generate a valid plan after {max_retries} attempts. "
        f"Last errors: {'; '.join(last_errors)}"
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


def _check_media_soft(plan_data: dict, job_dir: Path) -> list[str]:
    """Non-fatal media checks (files may not exist yet for B-roll)."""
    warnings = []
    source = plan_data.get("source", "")
    sp = Path(source) if Path(source).is_absolute() else (job_dir / source)
    if not sp.exists():
        warnings.append(f"source not found: {source}")
    return warnings
