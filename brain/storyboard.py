"""Storyboard generator — breaks a text prompt into timed scenes for content creation."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional

from engine.content_types import ContentType, get_preset
from .ai_provider import get_provider

log = logging.getLogger(__name__)


@dataclass
class Scene:
    index: int
    description: str
    duration_s: float
    text_overlay: str = ""
    media_method: Literal["generate", "library", "upload"] = "generate"
    media_prompt: str = ""
    estimated_cost: float = 0.0
    narration_text: str = ""
    narration_voice: str = "default"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Storyboard:
    prompt: str
    content_type: str
    language: str
    style: str
    creative_brief: dict[str, str] = field(default_factory=dict)
    scenes: list[Scene] = field(default_factory=list)
    total_duration_s: float = 0.0
    estimated_total_cost: float = 0.0
    usage: Optional[dict] = None
    is_fallback: bool = False
    fallback_reason: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scenes"] = [s.to_dict() for s in self.scenes]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Storyboard:
        scenes = [Scene(**s) for s in data.get("scenes", [])]
        return cls(
            prompt=data.get("prompt", ""),
            content_type=data.get("content_type", "reel"),
            language=data.get("language", "en"),
            style=data.get("style", "rafiei_reel"),
            creative_brief=data.get("creative_brief") or {},
            scenes=scenes,
            total_duration_s=data.get("total_duration_s", 0.0),
            estimated_total_cost=data.get("estimated_total_cost", 0.0),
            usage=data.get("usage"),
            is_fallback=bool(data.get("is_fallback", False)),
            fallback_reason=data.get("fallback_reason"),
        )


def _template_storyboard(
    prompt: str,
    content_type: ContentType,
    language: str,
    style: str,
    creative_brief: Optional[dict[str, str]],
    reason: str,
) -> Storyboard:
    """Return a valid, zero-cost storyboard that can be edited in the UI."""
    if content_type == ContentType.POST:
        placeholders = [("Main point", 5.0)]
    else:
        placeholders = [("Intro", 5.0), ("Main point", 5.0), ("Outro", 5.0)]

    scenes = [
        Scene(
            index=index,
            description=label,
            duration_s=duration,
            text_overlay=label,
            narration_text="",
            media_method="generate",
            media_prompt=f"Editable placeholder visual for the {label.lower()}",
            estimated_cost=0.0,
        )
        for index, (label, duration) in enumerate(placeholders)
    ]
    return Storyboard(
        prompt=prompt,
        content_type=content_type.value,
        language=language,
        style=style,
        creative_brief=creative_brief or {},
        scenes=scenes,
        total_duration_s=sum(scene.duration_s for scene in scenes),
        estimated_total_cost=0.0,
        usage={"input_tokens": 0, "output_tokens": 0, "model": "local_template"},
        is_fallback=True,
        fallback_reason=reason,
    )


def _build_storyboard_system_prompt(preset: dict, content_type: ContentType, language: str) -> str:
    is_persian = language.lower().strip() in {"fa", "per", "fas", "persian", "farsi"}

    if content_type == ContentType.POST:
        scene_rule = (
            "Produce exactly 1 scene. It is a still image (duration_s = 5.0 for display purposes). "
            "If narration is useful, keep it to one concise sentence that takes no more than "
            "4.2 seconds to say."
        )
    elif content_type == ContentType.STORY:
        scene_rule = (
            "Produce 1-3 scenes. Total duration must be 5-15 seconds. Aim for 10-15 seconds, "
            "with 1-2 concise spoken thoughts per scene and a short, natural ending."
        )
    else:
        scene_rule = (
            "Produce 5-7 scenes. Aim for a concise 20-45 second Reel, with 15-90 seconds "
            "allowed when the brief needs it. Keep scenes around 3-7 seconds, give each "
            "scene one concise spoken thought, and reserve the final scene for one short, "
            "natural call to action."
        )

    lang_rule = ""
    if is_persian:
        lang_rule = (
            "\n- Text overlays MUST be in Persian script (right-to-left). "
            "Do NOT transliterate or translate to English. "
            "Text overlays are rendered separately via the caption system — "
            "do NOT include text in the media_prompt (image/video generation prompt). "
            "narration_text MUST be in Persian script."
        )

    return f"""You are a creative director and Persian-first short-form editor making publishable Instagram content.

Turn the user's brief into a distinctive, specific visual story for a {content_type.value}.
Preserve every requested point, order, audience, tone, and call to action. Do not invent factual claims.
Use one clear idea per scene. Open with a concrete visual hook, build curiosity or useful payoff,
and end with the requested action. Keep the spoken script short enough to sound natural at a
measured pace; do not add a second summary or repeat the call to action. Make every scene advance
the story with a distinct subject action and composition; never reuse the same shot or action in
adjacent scenes. Avoid generic motivational cliches, repeated stock imagery, and interchangeable
scenes. Vary shot distance, camera angle, action, and visual rhythm while
keeping the palette, lighting, and location coherent across scenes. Independent image
generation cannot reliably preserve one person's face across shots: use hands, objects,
and action details between a small number of portraits, or present different people
intentionally. Do not claim a recurring identifiable character without a reference image.

Output a single JSON object with this schema:
{{
  "scenes": [
    {{
      "index": 0,
      "description": "What this scene shows — internal note for the editor",
      "duration_s": <seconds as float>,
      "text_overlay": "<short text to display on screen, 2-8 words>",
      "narration_text": "<voiceover script for this scene>",
      "media_method": "generate",
      "media_prompt": "<detailed prompt for image/video AI generation — visual only, NO text>",
      "estimated_cost": 0.05
    }}
  ],
  "total_duration_s": <sum of all scene durations>
}}

