"""Automatic transcript correction: detect suspect words + one LLM call to fix them.

Pipeline position: transcribe → auto_correct → silence → plan → captions.

The LLM receives only the flagged word indices and their surrounding context.
It returns structured JSON [{index, old, new, confidence, reason}].
High-confidence fixes are applied automatically via save_corrections().
Lower-confidence items are stored as suggestions for manual review.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import yaml

from .llm import LLMUsage, chat_json

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def normalize_persian(text: str) -> str:
    """Normalize Arabic-script look-alikes to standard Persian."""
    return (
        text
        .replace("ي", "ی")  # Arabic ي → Persian ی
        .replace("ى", "ی")  # Arabic alef maqsura → Persian ی
        .replace("ك", "ک")  # Arabic ك → Persian ک
        .replace("ي", "ی")
        .replace("ك", "ک")
    )


def load_glossary(path: Optional[Path] = None) -> dict:
    """Load glossary.yaml. Returns {} if the file does not exist."""
    if path is None:
        path = PROJECT_ROOT / "presets" / "glossary.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.warning("could not load glossary %s: %s", path, e)
        return {}


def detect_suspect_words(
    words: list[dict],
    threshold: float,
    glossary: dict,
) -> list[dict]:
    """Return [{index, word, reasons}] for words that need review.

    Flags words whose Whisper probability is below *threshold* or whose
    normalized form appears in the glossary's known-error table.
    Skips words already marked *reviewed* by a human.
    """
    corrections_map: dict[str, str] = {
        normalize_persian(bad).lower(): normalize_persian(good)
        for bad, good in (glossary.get("corrections") or {}).items()
    }

    flagged: list[dict] = []
    for i, w in enumerate(words):
        if w.get("reviewed"):
            continue
        reasons: list[str] = []

        if w.get("prob", 1.0) < threshold:
            reasons.append(f"low_prob:{w.get('prob', 0):.2f}")

        norm = normalize_persian(w["w"]).lower().strip(".,،؛:!؟?\"'")
        if norm in corrections_map:
            reasons.append(f"known_error→{corrections_map[norm]}")

        if reasons:
            flagged.append({"index": i, "word": w["w"], "reasons": reasons})

    return flagged


def _build_prompts(
    transcript: dict,
    flagged: list[dict],
    glossary: dict,
) -> tuple[str, str]:
    """Build (system, user) prompts for the LLM correction call."""
    lang = transcript.get("language", "unknown")
    words = transcript.get("words", [])

    vocab = list(glossary.get("vocabulary") or [])
    corrections_map = glossary.get("corrections") or {}

    glossary_lines: list[str] = []
    if vocab:
        glossary_lines.append("Known correct terms: " + ", ".join(str(t) for t in vocab[:60]))
    if corrections_map:
        glossary_lines.append(
            "Known fixes: "
            + "; ".join(f"{b}→{g}" for b, g in list(corrections_map.items())[:30])
        )
    glossary_block = ("\n\n## Glossary\n" + "\n".join(glossary_lines)) if glossary_lines else ""

    system = f"""You are a transcript correction assistant for {lang} audio.
Fix ONLY the flagged words. Do not alter any unflagged word or sentence structure.
Rules:
- Correct only clear mis-transcriptions (acoustic confusions, wrong script).
- Never change meaning, add words, or remove words.
- For Persian: use standard Persian characters (ی not ي, ک not ك). Keep ZWNJ (نیم‌فاصله U+200C) where appropriate.
- Confidence 1.0 = certain; 0.0 = pure guess. Be conservative — prefer lower confidence.
- If a flagged word actually looks correct, return confidence 0.0 and explain.
- Never fabricate words not present in the audio context.
{glossary_block}

Output exactly this JSON, no markdown, no explanation:
{{"corrections": [{{"index": <int>, "old": "<original>", "new": "<corrected>", "confidence": <0.0-1.0>, "reason": "<one sentence>"}}]}}"""

    context_lines: list[str] = []
    for item in flagged:
        i = item["index"]
        start = max(0, i - 4)
        end = min(len(words), i + 5)
        ctx = []
        for j, w in enumerate(words[start:end], start=start):
            if j == i:
                ctx.append(f">>>{j}:{w['w']}(p={w.get('prob', 1):.2f})<<<")
            else:
                ctx.append(f"{j}:{w['w']}")
        context_lines.append(
            f"  #{i} {item['word']!r} — {', '.join(item['reasons'])}\n"
            f"    context: {' '.join(ctx)}"
        )

    sentences_ctx = json.dumps(
        transcript.get("sentences", [])[:30], ensure_ascii=False
    )

    user = (
        f"Language: {lang}\n"
        f"Total words: {len(words)}\n\n"
        f"Flagged words:\n" + "\n".join(context_lines) + "\n\n"
        f"Sentences (for context):\n{sentences_ctx}\n\n"
        "Return the corrections JSON now."
    )

    return system, user


def auto_correct(
    transcript: dict,
    preset: dict,
    glossary: Optional[dict] = None,
    *,
    glossary_path: Optional[Path] = None,
) -> tuple[list[dict], LLMUsage]:
    """Detect suspect words and ask the LLM to fix them.

    Returns (corrections, usage) where each correction is:
        {index, old, new, confidence, reason}

    Does NOT apply corrections — the caller decides which to apply.
    Returns ([], LLMUsage()) when nothing is flagged or the call fails.
    """
    if glossary is None:
        glossary = load_glossary(glossary_path)

    correction_cfg = preset.get("correction") or {}
    threshold = float(correction_cfg.get("low_prob_threshold", 0.60))
    max_ratio = float(correction_cfg.get("max_flagged_ratio", 0.40))

    words = transcript.get("words") or []
    if not words:
        return [], LLMUsage()

    flagged = detect_suspect_words(words, threshold, glossary)

    if not flagged:
        log.info("auto_correct: no suspect words (threshold=%.2f)", threshold)
        return [], LLMUsage()

    ratio = len(flagged) / len(words)
    if ratio > max_ratio:
        log.warning(
            "auto_correct: %.0f%% words flagged — skipping LLM call "
            "(too noisy or wrong language detection)",
            ratio * 100,
        )
        return [], LLMUsage()

    log.info(
        "auto_correct: %d/%d words suspect (%.0f%%), calling LLM…",
        len(flagged), len(words), ratio * 100,
    )

    system, user = _build_prompts(transcript, flagged, glossary)

    try:
        raw, usage = chat_json(system, user, max_tokens=2048, temperature=0.0)
    except Exception as exc:
        log.error("auto_correct: LLM call failed: %s", exc)
        return [], LLMUsage()

    corrections: list[dict] = []
    seen: set[int] = set()
    for item in raw.get("corrections") or []:
        try:
            idx = int(item["index"])
            new_word = str(item.get("new") or "").strip()
            confidence = float(item.get("confidence", 0.5))
            reason = str(item.get("reason") or "")[:200]
            old_word = str(item.get("old") or (words[idx]["w"] if 0 <= idx < len(words) else ""))

            if idx in seen or not (0 <= idx < len(words)):
                continue
            if not new_word or len(new_word) > 120:
                continue
            if new_word == words[idx]["w"]:
                continue

            seen.add(idx)
            corrections.append({
                "index": idx,
                "old": old_word,
                "new": new_word,
                "confidence": round(min(1.0, max(0.0, confidence)), 3),
                "reason": reason,
            })
        except (KeyError, ValueError, TypeError):
            continue

    log.info("auto_correct: LLM proposed %d corrections", len(corrections))
    return corrections, usage
