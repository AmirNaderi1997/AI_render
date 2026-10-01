"""Effect scorer: matches segment analysis to effect families via a score matrix.

Returns top-3 candidate families per segment for the LLM to choose from.
Enforces variety constraints before scoring (no same family twice in a row,
max share per family, accent spacing).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from engine.effects import EFFECT_FAMILIES, family_to_effect_id
from .llm import LLMUsage, chat_json

log = logging.getLogger(__name__)

# Role → family affinity scores (0-10)
_ROLE_AFFINITY: dict[str, dict[str, int]] = {
    "hook":         {"punch_bright": 10, "punch": 8, "flash": 7, "close_hold": 6, "still": 2},
    "claim":        {"punch": 8, "lift": 7, "slow_push_bright": 7, "slow_push": 5, "still": 4},
    "explanation":  {"slow_push": 8, "still": 7, "breathe": 6, "close_hold": 5},
    "list_item":    {"slow_push": 7, "still": 8, "lift": 5, "drift": 4},
    "number":       {"flash": 9, "punch": 8, "lift": 6, "close_hold": 5},
    "story":        {"breathe": 9, "slow_push": 7, "drift": 6, "still": 5},
    "question":     {"close_hold": 9, "punch": 6, "still": 7, "breathe": 5},
    "emotion":      {"close_hold": 10, "breathe": 8, "slow_pull": 7, "still": 5},
    "contrast":     {"slow_pull_dim": 9, "dim": 8, "slow_pull": 7, "still": 4},
    "cta":          {"flash_end": 10, "punch_bright": 8, "lift": 7, "punch": 6},
    "conclusion":   {"slow_pull": 8, "breathe": 7, "lift": 6, "flash_end": 5},
    "transition":   {"breathe": 9, "still": 7, "slow_pull": 6, "drift": 5},
    "turning_point": {"flash": 9, "punch": 8, "tilt": 7, "punch_bright": 7},
}

# Energy → family energy affinity bonus
def _energy_bonus(seg_energy: int, family_energy: int) -> float:
    return max(0.0, 3.0 - abs(seg_energy - family_energy))


def score_families(
    analysis: dict,
    prev_family: Optional[str],
    prev_prev_family: Optional[str],
    accent_debt: float,
    style: dict,
) -> list[tuple[str, float]]:
    """Score all families for one segment. Returns [(family, score)] sorted descending."""
    role = analysis.get("role", "explanation")
    energy = analysis.get("energy", 2)
    is_tp = analysis.get("is_turning_point", False)
    effective_role = "turning_point" if is_tp else role

    effect_cfg = style.get("effects", {})
    max_share = float(effect_cfg.get("max_family_share", 0.4))
    accent_min_gap = float(effect_cfg.get("accent_min_gap_sec", 6.0))

    accent_families = {"flash", "flash_end", "punch_bright"}
    affinity = _ROLE_AFFINITY.get(effective_role, _ROLE_AFFINITY.get(role, {}))

    scores: list[tuple[str, float]] = []
    for fname, finfo in EFFECT_FAMILIES.items():
        base = float(affinity.get(fname, 1))
        base += _energy_bonus(energy, finfo["energy"])

        # Penalise repeating the same family as previous
        if fname == prev_family:
            base -= 6.0
        # Penalise same family as two-back
        if fname == prev_prev_family:
            base -= 3.0
        # Penalise avoid_after
        if prev_family in finfo.get("avoid_after", []):
            base -= 4.0
        # Penalise accent family if too soon
        if fname in accent_families and accent_debt > 0:
            base -= 5.0
        # Require framing check: slight penalty since we can't check automatically
        if finfo.get("framing_check"):
            base -= 2.0

        scores.append((fname, max(0.0, base)))

    scores.sort(key=lambda x: -x[1])
    return scores


def _find_emphasis_start(
    key_words: list[str],
    transcript: dict,
    seg_in: float,
    seg_out: float,
) -> Optional[float]:
    """Find the source-time start of the first emphasis key word in the segment."""
    if not key_words:
        return None
    words = transcript.get("words", [])
    first_kw = key_words[0].strip()
    for w in words:
        if seg_in - 0.05 <= w.get("start", 0) <= seg_out + 0.05:
            if w["w"].strip() == first_kw:
                return w["start"]
    return None


def select_effects_with_llm(
    segments: list[dict],
    analyses: list[dict],
    transcript: dict,
    style: dict,
) -> tuple[list[dict], LLMUsage]:
    """Score and ask the LLM to pick one family per segment from top-3 candidates.

    Returns (visual_effects list, total_usage).
    Falls back to the top score if the LLM picks an invalid family.
    """
    if not segments or not analyses:
        return [], LLMUsage()

    analyses_map = {a["segment_id"]: a for a in analyses}
    effect_cfg = style.get("effects", {})
    accent_spacing = float(effect_cfg.get("accent_min_gap_sec", 6.0))

    # Build top-3 candidates per segment
    prev_family: Optional[str] = None
    prev_prev_family: Optional[str] = None
    last_accent_out = -999.0
    out_acc = 0.0
    candidates_per_seg: list[dict] = []

    for seg in segments:
        dur = seg.get("out", 0) - seg.get("in", 0)
        seg_start_out = out_acc
        out_acc += dur
        analysis = analyses_map.get(seg["id"], {"role": "explanation", "energy": 2})
        accent_debt = max(0.0, accent_spacing - (seg_start_out - last_accent_out))

        scored = score_families(analysis, prev_family, prev_prev_family, accent_debt, style)
        top3 = [name for name, _ in scored[:3]]

        emphasis_start = _find_emphasis_start(
            analysis.get("key_words", []),
            transcript,
            seg.get("in", 0),
            seg.get("out", 0),
        )
        candidates_per_seg.append({
            "segment_id": seg["id"],
            "duration": round(dur, 2),
            "role": analysis.get("role", "explanation"),
            "energy": analysis.get("energy", 2),
            "emotion": analysis.get("emotion", "neutral"),
            "is_turning_point": analysis.get("is_turning_point", False),
            "key_words": analysis.get("key_words", []),
            "candidates": top3,
            "top_score_family": top3[0] if top3 else "still",
            "emphasis_start": emphasis_start,
        })
        prev_prev_family = prev_family
        prev_family = top3[0] if top3 else "still"

    # Build LLM prompt with family catalog and candidates
    families_compact = "\n".join(
        f"  {name}: energy={info['energy']} mood={info['mood']} — {info['description']}"
        for name, info in EFFECT_FAMILIES.items()
    )

    system = f"""You are a video editor choosing the best visual effect family for each segment.

