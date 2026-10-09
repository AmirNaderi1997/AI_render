"""Segment analysis: classify each kept segment by role, energy, and emotion.

One LLM call for the whole video before effect selection. Returns structured
metadata the effect scorer uses to match family → segment meaning.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from .llm import LLMUsage, chat_json

log = logging.getLogger(__name__)

# Canonical role labels
ROLES = (
    "hook",          # opening hook, grab attention
    "claim",         # a stated fact or assertion
    "explanation",   # unpacking an idea
    "list_item",     # one item in a list/series
    "number",        # stat, metric, price
    "story",         # narrative moment
    "question",      # rhetorical or direct question
    "emotion",       # emotional peak, vulnerable moment
    "contrast",      # before/after, problem/solution setup
    "cta",           # call to action, directive
    "conclusion",    # wrapping up, summary
    "transition",    # bridging moment between ideas
)


def analyse_segments(
    segments: list[dict],
    transcript: dict,
    *,
    source_captions: Optional[list[dict]] = None,
    signals: Optional[list[dict]] = None,
) -> tuple[list[dict], LLMUsage]:
    """Classify each segment by role/energy/emotion using one LLM call.

    segments: list of {id, in, out} dicts from the plan
    transcript: effective_transcript dict
    source_captions: planned captions mapped to output timeline (optional, enriches context)

    Returns (analyses, usage) where each analysis is:
        {segment_id, role, energy, emotion, key_words, is_turning_point,
         shareability_score}
    Falls back to a heuristic if the LLM fails (never breaks the caller).
    """
    if not segments:
        return [], LLMUsage()

    # Map words to output segments for context
    seg_texts: list[dict] = []
    words = transcript.get("words", [])
    captions_by_seg: dict[str, list[str]] = {}
    if source_captions:
        out_acc = 0.0
        for seg in segments:
            dur = seg.get("out", 0) - seg.get("in", 0)
            seg_start_out = out_acc
            seg_end_out = out_acc + dur
            out_acc = seg_end_out
            captions_by_seg[seg["id"]] = [
                c["text"] for c in source_captions
                if c.get("start", 0) >= seg_start_out - 0.1
                and c.get("end", 0) <= seg_end_out + 0.1
            ]

    signals_map: dict[str, dict] = {}
    if signals:
        for sig in signals:
            signals_map[sig["segment_id"]] = sig

    for seg in segments:
        seg_in, seg_out = seg.get("in", 0), seg.get("out", 0)
        seg_words = [
            w["w"] for w in words
            if seg_in - 0.05 <= w.get("start", 0) <= seg_out + 0.05
        ]
        text = " ".join(seg_words)
        caps = captions_by_seg.get(seg["id"], [])
        sig = signals_map.get(seg["id"], {})
        entry: dict = {
            "id": seg["id"],
            "duration": round(seg_out - seg_in, 2),
            "text": text[:300],
            "captions": caps,
        }
        if sig.get("loudness_lufs") is not None:
            entry["loudness_lufs"] = sig["loudness_lufs"]
        if sig.get("speech_rate_wps") is not None:
            entry["speech_rate_wps"] = sig["speech_rate_wps"]
        seg_texts.append(entry)

    total_dur = sum(s.get("out", 0) - s.get("in", 0) for s in segments)
    lang = transcript.get("language", "unknown")

    has_signals = any("loudness_lufs" in s or "speech_rate_wps" in s for s in seg_texts)
    signals_note = (
        "\n  - loudness_lufs and speech_rate_wps (words/sec) are measured audio signals to help calibrate energy."
        if has_signals else ""
    )

    system = f"""Analyse each video segment for an editor.

Segments are from a {lang} video ({total_dur:.1f}s total output).
For each segment return a JSON analysis with:
  - role: one of {json.dumps(list(ROLES))}
  - energy: 1 (calm/quiet) to 5 (peak energy/impact)
  - emotion: one word (e.g. curious, assertive, warm, urgent, reflective, playful)
  - key_words: 1-3 most important words (in the source language)
  - is_turning_point: true if this is a structural shift (from problem→solution, question→answer, buildup→payoff){signals_note}
  - shareability_score: 1-10 for how strong this exact spoken idea is as a short cover hook. Reward a self-contained benefit, surprising contrast, curiosity, specificity, and emotional punch. Do not reward clickbait that is unsupported by the transcript.

