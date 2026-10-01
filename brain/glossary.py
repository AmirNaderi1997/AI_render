"""Glossary learning: save accepted transcript corrections back to presets/glossary.yaml."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def save_correction_to_glossary(
    wrong: str,
    correct: str,
    *,
    glossary_path: Optional[Path] = None,
) -> bool:
    """Add a known-wrong → known-correct pair to glossary.yaml.

    Thread-safe via a simple re-read / write cycle (safe for single-process use).
    Returns True if the entry was added or already existed.
    """
    if not wrong or not correct or wrong.strip() == correct.strip():
        return False

    path = glossary_path or (PROJECT_ROOT / "presets" / "glossary.yaml")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:
        log.warning("could not read glossary: %s", exc)
        return False

    if not isinstance(raw, dict):
        raw = {}

    corrections = raw.get("corrections") or {}
    wrong_norm = wrong.strip()
    correct_norm = correct.strip()

    if corrections.get(wrong_norm) == correct_norm:
        return True  # already known

    corrections[wrong_norm] = correct_norm
    raw["corrections"] = corrections

    # Also add the correct form to vocabulary if not already there
    vocab = raw.get("vocabulary") or []
    if correct_norm not in vocab:
        vocab.append(correct_norm)
    raw["vocabulary"] = vocab

    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        tmp.replace(path)
        log.info("glossary: added %r → %r", wrong_norm, correct_norm)
        return True
    except Exception as exc:
        log.warning("could not write glossary: %s", exc)
        return False


def build_initial_prompt(glossary: dict, language: str = "fa") -> str:
    """Build a Whisper initial_prompt string from the glossary vocabulary.

    This seeds the ASR model with known good terms so it's less likely to
    mis-transcribe them. Only used when language matches the glossary.
    """
    if glossary.get("language", "fa") != language:
        return ""
    vocab = list(glossary.get("vocabulary") or [])
    if not vocab:
        return ""
    # Keep under ~100 chars so it doesn't dominate the attention window
    terms = ", ".join(str(t) for t in vocab[:20])
    return terms