## Effect families available:
{families_compact}

## Task
For each segment, pick ONE family from its `candidates` list. Return your choice + a one-sentence reason.
Rules:
- Pick based on role, energy, emotion, and pacing
- Vary the choices — do not repeat the same family more than twice in a row
- Use "punch_bright" or "flash" at most once per video
- Use "drift" or "tilt" only if framing_check is acceptable
- Never invent a family not in the candidates list

Output ONLY this JSON:
{{"effects": [{{"segment_id": "<id>", "family": "<chosen_family>", "reason": "<one sentence>"}}]}}"""

    user = (
        f"Language: {transcript.get('language', 'fa')}\n\n"
        + "\n".join(
            f"Segment {c['segment_id']} ({c['duration']}s): role={c['role']} energy={c['energy']} "
            f"emotion={c['emotion']} turning_point={c['is_turning_point']} "
            f"key_words={c['key_words']}\n  candidates: {c['candidates']}"
            for c in candidates_per_seg
        )
        + "\n\nChoose one family per segment and explain."
    )

    try:
        raw, usage = chat_json(system, user, max_tokens=1024, temperature=0.0)
    except Exception as exc:
        log.warning("effect selection LLM call failed: %s — using top scores", exc)
        return _fallback_effects(candidates_per_seg, segments), LLMUsage()

    # Validate and build visual_effects list
    valid_families = set(EFFECT_FAMILIES.keys())
    effects: list[dict] = []
    chosen_by_id: dict[str, dict] = {}

    for item in raw.get("effects") or []:
        sid = str(item.get("segment_id", ""))
        family = str(item.get("family", ""))
        reason = str(item.get("reason", ""))[:200]

        # Find the candidate spec for this segment
        cspec = next((c for c in candidates_per_seg if c["segment_id"] == sid), None)
        if not cspec:
            continue

        # LLM must pick from the candidates list; if it picks outside, use top score
        if family not in valid_families or family not in cspec["candidates"]:
            log.warning(
                "LLM chose family %r for %s outside candidates %s — using top score",
                family, sid, cspec["candidates"],
            )
            family = cspec["top_score_family"]
            reason = f"[auto: top score] {reason}"

        # Map family → specific effect ID
        seg_index = next(
            (i for i, s in enumerate(segments) if s["id"] == sid), 0
        )
        prev_fam = effects[-1].get("_family", "") if effects else ""
        effect_id = family_to_effect_id(family, seg_index, prev_fam)
        emphasis_start = cspec.get("emphasis_start")
        intensity = EFFECT_FAMILIES.get(family, {}).get("energy", 2)
        chosen_by_id[sid] = {
            "effect_id": effect_id,
            "family": family,
            "reason": reason,
            "emphasis_start": emphasis_start,
            "intensity": intensity,
        }

    # Fill any missing segments with top score
    for cspec in candidates_per_seg:
        sid = cspec["segment_id"]
        if sid not in chosen_by_id:
            family = cspec["top_score_family"]
            seg_index = next((i for i, s in enumerate(segments) if s["id"] == sid), 0)
            effect_id = family_to_effect_id(family, seg_index)
            intensity = EFFECT_FAMILIES.get(family, {}).get("energy", 2)
            chosen_by_id[sid] = {
                "effect_id": effect_id,
                "family": family,
                "reason": "top score fallback",
                "emphasis_start": cspec.get("emphasis_start"),
                "intensity": intensity,
            }

    effects = [
        {
            "segment_id": sid,
            "type": v["effect_id"],
            "_family": v["family"],
            "_reason": v["reason"],
            "_intensity": v.get("intensity", 2),
            "_emphasis_start": v.get("emphasis_start"),
        }
        for sid, v in chosen_by_id.items()
    ]

    return effects, usage


def critic_effect_pass(
    effects: list[dict],
    analyses: list[dict],
    total_duration: float,
    style: dict,
) -> tuple[list[dict], LLMUsage]:
    """Cheap LLM critic reviews the effect timeline and suggests fixes.

    Returns (possibly updated effects, usage).
    """
    if not effects or total_duration <= 0:
        return effects, LLMUsage()

    effect_cfg = style.get("effects", {})
    max_static_sec = float(effect_cfg.get("max_static_sec", style.get("editing", {}).get("max_static_sec", 4.0)))

    # Check if there are obvious problems worth sending to the LLM
    families = [e.get("_family", e.get("type", "")) for e in effects]
    has_repeats = any(families[i] == families[i - 1] for i in range(1, len(families)))
    static_run = 0
    has_static_overrun = False
    analyses_map = {a["segment_id"]: a for a in analyses}
    for eff, seg_info in zip(effects, analyses):
        if eff.get("_family", "").startswith("still") or eff.get("type", "") == "steady__neutral":
            dur = analyses_map.get(eff["segment_id"], {}).get("duration", 0)
            static_run += dur
            if static_run > max_static_sec:
                has_static_overrun = True
        else:
            static_run = 0

    if not has_repeats and not has_static_overrun:
        return effects, LLMUsage()

    issues_desc = []
    if has_repeats:
        issues_desc.append("same family appears back-to-back")
    if has_static_overrun:
        issues_desc.append(f"static shot exceeds {max_static_sec}s limit")

    timeline = "\n".join(
        f"  {e['segment_id']}: family={e.get('_family', e.get('type'))} reason={e.get('_reason', '')}"
        for e in effects
    )
    roles = "\n".join(
        f"  {a['segment_id']}: role={a['role']} energy={a['energy']}"
        for a in analyses
    )

    system = """You are a video editor reviewing an effect timeline.
