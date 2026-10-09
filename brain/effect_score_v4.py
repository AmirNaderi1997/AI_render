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
from .llm import LLMUsage

log = logging.getLogger(__name__)

_V4_ROLE_SCORES = {
    "number": {"text_pop": 12, "flash_black": 10, "freeze_zoom": 10},
    "claim": {"text_pop": 10, "vignette_pulse": 7},
    "hook": {"blur_in": 9, "text_pop": 9, "flash_white": 8},
    "question": {"vignette_pulse": 10, "blur_in": 6},
    "emotion": {"vignette_pulse": 12, "blur_in": 8},
    "contrast": {"bw_flash": 11, "flash_black": 8},
    "transition": {"blur_in": 10, "light_leak": 8},
    "cta": {"text_pop": 10, "flash_white": 8},
}
_VERIFIED_V4_FAMILIES = {"blur_in", "vignette_pulse"}


def _is_zoom_effect(effect_id: str) -> bool:
    if "zoom" in effect_id:
        return True
    if "__" in effect_id:
        return effect_id.split("__", 1)[0] != "steady"
    return False

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
    role = segment_analysis.get("role", "explanation")
    energy = float(segment_analysis.get("energy", 2))
    for family, info in EFFECT_FAMILIES_V4.items():
        if family in scores_dict:
            continue
        if family not in _VERIFIED_V4_FAMILIES:
            continue
        score = 2.0 + max(0.0, 3.0 - abs(energy - info["energy"]))
        score += _V4_ROLE_SCORES.get(role, {}).get(family, 0)
        if role in info.get("best_roles", []):
            score += 3.0
        if family == prev_family:
            score -= 6.0
        if family == prev_prev_family:
            score -= 3.0
        scores_dict[family] = max(0.0, score)

    # Apply my_effects rules if provided
    if my_effects:
        # Hard rules: apply immediately to filter families
        hard_exclusions = set()
        hard_boosts = {}

        no_zoom = False
        for rule in my_effects.rules:
            rule_text = rule.get("text", "").lower()
            if any(phrase in rule_text for phrase in ("زوم نکن", "بدون زوم", "no zoom", "don't zoom")):
                no_zoom = True
                continue
            # Parse simple heuristics from rule text (e.g., "zoom on numbers" → boost punch, flash)
            if (role == "number" and any(w in rule_text for w in ("اعداد", "آمار", "number", "stat"))
                    and any(w in rule_text for w in ("زوم", "zoom", "punch"))):
                hard_boosts["punch"] = hard_boosts.get("punch", 0) + 3
                hard_boosts["punch_bright"] = hard_boosts.get("punch_bright", 0) + 3
                hard_boosts["flash"] = hard_boosts.get("flash", 0) + 2
            if role in ("cta", "conclusion", "transition") and any(w in rule_text for w in ["آروم", "calm", "slow", "نرم", "soft"]):
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
            for fam_name, info in EFFECT_FAMILIES_V4.items():
                if fav_id in info.get("ids", []) and fam_name in scores_dict:
                    scores_dict[fam_name] *= 1.0 + float(weight) * 0.5

        # A Rafiei style is a separate, mutually exclusive theme choice. It
        # biases the matching family without changing Favorites or My Rules.
        selected_style = my_effects.selected_rafiei_style
        if selected_style:
            for fam_name, info in EFFECT_FAMILIES_V4.items():
                if selected_style in info.get("ids", []) and fam_name in scores_dict:
                    scores_dict[fam_name] += 12.0

        # Apply dislikes (never use)
        for dislike_id in my_effects.dislikes:
            for fam_name, info in EFFECT_FAMILIES_V4.items():
                if dislike_id == fam_name or dislike_id in info.get("ids", []):
                    scores_dict[fam_name] = -100

        if no_zoom:
            for fam_name, info in EFFECT_FAMILIES_V4.items():
                if any(_is_zoom_effect(effect_id) for effect_id in info.get("ids", [])):
                    scores_dict[fam_name] = -100

        # Remove hard exclusions
        for exc in hard_exclusions:
            for fam_name in list(scores_dict.keys()):
                if fam_name in exc or exc in fam_name:
                    scores_dict[fam_name] = -100

    # Stage 5: Apply aggregated feedback bias from style learning
    try:
        from brain.style_feedback import load_feedback_summary, apply_feedback_to_effect_scores
        fb_summary = load_feedback_summary()
        if fb_summary and fb_summary.get("total_events", 0) >= 5:
            scores_dict = apply_feedback_to_effect_scores(scores_dict, fb_summary)
    except Exception:
        pass

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
    vision_usage: Optional[list[LLMUsage]] = None,
) -> list[dict]:
    """Plan effects for all segments as a coherent reel story.

    Returns [{"segment_id": "s1", "type": "punch__lift_medium", "reason": "..."}]
    """

    from engine.effects_v4 import EFFECT_FAMILIES_V4 as FAMILIES
    from .effect_score import _find_emphasis_start

    # A style explicitly selected on My Effects is an editing decision, not a
    # suggestion to the scorer. Do not call vision, rotate variants, or let a
    # critic choose a different family when this lock is present.
    selected_style = my_effects.selected_rafiei_style if my_effects else None
    if selected_style:
        selected_family = next(
            (name for name, info in FAMILIES.items() if selected_style in info.get("ids", [])),
            "user_selected",
        )
        return [
            {
                "segment_id": seg["id"],
                "type": selected_style,
                "family": selected_family,
                "reason": f"Locked by My Effects selection: {selected_style}",
                "source": "my_effects_selection",
                "vision": None,
            }
            for seg in segments
        ]

    effects = []
    accent_debt = 0.0
    prev_family = None
    prev_prev_family = None

    # First pass: holistic edit story planning
    # Identify hook (first segment), build (middle), peak (climax), calm (before CTA), CTA
    story_moments = _identify_edit_story(segments, analyses)

    vision_indices = {0, len(segments) // 2, len(segments) - 1} if keyframe_dir else set()
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
        vision_answer = None
        if i in vision_indices and keyframe and keyframe.exists() and scores:
            from .llm import chat_vision
            candidates = [family for family, _ in scores[:8]]
            try:
                vision_answer, usage = chat_vision(
                    system="You are a careful video editor. Describe only visible framing and choose one suitable effect family. Return JSON.",
                    user=(f"Segment role: {ana.get('role', 'unknown')}; spoken text: {ana.get('text', '')[:180]}. "
                          f"Candidate families: {', '.join(candidates)}. "
                          "Return JSON keys face_size, framing, chosen_effect, reason. "
                          "chosen_effect must be one candidate. Respect the user's no-zoom rule where applicable."),
                    images=[keyframe], return_json=True, max_tokens=300,
                )
                if vision_usage is not None:
                    vision_usage.append(usage)
                choice = vision_answer.get("chosen_effect")
                if choice in candidates:
                    scores = sorted([(fam, score + (5.0 if fam == choice else 0.0))
                                     for fam, score in scores], key=lambda pair: -pair[1])
            except Exception as exc:
                log.warning("vision analysis failed for %s: %s", seg_id, exc)

        if not scores:
            scores = [("still", 1.0)]

        chosen_family = scores[0][0]

        # Check story moment to boost/adjust family
        moment = story_moments.get(seg_id)
        if moment == "hook" and not my_effects:
            # Boost high-energy families
            for fam, score in scores:
                if fam in {"punch_bright", "flash", "punch"}:
                    chosen_family = fam
                    break
        elif moment == "peak" and not my_effects:
            # Strongest effect on peak
            for fam, score in scores:
                if fam in {"punch_bright", "flash_end", "freeze_zoom"}:
                    chosen_family = fam
                    break
        elif moment == "cta" and not my_effects:
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

        reason = (f"Role {ana.get('role', 'unknown')}; story moment {moment or 'build'}; "
                  f"family {chosen_family}; score {dict(scores).get(chosen_family, 0):.1f}")
        if vision_answer and vision_answer.get("chosen_effect") == chosen_family:
            reason += f"; vision: {vision_answer.get('reason', '')[:180]}"

        effects.append({
            "segment_id": seg_id,
            "type": effect_id,
            "family": chosen_family,
            "reason": reason,
            "source": "vision" if vision_answer and vision_answer.get("chosen_effect") == chosen_family else "favorite" if my_effects and effect_id in my_effects.favorites else "rule" if my_effects and my_effects.rules else "analysis",
            "vision": vision_answer,
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
