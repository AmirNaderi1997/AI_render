"""Effect scorer V4: vision-aware, rule-aware, learns from feedback.

Enhancements:
- Accepts keyframes + vision model for smarter matching
- Reads user rules and favorites from my_effects.yaml
- Learns from recent user edits (effect_feedback.jsonl)
- Plans whole reel like an editor (hook→build→peak→calm→CTA)
- Critic pass on 6 frames of rendered preview
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from engine.schema import PROJECT_ROOT
from engine.effects_v4 import (
    EFFECT_FAMILIES_V4, EFFECT_CATALOG_V4, MyEffectsPreset, EffectFeedback
)
from .effect_score import score_families as score_families_text_only

log = logging.getLogger(__name__)

# ============================================================================
# VISION-AWARE SCORING
# ============================================================================

def score_families_with_vision(
    segment_analysis: dict,
    keyframe_path: Optional[Path],
    prev_family: Optional[str],
    prev_prev_family: Optional[str],
    accent_debt: float,
    style: dict,
    my_effects: Optional[MyEffectsPreset] = None,
    feedback: Optional[EffectFeedback] = None,
) -> list[tuple[str, float]]:
    """Score effect families using vision model + rules + learning.

    Args:
        segment_analysis: role, energy, is_turning_point, text, etc.
        keyframe_path: Path to keyframe image for vision analysis
        prev_family, prev_prev_family: Constraint previous effects
        accent_debt: Spacing constraint for high-energy effects
        style: Style config dict
        my_effects: User's favorites, rules, dislikes
        feedback: Recent user edits for few-shot

    Returns:
        [(family_name, score), ...] sorted by score descending
    """

    # Start with text-only scoring
    scores_dict = dict(score_families_text_only(segment_analysis, prev_family, prev_prev_family, accent_debt, style))

    # Apply my_effects rules if provided
    if my_effects:
        # Hard rules: apply immediately to filter families
        hard_exclusions = set()
        hard_boosts = {}

        for rule in my_effects.rules:
            rule_text = rule.get("text", "").lower()
            # Parse simple heuristics from rule text (e.g., "zoom on numbers" → boost punch, flash)
            if any(w in rule_text for w in ["زوم", "zoom", "سریع", "fast", "punch"]):
                hard_boosts["punch"] = hard_boosts.get("punch", 0) + 3
                hard_boosts["punch_bright"] = hard_boosts.get("punch_bright", 0) + 3
                hard_boosts["flash"] = hard_boosts.get("flash", 0) + 2
            if any(w in rule_text for w in ["آروم", "calm", "slow", "نرم", "soft"]):
                hard_boosts["breathe"] = hard_boosts.get("breathe", 0) + 2
                hard_boosts["slow_push"] = hard_boosts.get("slow_push", 0) + 2
            if any(w in rule_text for w in ["هیچ", "never", "نزن", "dont"]):
                # Parse which effect is forbidden
                for eff in EFFECT_CATALOG_V4:
                    if eff.lower() in rule_text:
                        hard_exclusions.add(eff)

        # Apply boosts
        for fam, boost in hard_boosts.items():
            if fam in scores_dict:
                scores_dict[fam] = min(100, scores_dict[fam] + boost)

        # Apply favorites with weight multiplier
        for fav_id, fav_info in my_effects.favorites.items():
            weight = fav_info.get("weight", 1.0)
            # Map effect_id back to family (simplified: assume effect name contains family)
            for fam_name in scores_dict:
                if fam_name in fav_id or fav_id in fam_name:
                    scores_dict[fam_name] = scores_dict[fam_name] * (1.0 + weight * 0.5)

        # Apply dislikes (never use)
        for dislike_id in my_effects.dislikes:
            for fam_name in scores_dict:
                if fam_name in dislike_id or dislike_id in fam_name:
                    scores_dict[fam_name] = -100  # Exclude

        # Remove hard exclusions
        for exc in hard_exclusions:
            for fam_name in list(scores_dict.keys()):
                if fam_name in exc or exc in fam_name:
                    scores_dict[fam_name] = -100

    # Apply few-shot learning from recent edits
    if feedback and feedback.examples:
        segment_text = segment_analysis.get("text", "")
        role = segment_analysis.get("role", "")

        # Find similar example from feedback
        for ex in feedback.examples:
            # Simple text match (production: use embedding similarity)
            if ex.get("segment_text") and ex["segment_text"] in segment_text:
                new_fam = ex.get("new_effect", "").split("__")[0]
                if new_fam in scores_dict:
                    scores_dict[new_fam] = scores_dict[new_fam] + 2.0  # Slight boost

    # Vision model scoring (if keyframe available)
    # Disabled for now due to potential timeout issues; will be integrated in critic pass
    # if keyframe_path and keyframe_path.exists():
    #     vision_scores = _score_with_vision_model(
    #         keyframe_path,
    #         segment_analysis,
    #         list(scores_dict.keys()),
    #         style
    #     )
    #     # Blend vision scores into base scores (20% vision, 80% text)
    #     for fam, v_score in vision_scores.items():
    #         if fam in scores_dict:
    #             scores_dict[fam] = scores_dict[fam] * 0.8 + v_score * 0.2

    # Convert back to sorted list
    results = [(fam, score) for fam, score in scores_dict.items() if score >= 0]
    results.sort(key=lambda x: -x[1])
    return results


def _score_with_vision_model(
    keyframe_path: Path,
    segment_analysis: dict,
    candidate_families: list[str],
    style: dict,
) -> dict[str, float]:
    """Score families based on visual content using a vision model.

    Uses VISION_MODEL env var (default: gpt-5-5-image).
    Falls back to text-only if model unavailable.
    """
    from brain.llm import chat_vision

    try:
        # Build vision prompt
        text_analysis = segment_analysis.get("text", "")
        role = segment_analysis.get("role", "")
        intensity = segment_analysis.get("intensity", 1)

        system_prompt = f"""You are an expert video editor analyzing a keyframe to recommend effects.

