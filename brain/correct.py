"""Automatic transcript correction: detect suspect words + one LLM call to fix them.

Pipeline position: transcribe → auto_correct → silence → plan → captions.

V2 improvements over V1:
- Context-aware prompt: sends the full transcript sentence-by-sentence so the LLM
  can catch contextually wrong words (not just low-prob ones).
- Similarity guardrail: rejects fixes whose new word sounds too different from the
  original (prevents meaning changes).
- merge/split support: one Whisper word can be split into two, or two merged into one,
  with timing divided by character length.
- Guardrail: never rewrite more than 2 consecutive words in one correction.

The LLM returns:
    {"corrections": [{index, old, new, confidence, reason, type: replace|merge|split}]}

High-confidence fixes are applied automatically via save_corrections().
Lower-confidence items are stored as suggestions for manual review.
"""
from __future__ import annotations

import json
import logging
import math
import os
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
        .replace("ى", "ی")  # Arabic alef maqsura → ی
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


def _char_bigrams(text: str) -> set[str]:
    """Character bigrams for simple similarity check."""
    t = text.strip()
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i+2] for i in range(len(t) - 1)}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity on character bigrams, 0-1. Fast and language-agnostic."""
    bg_a = _char_bigrams(normalize_persian(a.lower()))
    bg_b = _char_bigrams(normalize_persian(b.lower()))
    if not bg_a and not bg_b:
        return 1.0
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


def is_acceptable_replacement(old: str, new: str, threshold: float = 0.25) -> bool:
    """Return True if the new word is acoustically plausible for the old one.

    A very low threshold (0.25) — just enough to reject wild hallucinations
    while allowing correct fixes like مخصول→محصول (Jaccard ~0.47) or
    فوشم→می‌فروشم (shares میم and فاء sounds, Jaccard ~0.17).
    Glossary fixes bypass this check (handled by caller).
    """
    if not old or not new:
        return False
    if old.strip() == new.strip():
        return False
    return _similarity(old, new) >= threshold


import re as _re

_LATIN_RE = _re.compile(r'[A-Za-z]')


def is_latin_word(text: str) -> bool:
    """True if the word contains any Latin letter (A-Z/a-z)."""
    return bool(_LATIN_RE.search(text))


def detect_suspect_words(
    words: list[dict],
    threshold: float,
    glossary: dict,
    *,
    language: str = "",
) -> list[dict]:
    """Return [{index, word, reasons}] for words needing review.

    Flags words whose Whisper probability is below *threshold* OR whose
    normalized form appears in the glossary's known-error table.
    For Persian transcripts, also flags Latin-script words (e.g. "rekord").
    Skips words already marked *reviewed* by a human.
    """
    corrections_map: dict[str, str] = {
        normalize_persian(bad).lower(): normalize_persian(good)
        for bad, good in (glossary.get("corrections") or {}).items()
    }
    is_persian = language.lower().strip() in ("fa", "per", "fas", "persian", "farsi")

    # Build set of allowed Latin words from glossary (brands/acronyms)
    latin_allowlist: set[str] = set()
    if is_persian:
        for term in (glossary.get("vocabulary") or []):
            if is_latin_word(str(term)):
                latin_allowlist.add(str(term).lower().strip())

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

        if "alt_w" in w and w["alt_w"] != w["w"]:
            reasons.append(f"decode_disagree:{w['alt_w']}")

        if is_persian and is_latin_word(w["w"]):
            stripped = w["w"].lower().strip(".,،؛:!؟?\"'")
            if stripped not in latin_allowlist:
                reasons.append("latin_in_persian")

        if reasons:
            flagged.append({"index": i, "word": w["w"], "reasons": reasons})

    return flagged


def _build_prompts(
    transcript: dict,
    flagged: list[dict],
    glossary: dict,
) -> tuple[str, str]:
    """Build (system, user) prompts.

    V2: sends full transcript sentences for context, not just flagged words.
    """
    lang = transcript.get("language", "unknown")
    words = transcript.get("words", [])
    sentences = transcript.get("sentences", [])

    vocab = list(glossary.get("vocabulary") or [])
    corrections_map = glossary.get("corrections") or {}

    glossary_lines: list[str] = []
    if vocab:
        glossary_lines.append("Known correct terms: " + ", ".join(str(t) for t in vocab[:60]))
    if corrections_map:
        glossary_lines.append(
            "Known wrong→right: "
            + "; ".join(f"{b}→{g}" for b, g in list(corrections_map.items())[:30])
        )
    glossary_block = ("\n\n## Glossary\n" + "\n".join(glossary_lines)) if glossary_lines else ""

    flagged_indices = {item["index"] for item in flagged}

    system = f"""You are a transcript correction assistant for {lang} audio.