Output ONLY this JSON:
{{"segments": [{{"id": "<seg_id>", "role": "<role>", "energy": <1-5>, "emotion": "<word>", "key_words": ["<w1>"], "is_turning_point": <bool>, "shareability_score": <1-10>}}]}}"""

    def _seg_line(s: dict) -> str:
        line = f"Segment {s['id']} ({s['duration']}s): {s['text']!r}"
        extras = []
        if s['captions']:
            extras.append(f"captions: {s['captions']}")
        if s.get("loudness_lufs") is not None:
            extras.append(f"loudness={s['loudness_lufs']} LUFS")
        if s.get("speech_rate_wps") is not None:
            extras.append(f"rate={s['speech_rate_wps']} w/s")
        if extras:
            line += "\n  " + ", ".join(extras)
        return line

    user = (
        f"Video language: {lang}, {len(segments)} segments, {total_dur:.1f}s total.\n\n"
        + "\n".join(_seg_line(s) for s in seg_texts)
        + "\n\nReturn the JSON analysis."
    )

    try:
        raw, usage = chat_json(system, user, max_tokens=1024, temperature=0.0,
                               timeout_seconds=300)
    except Exception as exc:
        log.warning("segment analysis LLM call failed: %s — using heuristic", exc)
        return _heuristic_analysis(segments, seg_texts), LLMUsage()

    result: list[dict] = []
    seen: set[str] = set()
    for item in raw.get("segments") or []:
        sid = str(item.get("id", ""))
        if sid in seen:
            continue
        seen.add(sid)
        result.append({
            "segment_id": sid,
            "role": item.get("role", "explanation") if item.get("role") in ROLES else "explanation",
            "energy": max(1, min(5, int(item.get("energy", 2)))),
            "emotion": str(item.get("emotion", "neutral"))[:30],
            "key_words": [str(w)[:40] for w in (item.get("key_words") or [])[:3]],
            "is_turning_point": bool(item.get("is_turning_point", False)),
            "shareability_score": max(1, min(10, int(item.get("shareability_score", 5)))),
        })

    # Fill in any segments the LLM missed
    covered = {a["segment_id"] for a in result}
    for seg, text_info in zip(segments, seg_texts):
        if seg["id"] not in covered:
            result.append(_heuristic_one(seg, text_info, len(result)))

    log.info("segment analysis: %d segments analysed", len(result))
    return result, usage


def _heuristic_one(seg: dict, text_info: dict, index: int) -> dict:
    dur = text_info["duration"]
    text = text_info["text"].lower()
    role = "cta" if index == -1 else ("hook" if index == 0 else "explanation")
    if "چرا" in text or "؟" in text or "?" in text:
        role = "question"
    if any(w in text for w in ("لازم نیست", "نداره", "رایگان")):
        role = "claim"
    shareability = 4
    if role in {"hook", "claim", "contrast", "question", "conclusion"}:
        shareability += 2
    if any(w in text for w in ("لازم نیست", "نمیخواد", "نمی‌خواد", "نداره", "بدون", "چرا", "راز")):
        shareability += 2
    word_count = len(text_info.get("text", "").split())
    if 3 <= word_count <= 9:
        shareability += 1
    return {
        "segment_id": seg["id"],
        "role": role,
        "energy": 3 if index == 0 else 2,
        "emotion": "neutral",
        "key_words": [],
        "is_turning_point": False,
        "shareability_score": min(10, shareability),
    }


def _heuristic_analysis(segments: list[dict], seg_texts: list[dict]) -> list[dict]:
    result = []
    for i, (seg, text_info) in enumerate(zip(segments, seg_texts)):
        idx = i if i < len(segments) - 1 else -1
        result.append(_heuristic_one(seg, text_info, idx))
    return result