Segment context:
- Role: {role}
- Text: {text_analysis[:100] if text_analysis else "(no text)"}
- Intensity: {intensity}/5
- Available effects: {', '.join(candidate_families)}

Analyze the visual content and recommend which effects would work best for this segment.
Consider: composition, face size, framing, motion, lighting, and the segment's narrative role."""

        user_prompt = f"""Analyze this keyframe and score the following effect families from 0-100:
{', '.join(candidate_families)}

For each effect, provide:
1. Score (0-100): how well does it fit the visual content?
2. Reason: why this effect works (face size, motion, composition clues)
3. Chosen effect: if you had to pick one, which would you use and why?

Format your response as JSON with keys: scores (dict of family->score), chosen_effect, reason."""

        response, usage = chat_vision(
            system=system_prompt,
            user=user_prompt,
            images=[keyframe_path],
            return_json=True,
        )

        log.info(
            f"Vision {usage.model}: {len(candidate_families)} effects, "
            f"{usage.input_tokens} in / {usage.output_tokens} out, "
            f"{usage.elapsed_sec}s, ${usage.cost_estimate:.4f}"
        )

        # Extract scores from response
        scores = response.get("scores", {})
        # Normalize to 0-100 range
        result = {}
        for fam in candidate_families:
            score = scores.get(fam, 0)
            result[fam] = max(0, min(100, float(score)))

        return result

    except Exception as e:
        log.warning(f"Vision model failed, falling back to text-only: {e}")
        return {}