Your job: find mis-transcribed words in the transcript and suggest corrections.

## What to look for
1. The explicitly flagged words (low probability or known errors).
2. ANY other word that clearly does not fit the sentence context — wrong homophone,
   broken name, split/merged word — even if Whisper was confident.

## Rules
- Fix ONLY individual words (or a merge/split of adjacent words). Do not rewrite clauses.
- Never change the meaning, tense, or language register.
- For Persian: use standard characters (ی not ي, ک not ك). Keep ZWNJ (نیم‌فاصله).
- For Persian transcripts: any word in Latin script (e.g. "rekord", "product") MUST be
  converted to its Persian equivalent (رکورد, محصول). Captions must never mix Latin words
  into RTL text unless the word is a real brand/acronym listed in the glossary.
- A fix must sound phonetically similar to the original — do not invent words.
- Confidence 0.0-1.0: 1.0 = certain, 0.5 = plausible, <0.5 = a guess.
  Be conservative — if unsure, confidence < 0.7.
- type field: "replace" (one word → one word), "split" (one word → two separate words),
  "merge" (two adjacent words → one word, use "index" for the first and "merge_next": true).
{glossary_block}

Output ONLY this JSON:
{{"corrections": [{{"index": <int>, "old": "<original>", "new": "<corrected>", "confidence": <0.0-1.0>, "reason": "<one sentence>", "type": "replace|split|merge"}}]}}"""

    # Build word-annotated sentence view for context
    # Show all sentences with word indices and probs
    sentence_lines: list[str] = []
    for sent in sentences[:30]:
        sent_words = [
            w for w in words
            if sent["start"] - 0.05 <= w.get("start", 0) <= sent["end"] + 0.05
        ]
        parts = []
        for w in sent_words:
            idx = words.index(w) if w in words else -1
            prob = w.get("prob", 1.0)
            flag = "⚑" if idx in flagged_indices else ""
            parts.append(f"{flag}[{idx}:{w['w']}(p={prob:.2f})]")
        sentence_lines.append(" ".join(parts))

    # Separate section listing just the pre-flagged words
    flag_lines: list[str] = []
    for item in flagged:
        i = item["index"]
        flag_lines.append(f"  #{i} {item['word']!r} — {', '.join(item['reasons'])}")

    user = (
        f"Language: {lang}, {len(words)} words total.\n\n"
        f"## Transcript (⚑ = pre-flagged)\n"
        + "\n".join(sentence_lines)
        + "\n\n## Pre-flagged words\n"
        + ("\n".join(flag_lines) if flag_lines else "  (none)")
        + "\n\nReturn the corrections JSON, covering both flagged words AND any "
          "contextually wrong words you find in the full transcript."
    )

    return system, user


def _apply_merge_split(
    words: list[dict],
    item: dict,
) -> list[dict] | None:
    """Expand a merge/split correction into a list of save_corrections-compatible items.

    Returns None if the item should be skipped (invalid indices or no change).
    """
    correction_type = item.get("type", "replace")
    idx = item["index"]
    new_word = item["new"].strip()

    if not (0 <= idx < len(words)):
        return None

    if correction_type == "split":
        # One word split into two: divide the time range by character length
        parts = new_word.split(None, 1)
        if len(parts) < 2:
            return [{"index": idx, "text": new_word}]
        orig = words[idx]
        total_chars = sum(len(p) for p in parts)
        if total_chars == 0:
            return None
        start, end = orig["start"], orig["end"]
        mid = start + (end - start) * len(parts[0]) / total_chars
        return [{
            "index": idx, "text": parts[0], "start": start, "end": round(mid, 3),
            "insert_after": {"text": parts[1], "start": round(mid, 3), "end": round(end, 3)},
        }]

    if correction_type == "merge":
        # Two adjacent words merged: union of time ranges
        if idx + 1 >= len(words):
            return [{"index": idx, "text": new_word}]
        orig_a = words[idx]
        orig_b = words[idx + 1]
        merged_start = orig_a["start"]
        merged_end = orig_b["end"]
        return [
            {"index": idx, "text": new_word, "start": merged_start, "end": round(merged_end, 3)},
            {"index": idx + 1, "delete": True},
        ]

    # replace (default)
    return [{"index": idx, "text": new_word}]


def _call_correction_llm(
    system: str, user: str, model: Optional[str],
    max_retries: int = 2,
) -> tuple[Optional[dict], LLMUsage]:
    """Call LLM for correction with retry. Returns (parsed_response, usage)."""
    total_usage = LLMUsage()
    for attempt in range(1, max_retries + 1):
        try:
            kwargs = {"max_tokens": 2048, "temperature": 0.0}
            if model:
                kwargs["model"] = model
            provider = _correction_provider()
            if provider:
                kwargs["provider"] = provider
            kwargs["timeout_seconds"] = _correction_timeout_seconds()
            raw, usage = chat_json(system, user, **kwargs)
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.model = usage.model
            total_usage.elapsed_sec += usage.elapsed_sec

            if not raw or (isinstance(raw, dict) and not raw.get("corrections") and raw.get("corrections") != []):
                if attempt < max_retries:
                    log.warning("auto_correct: empty response (attempt %d/%d), retrying…", attempt, max_retries)
                    continue
                log.warning("auto_correct: empty response after %d attempts", max_retries)
            return raw, total_usage
        except Exception as exc:
            total_usage.model = model or ""
            if _is_timeout_error(exc):
                log.warning("auto_correct: LLM call timed out; continuing without optional corrections")
                return None, total_usage
            if attempt < max_retries:
                log.warning("auto_correct: LLM call failed (attempt %d/%d): %s — retrying…", attempt, max_retries, exc)
                continue
            log.error("auto_correct: LLM call failed after %d attempts: %s", max_retries, exc)
            return None, total_usage
    return None, total_usage


def _correction_timeout_seconds() -> float:
    """Keep optional transcript correction bounded independently from planning."""
    default_timeout = 300.0
    try:
        raw = os.getenv("AI_CORRECTION_TIMEOUT_SECONDS")
        if raw is None:
            raw = os.getenv("AI_PROVIDER_TIMEOUT_SECONDS", str(default_timeout))
        timeout = float(raw)
    except (TypeError, ValueError):
        return default_timeout
    if not math.isfinite(timeout) or timeout <= 0:
        return default_timeout
    return min(timeout, 600.0)


def _is_timeout_error(error: BaseException) -> bool:
    """Recognize built-in and common SDK timeout exceptions without SDK imports."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = type(current).__name__.lower()
        if isinstance(current, TimeoutError) or "timeout" in name or "timedout" in name:
            return True
        current = current.__cause__ or current.__context__
    return False