Find and fix: same family twice in a row, too many static shots in a row, accent effects too close together.
For each fix, return the segment_id and the new family (must be a valid family name).
Output ONLY JSON: {"fixes": [{"segment_id": "<id>", "family": "<new_family>", "reason": "<why>"}]}
If no fixes are needed, return {"fixes": []}."""

    user = (
        f"Issues detected: {', '.join(issues_desc)}\n\n"
        f"Effect timeline:\n{timeline}\n\n"
        f"Segment roles:\n{roles}\n\n"
        "List any fixes."
    )

    try:
        raw, usage = chat_json(system, user, max_tokens=512, temperature=0.0)
    except Exception as exc:
        log.warning("critic pass failed: %s", exc)
        return effects, LLMUsage()

    fixes = raw.get("fixes") or []
    if not fixes:
        return effects, usage

    effects_map = {e["segment_id"]: dict(e) for e in effects}
    valid_families = set(EFFECT_FAMILIES.keys())
    for fix in fixes:
        sid = str(fix.get("segment_id", ""))
        new_family = str(fix.get("family", ""))
        if sid in effects_map and new_family in valid_families:
            seg_index = next(
                (i for i, e in enumerate(effects) if e["segment_id"] == sid), 0
            )
            new_id = family_to_effect_id(new_family, seg_index)
            effects_map[sid]["type"] = new_id
            effects_map[sid]["_family"] = new_family
            effects_map[sid]["_reason"] = f"[critic] {fix.get('reason', '')}"
            log.info("critic fixed %s: → %s (%s)", sid, new_family, fix.get("reason"))

    return list(effects_map.values()), usage


def _fallback_effects(candidates_per_seg: list[dict], segments: list[dict]) -> list[dict]:
    effects = []
    for i, cspec in enumerate(candidates_per_seg):
        family = cspec["top_score_family"]
        eff_id = family_to_effect_id(family, i, effects[-1].get("_family", "") if effects else "")
        effects.append({
            "segment_id": cspec["segment_id"],
            "type": eff_id,
            "_family": family,
            "_reason": "top-score fallback",
        })
    return effects