## Rules
- {scene_rule}
- Resolution: {preset['resolution']}, aspect ratio: {preset['aspect']}
- media_method is always "generate" unless the user mentions using their own footage
- media_prompt must be specific enough for an image model: subject identity and action,
  setting, foreground/background, framing, camera angle, lighting, palette, continuity
  with adjacent scenes, and clear negative space for the separate caption layer.
- Use photographic or cinematic detail appropriate to the brief; avoid abstract gradients,
  generic smiling portraits, and a different anonymous person in every scene.
- media_prompt must NEVER include text, words, letters, or typography instructions
- text_overlay is rendered separately by the caption system, not burned into generated media
- narration_text is the voiceover script for this scene. Write conversationally in the
  same language as text_overlay. Use one concise thought and budget no more than
  1.7 spoken words per second of scene duration, including Persian. Leave a short pause
  at the end. The voice must fit the scene naturally; never rely on speeding it up or
  stretching a visual for a long hold. Use an empty string when narration is inappropriate.
- estimated_cost: ~$0.04 per image, ~$0.10 per second of video{lang_rule}
- Keep text_overlay concise: 2-8 words max. Make it a useful headline or point,
  not a duplicate of the whole narration. Check spelling and numbering.
- Output pure JSON only, no markdown"""


def _build_storyboard_user_prompt(
    prompt: str, content_type: ContentType, style: str,
    creative_brief: Optional[dict[str, str]] = None,
) -> str:
    labels = {
        "audience": "Target audience",
        "goal": "Desired viewer response",
        "brand": "Brand and visual identity",
        "avoid": "Ideas or claims to avoid",
    }
    brief_lines = [f"{label}: {str((creative_brief or {}).get(key, '')).strip()[:500]}"
                   for key, label in labels.items() if (creative_brief or {}).get(key)]
    brief = "\n".join(brief_lines) if brief_lines else "No additional brand brief supplied."
    return (
        f"Content type: {content_type.value}\n"
        f"Style: {style}\n"
        f"Creative brief:\n{brief}\n\n"
        f"User prompt:\n{prompt}\n\n"
        f"Generate the storyboard JSON now."
    )


def generate_storyboard(
    prompt: str,
    content_type: str | ContentType,
    language: str = "fa",
    style: str = "rafiei_reel",
    creative_brief: Optional[dict[str, str]] = None,
    provider_name: Optional[str] = None,
) -> Storyboard:
    if isinstance(content_type, str):
        content_type = ContentType(content_type)

    preset = get_preset(content_type)
    system = _build_storyboard_system_prompt(preset, content_type, language)
    user = _build_storyboard_user_prompt(prompt, content_type, style, creative_brief)

    provider = get_provider(provider_name)
    provider_context = {
        "name": style,
        "content_type": content_type.value,
        "language": language,
        "creative_brief": creative_brief or {},
        "system_prompt": system,
        "user_prompt": user,
    }
    data, usage = provider.generate_storyboard(prompt, provider_context)
    provider_meta = data.pop("_provider_meta", {})
    if provider_meta.get("provider") == "local":
        reason = str(provider_meta.get("fallback_reason") or "text_provider_not_configured")
        log.info("Using editable storyboard template: %s", reason)
        return _template_storyboard(
            prompt, content_type, language, style, creative_brief,
            reason,
        )

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise ValueError("Storyboard response must contain at least one scene")

    scenes = []
    for i, s in enumerate(raw_scenes):
        if not isinstance(s, dict):
            raise ValueError(f"Storyboard scene {i + 1} must be an object")
        media_method = s.get("media_method", "generate")
        if media_method not in ("generate", "library", "upload"):
            raise ValueError(f"Storyboard scene {i + 1} has invalid media_method {media_method!r}")
        try:
            duration = float(s.get("duration_s", 5.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Storyboard scene {i + 1} has invalid duration") from exc
        if not math.isfinite(duration) or duration < 0.5:
            raise ValueError(f"Storyboard scene {i + 1} duration must be at least 0.5 seconds")
        scenes.append(Scene(
            index=i,
            description=s.get("description", ""),
            duration_s=duration,
            text_overlay=s.get("text_overlay", ""),
            narration_text=s.get("narration_text") or "",
            narration_voice=s.get("narration_voice") or "default",
            media_method=media_method,
            media_prompt=s.get("media_prompt", ""),
            estimated_cost=float(s.get("estimated_cost", 0.05)),
        ))

    total_dur = sum(s.duration_s for s in scenes)
    total_cost = sum(s.estimated_cost for s in scenes)

    if content_type == ContentType.POST:
        if len(scenes) != 1 or abs(total_dur - 5.0) > 1e-6:
            raise ValueError("A post storyboard must contain one 5-second scene")
    elif content_type == ContentType.STORY:
        if not 1 <= len(scenes) <= 3:
            raise ValueError("A story storyboard must contain 1 to 3 scenes")
        if not 5.0 <= total_dur <= 15.0:
            raise ValueError("A story storyboard must total 5 to 15 seconds")
    else:
        if not 3 <= len(scenes) <= 10:
            raise ValueError("A reel storyboard must contain 3 to 10 scenes")
        if not 15.0 <= total_dur <= 90.0:
            raise ValueError("A reel storyboard must total 15 to 90 seconds")

    return Storyboard(
        prompt=prompt,
        content_type=content_type.value,
        language=language,
        style=style,
        creative_brief=creative_brief or {},
        scenes=scenes,
        total_duration_s=round(total_dur, 2),
        estimated_total_cost=round(total_cost, 4),
        usage={"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
               "model": usage.model},
    )