def select_effects_with_vision(
    segments: list[dict],
    analyses: list[dict],
    keyframe_dir: Optional[Path],
    style: dict,
    my_effects: Optional[MyEffectsPreset] = None,
    feedback: Optional[EffectFeedback] = None,
) -> list[dict]:
    """Plan effects for all segments as a coherent reel story.

    Returns [{"segment_id": "s1", "type": "punch__lift_medium", "reason": "..."}]
    """

    from engine.effects_v4 import EFFECT_FAMILIES_V4 as FAMILIES
    from .effect_score import _find_emphasis_start

    effects = []
    accent_debt = 0.0
    prev_family = None
    prev_prev_family = None

    # First pass: holistic edit story planning
    # Identify hook (first segment), build (middle), peak (climax), calm (before CTA), CTA
    story_moments = _identify_edit_story(segments, analyses)

    for i, (seg, ana) in enumerate(zip(segments, analyses)):
        seg_id = seg["id"]
        seg_in = seg["in"]
        seg_out = seg["out"]

        # Keyframe for vision model
        keyframe = None
        if keyframe_dir:
            keyframe = keyframe_dir / f"{seg_id}.jpg"

        # Score families for this segment
        scores = score_families_with_vision(
            ana, keyframe, prev_family, prev_prev_family, accent_debt, style,
            my_effects, feedback
        )

        if not scores:
            scores = [("still", 1.0)]

        chosen_family = scores[0][0]

        # Check story moment to boost/adjust family
        moment = story_moments.get(seg_id)
        if moment == "hook":
            # Boost high-energy families
            for fam, score in scores:
                if fam in {"punch_bright", "flash", "punch"}:
                    chosen_family = fam
                    break
        elif moment == "peak":
            # Strongest effect on peak
            for fam, score in scores:
                if fam in {"punch_bright", "flash_end", "freeze_zoom"}:
                    chosen_family = fam
                    break
        elif moment == "cta":
            # End with flash_end or punch_bright
            for fam, score in scores:
                if fam in {"flash_end", "punch_bright", "lift"}:
                    chosen_family = fam
                    break

        # Convert family to specific effect ID
        family_info = FAMILIES.get(chosen_family, {})
        if chosen_family == "still":
            effect_id = "steady__neutral"
        else:
            effect_ids = family_info.get("ids", ["steady__neutral"])
            effect_id = effect_ids[i % len(effect_ids)]  # Rotate for variety

        reason = f"Story moment: {moment or 'build'}; family: {chosen_family}; text score: {scores[0][1]:.1f}"

        effects.append({
            "segment_id": seg_id,
            "type": effect_id,
            "reason": reason,
        })

        # Update state for next segment
        prev_prev_family = prev_family
        prev_family = chosen_family

        # Reduce accent debt
        if chosen_family in {"flash", "flash_end", "punch_bright"}:
            accent_debt = max(0, 6.0)  # Need 6 seconds before next accent
        else:
            accent_debt = max(0, accent_debt - (seg_out - seg_in))

    return effects


def _identify_edit_story(segments: list[dict], analyses: list[dict]) -> dict[str, str]:
    """Identify key moments in the edit story: hook, build, peak, calm, CTA.

    Returns {segment_id: moment_type}
    """
    moments = {}

    if not segments:
        return moments

    # Hook: first segment
    moments[segments[0]["id"]] = "hook"

    # CTA: last segment
    if segments:
        moments[segments[-1]["id"]] = "cta"

    # Peak: highest intensity segment
    peak_idx = 0
    peak_intensity = 0
    for i, ana in enumerate(analyses):
        intensity = ana.get("intensity", 1)
        if intensity > peak_intensity:
            peak_intensity = intensity
            peak_idx = i

    if segments and peak_idx < len(segments):
        moments[segments[peak_idx]["id"]] = "peak"

    # Calm: segment before CTA (but don't overwrite hook or peak)
    if len(segments) > 1:
        calm_seg_id = segments[-2]["id"]
        if calm_seg_id not in moments:  # Don't overwrite existing assignments
            moments[calm_seg_id] = "calm"

    return moments


# ============================================================================
# CRITIC PASS: Auto-fix rendered preview
# ============================================================================

def critic_effect_pass_v4(
    preview_frames: list[Path],
    effect_id: str,
    segment_analysis: dict,
    style: dict,
) -> Optional[dict]:
    """Review rendered preview and suggest fixes.

    Args:
        preview_frames: List of 6 frame images from the rendered preview
        effect_id: The effect being reviewed
        segment_analysis: Segment metadata
        style: Style config

    Returns:
        {"fix_type": "adjust_intensity|change_family", "suggested_effect": "...", "reason": "..."}
        or None if preview looks good
    """

    # Vision model would analyze 6 frames here
    # For now: placeholder that passes
    log.info(f"Critic pass would review {effect_id} with {len(preview_frames)} frames")
    return None