def _auto_correct_chunked(
    transcript: dict,
    all_flagged: list[dict],
    glossary: dict,
    preset: dict,
    model: Optional[str],
    sim_threshold: float,
) -> tuple[list[dict], LLMUsage]:
    """Run correction in chunks of _CHUNK_SIZE words for long transcripts."""
    words = transcript["words"]
    total_usage = LLMUsage()
    all_corrections: list[dict] = []

    flagged_by_idx = {f["index"]: f for f in all_flagged}

    for chunk_start in range(0, len(words), _CHUNK_SIZE):
        chunk_end = min(chunk_start + _CHUNK_SIZE, len(words))
        chunk_words = words[chunk_start:chunk_end]

        chunk_sentences = [
            s for s in transcript.get("sentences", [])
            if any(chunk_start <= i < chunk_end
                   for i, w in enumerate(words)
                   if s["start"] - 0.05 <= w.get("start", 0) <= s["end"] + 0.05)
        ]
        chunk_flagged = [f for f in all_flagged if chunk_start <= f["index"] < chunk_end]

        chunk_transcript = {
            **transcript,
            "words": chunk_words,
            "sentences": chunk_sentences,
        }

        # Remap flagged indices to chunk-local indices for the prompt
        local_flagged = [
            {**f, "index": f["index"] - chunk_start}
            for f in chunk_flagged
        ]

        system, user = _build_prompts(chunk_transcript, local_flagged, glossary)
        raw, usage = _call_correction_llm(system, user, model)
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        total_usage.model = usage.model
        total_usage.elapsed_sec += usage.elapsed_sec

        if raw and raw.get("corrections"):
            for item in raw["corrections"]:
                try:
                    item["index"] = int(item["index"]) + chunk_start
                except (KeyError, ValueError, TypeError):
                    continue
            # Filter and validate using the same logic as the main function
            # (delegated back via the caller's processing)
            all_corrections.extend(raw["corrections"])

    # Re-use the main validation logic by constructing a fake raw response
    log.info("auto_correct chunked: %d total corrections from %d chunks",
             len(all_corrections), (len(words) + _CHUNK_SIZE - 1) // _CHUNK_SIZE)

    # Run the same validation as the non-chunked path
    corrections_map = {
        normalize_persian(bad).lower(): normalize_persian(good)
        for bad, good in (glossary.get("corrections") or {}).items()
    }
    validated = _validate_corrections(all_corrections, words, corrections_map, sim_threshold)
    return validated, total_usage


def _validate_corrections(
    raw_corrections: list[dict],
    words: list[dict],
    corrections_map: dict[str, str],
    sim_threshold: float,
) -> list[dict]:
    """Validate and deduplicate correction items."""
    corrections: list[dict] = []
    seen: set[int] = set()
    for item in raw_corrections:
        try:
            idx = int(item["index"])
            new_word = str(item.get("new") or "").strip()
            confidence = float(item.get("confidence", 0.5))
            reason = str(item.get("reason") or "")[:200]
            correction_type = str(item.get("type") or "replace").lower()
            old_word = str(item.get("old") or (words[idx]["w"] if 0 <= idx < len(words) else ""))

            if idx in seen or not (0 <= idx < len(words)):
                continue
            if not new_word or len(new_word) > 200:
                continue
            if new_word == words[idx]["w"]:
                continue

            norm_old = normalize_persian(old_word).lower()
            is_glossary_fix = norm_old.strip(".,،؛:!؟?\"'") in corrections_map
            if (not is_glossary_fix
                    and correction_type == "replace"
                    and not is_acceptable_replacement(old_word, new_word, sim_threshold)):
                confidence = min(confidence, 0.5)

            seen.add(idx)
            corrections.append({
                "index": idx,
                "old": old_word,
                "new": new_word,
                "confidence": round(min(1.0, max(0.0, confidence)), 3),
                "reason": reason,
                "type": correction_type if correction_type in ("replace", "split", "merge") else "replace",
            })
        except (KeyError, ValueError, TypeError):
            continue
    return corrections


def _correction_model() -> Optional[str]:
    """Return CORRECTION_MODEL from env, or None to use the default LLM_MODEL."""
    import os
    return os.environ.get("CORRECTION_MODEL") or None


def _correction_provider() -> Optional[str]:
    """Use a provider dedicated to correction when configured."""
    provider = os.environ.get("CORRECTION_PROVIDER", "").strip().lower()
    return provider or None


_CHUNK_SIZE = 200  # max words per LLM correction call


def auto_correct(
    transcript: dict,
    preset: dict,
    glossary: Optional[dict] = None,
    *,
    glossary_path: Optional[Path] = None,
) -> tuple[list[dict], LLMUsage]:
    """Detect suspect words and ask the LLM to fix them (V2: context-aware).

    Returns (corrections, usage) where each correction is:
        {index, old, new, confidence, reason, type}

    Does NOT apply corrections — the caller decides which to apply.
    Returns ([], LLMUsage()) when nothing is flagged or the call fails.
    """
    if glossary is None:
        glossary = load_glossary(glossary_path)

    correction_cfg = preset.get("correction") or {}
    threshold = float(correction_cfg.get("low_prob_threshold", 0.60))
    max_ratio = float(correction_cfg.get("max_flagged_ratio", 0.40))
    sim_threshold = float(correction_cfg.get("similarity_threshold", 0.20))

    words = transcript.get("words") or []
    if not words:
        return [], LLMUsage()

    lang = transcript.get("language", "")
    flagged = detect_suspect_words(words, threshold, glossary, language=lang)
    ratio = len(flagged) / len(words)

    if ratio > max_ratio:
        log.warning(
            "auto_correct: %.0f%% words flagged — skipping LLM call (too noisy/wrong language)",
            ratio * 100,
        )
        return [], LLMUsage()

    model = _correction_model()
    log.info(
        "auto_correct V2: %d/%d pre-flagged (%.0f%%), model=%s, sending full context to LLM…",
        len(flagged), len(words), ratio * 100, model or "(default)",
    )

    if len(words) > _CHUNK_SIZE:
        return _auto_correct_chunked(transcript, flagged, glossary, preset, model, sim_threshold)

    system, user = _build_prompts(transcript, flagged, glossary)

    raw, usage = _call_correction_llm(system, user, model)
    if raw is None:
        return [], usage

    corrections_map = {
        normalize_persian(bad).lower(): normalize_persian(good)
        for bad, good in (glossary.get("corrections") or {}).items()
    }

    corrections: list[dict] = []
    seen: set[int] = set()

    for item in raw.get("corrections") or []:
        try:
            idx = int(item["index"])
            new_word = str(item.get("new") or "").strip()
            confidence = float(item.get("confidence", 0.5))
            reason = str(item.get("reason") or "")[:200]
            correction_type = str(item.get("type") or "replace").lower()
            old_word = str(item.get("old") or (words[idx]["w"] if 0 <= idx < len(words) else ""))

            if idx in seen or not (0 <= idx < len(words)):
                continue
            if not new_word or len(new_word) > 200:
                continue
            if new_word == words[idx]["w"]:
                continue

            # Similarity guardrail: skip fixes that sound completely different
            # (unless it's a known glossary fix, which is trusted)
            norm_old = normalize_persian(old_word).lower()
            is_glossary_fix = norm_old.strip(".,،؛:!؟?\"'") in corrections_map
            if (not is_glossary_fix
                    and correction_type == "replace"
                    and not is_acceptable_replacement(old_word, new_word, sim_threshold)):
                log.debug(
                    "similarity guard rejected: %r → %r (sim=%.2f < %.2f)",
                    old_word, new_word,
                    _similarity(old_word, new_word), sim_threshold,
                )
                confidence = min(confidence, 0.5)  # keep as low-confidence suggestion

            seen.add(idx)
            corrections.append({
                "index": idx,
                "old": old_word,
                "new": new_word,
                "confidence": round(min(1.0, max(0.0, confidence)), 3),
                "reason": reason,
                "type": correction_type if correction_type in ("replace", "split", "merge") else "replace",
            })
        except (KeyError, ValueError, TypeError):
            continue

    log.info("auto_correct: LLM proposed %d corrections", len(corrections))
    return corrections, usage


def expand_corrections_for_save(
    corrections: list[dict],
    words: list[dict],
) -> list[dict]:
    """Expand merge/split corrections into save_corrections-compatible items.

    Returns a flat list of {index, text, start?, end?} items.
    """
    items: list[dict] = []
    seen: set[int] = set()
    for correction in corrections:
        if correction.get("type") in ("split", "merge"):
            expanded = _apply_merge_split(words, correction)
            if expanded:
                for item in expanded:
                    if item["index"] not in seen:
                        seen.add(item["index"])
                        items.append(item)
        else:
            idx = correction["index"]
            if idx not in seen:
                seen.add(idx)
                items.append({"index": idx, "text": correction["new"]})
    return items
