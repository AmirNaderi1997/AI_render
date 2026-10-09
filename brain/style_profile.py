"""Style profile builder — aggregates multiple reference analyses into one profile.

Merges with rafiei_reel.yaml as base, overriding only metrics with enough
references (>=3 samples by default). Generates few-shot examples for the planner.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

import yaml

from engine.schema import PROJECT_ROOT

log = logging.getLogger(__name__)

STYLE_DIR = PROJECT_ROOT / "jobs" / "style-library"
LEARNED_PROFILES_DIR = STYLE_DIR / "learned"
LEARNED_PROFILES_DIR.mkdir(parents=True, exist_ok=True)

MIN_REFERENCES = 3


def _load_base_preset() -> dict:
    return yaml.safe_load((PROJECT_ROOT / "presets" / "rafiei_reel.yaml").read_text())


def aggregate_analyses(analyses: list[dict], min_references: int = MIN_REFERENCES) -> dict:
    """Aggregate multiple reference reel analyses into a merged profile.

    Returns a dict with averaged metrics and confidence scores.
    Only overrides defaults when len(analyses) >= min_references.
    """
    n = len(analyses)
    if n == 0:
        return {"metrics": {}, "confidence": {}, "sample_count": 0, "sufficient": False}

    sufficient = n >= min_references

    def avg(key_path: str) -> Optional[float]:
        values = []
        for a in analyses:
            obj = a
            for k in key_path.split("."):
                if isinstance(obj, dict):
                    obj = obj.get(k)
                else:
                    obj = None
            if obj is not None and isinstance(obj, (int, float)) and math.isfinite(obj):
                values.append(float(obj))
        return round(sum(values) / len(values), 3) if values else None

    metrics = {
        "cut_length_avg": avg("cut_lengths.avg"),
        "cut_length_min": avg("cut_lengths.min"),
        "cut_length_max": avg("cut_lengths.max"),
        "cut_length_median": avg("cut_lengths.median"),
        "cuts_per_minute": round(
            sum(a.get("cut_count", 0) for a in analyses)
            / max(1.0, sum(
                d for a in analyses
                if isinstance((d := a.get("total_duration", 60)), (int, float))
                and math.isfinite(d) and d > 0
            )) * 60, 2
        ),
        "pacing_early_avg": avg("pacing.early_avg"),
        "pacing_mid_avg": avg("pacing.mid_avg"),
        "pacing_late_avg": avg("pacing.late_avg"),
        "audio_mean_volume_db": avg("audio.mean_volume_db"),
        "caption_density_wps": avg("estimated_caption_density_wps"),
    }

    # Confidence: higher with more samples, capped at 1.0
    base_conf = min(1.0, n / 5)
    confidence = {k: round(base_conf, 2) for k in metrics if metrics[k] is not None}

    # Pacing trend: majority vote
    trends = [a.get("pacing", {}).get("trend", "unknown") for a in analyses]
    trend_counts = {}
    for t in trends:
        trend_counts[t] = trend_counts.get(t, 0) + 1
    dominant_trend = max(trend_counts, key=trend_counts.get) if trend_counts else "unknown"
    metrics["pacing_trend"] = dominant_trend

    return {
        "metrics": {k: v for k, v in metrics.items() if v is not None},
        "confidence": confidence,
        "sample_count": n,
        "sufficient": sufficient,
        "source_files": [a.get("source_file", "unknown") for a in analyses],
    }


def build_learned_profile(
    analyses: list[dict],
    min_references: int = MIN_REFERENCES,
) -> dict:
    """Build a learned style profile that can overlay the default preset.

    Returns a dict with:
    - preset_overrides: keys to merge into rafiei_reel.yaml
    - learned_metrics: raw aggregated metrics
    - few_shot_examples: representative segment sequences for planner prompt
    """
    aggregated = aggregate_analyses(analyses, min_references)

    overrides: dict = {}
    if aggregated["sufficient"]:
        m = aggregated["metrics"]

        if m.get("cut_length_avg"):
            overrides.setdefault("editing", {})["max_static_sec"] = round(
                min(m["cut_length_avg"] * 1.5, 8.0), 1
            )

        if m.get("caption_density_wps"):
            density = m["caption_density_wps"]
            if density > 0:
                avg_cut = m.get("cut_length_avg", 3.0)
                words_per_caption = max(2, min(7, round(density * avg_cut)))
                overrides.setdefault("captions", {})["max_words"] = words_per_caption

        if m.get("audio_mean_volume_db") is not None:
            vol = m["audio_mean_volume_db"]
            overrides.setdefault("music", {})["default_volume_db"] = round(max(-24, min(-8, vol)), 0)

    few_shot = _generate_few_shot_examples(analyses) if aggregated["sufficient"] else []

    return {
        "preset_overrides": overrides,
        "learned_metrics": aggregated,
        "few_shot_examples": few_shot,
    }


def _generate_few_shot_examples(analyses: list[dict]) -> list[dict]:
    """Pick 2-3 representative segment sequences as example plan snippets."""
    examples = []
    # Use analyses sorted by cut_count descending — more cuts = more representative
    sorted_analyses = sorted(analyses, key=lambda a: a.get("cut_count", 0), reverse=True)

    for i, analysis in enumerate(sorted_analyses[:3]):
        avg_cut = analysis.get("cut_lengths", {}).get("avg", 3.0)
        cut_count = analysis.get("cut_count", 5)
        duration = analysis.get("total_duration", 30.0)

        # Build a synthetic segment sequence matching this reel's rhythm
        segments = []
        cursor = 0.0
        for j in range(min(cut_count + 1, 12)):
            seg_dur = avg_cut * (0.8 + 0.4 * (j % 3) / 2)
            segments.append({
                "id": f"s{j + 1}",
                "in": round(cursor, 2),
                "out": round(cursor + seg_dur, 2),
            })
            cursor += seg_dur
            if cursor >= duration:
                break

        examples.append({
            "source": analysis.get("source_file", f"reference_{i + 1}"),
            "total_duration": round(duration, 1),
            "segment_count": len(segments),
            "avg_cut_length": round(avg_cut, 2),
            "segments_preview": segments[:6],
        })
    return examples


def save_learned_profile(profile: dict, name: str = "learned") -> Path:
    """Save learned profile to disk."""
    path = LEARNED_PROFILES_DIR / f"{name}.json"
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_learned_profile(name: str = "learned") -> Optional[dict]:
    """Load learned profile from disk, or None if not found."""
    path = LEARNED_PROFILES_DIR / f"{name}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def merge_with_preset(preset: dict, learned: Optional[dict]) -> dict:
    """Merge learned profile overrides into a preset, returning the merged result."""
    if not learned or not learned.get("preset_overrides"):
        return dict(preset)
    from engine.style_library import _deep_merge
    return _deep_merge(preset, learned["preset_overrides"])
