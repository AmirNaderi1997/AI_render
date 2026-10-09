"""Effects V4: extended catalog with vision-aware selection, custom presets, and rich effects.

Adds: camera shake, freeze frame, speed ramp, blur, vignette, RGB split, light leak overlay,
text pop, emoji pop, transitions, and per-effect SFX.

Still renders to MLT but with more filter types: boxblur, vignette, frei0r, affine, etc.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Legacy 100 combos from v3
from engine.effects import EFFECT_CATALOG as _LEGACY_CATALOG, EFFECT_FAMILIES as _LEGACY_FAMILIES
from engine.schema import PROJECT_ROOT

# ============================================================================
# EXTENDED EFFECT CATALOG: New effect types with params, moods, energy, SFX
# ============================================================================

EXTENDED_EFFECTS = {
    # Camera motion / composition (new)
    "camera_shake": {
        "id": "camera_shake",
        "category": "motion",
        "label": "Camera Shake",
        "description": "Handheld camera vibration — tension, impact, urgency",
        "params": {"intensity": 2, "frequency": 8},  # pixels, hz
        "mood": "tension",
        "energy": 4,
        "best_roles": ["shock", "mistake", "urgency", "impact"],
        "sfx": "sfx/impact_hit.wav",
    },
    "freeze_frame_zoom": {
        "id": "freeze_frame_zoom",
        "category": "transition",
        "label": "Freeze + Zoom",
        "description": "Freeze the current frame, zoom into it over 0.5s — punctuation, emphasis",
        "params": {"zoom_to": 1.3, "hold_frames": 3},
        "mood": "punctuation",
        "energy": 4,
        "best_roles": ["punchline", "stat", "revelation", "moment"],
        "sfx": "sfx/freeze_whoosh.wav",
    },
    "speed_ramp": {
        "id": "speed_ramp",
        "category": "motion",
        "label": "Speed Ramp (Slow then Speed)",
        "description": "Start at 50% speed, ramp to 150% by end — drama build, momentum",
        "params": {"slow_start": 0.5, "fast_end": 1.5},
        "mood": "building",
        "energy": 3,
        "best_roles": ["reveal", "build_up", "transition"],
        "sfx": None,
    },
    "blur_in": {
        "id": "blur_in",
        "category": "light",
        "label": "Blur In",
        "description": "Start blurred, focus in over 0.3s — soft entry, arrival",
        "params": {"blur_start": 20, "blur_end": 0},
        "mood": "elegant",
        "energy": 1,
        "best_roles": ["entry", "intro", "transition"],
        "sfx": None,
    },
    "vignette_pulse": {
        "id": "vignette_pulse",
        "category": "light",
        "label": "Vignette Pulse",
        "description": "Darkened edges pulse in — focus draws to center, intimacy",
        "params": {"vignette_strength": 0.4, "pulse_speed": 2},
        "mood": "intimate",
        "energy": 2,
        "best_roles": ["confession", "emotion", "close_up"],
        "sfx": None,
    },
    "rgb_split": {
        "id": "rgb_split",
        "category": "glitch",
        "label": "RGB Split / Glitch Accent",
        "description": "Brief RGB channel misalignment — digital, glitch aesthetic, hi-tech",
        "params": {"offset_px": 3, "duration_frames": 2},
        "mood": "tech",
        "energy": 3,
        "best_roles": ["tech_moment", "digital", "problem", "system"],
        "sfx": "sfx/glitch_beep.wav",
    },
    "light_leak_overlay": {
        "id": "light_leak_overlay",
        "category": "overlay",
        "label": "Light Leak (from assets/overlays/)",
        "description": "Cinematic light leak overlay — cinematic warmth, analog feel",
        "params": {"overlay_file": "assets/overlays/light_leak_warm.mp4", "opacity": 0.3},
        "mood": "cinematic",
        "energy": 1,
        "best_roles": ["transition", "moment", "beauty"],
        "sfx": None,
    },
    "white_flash": {
        "id": "white_flash",
        "category": "light",
        "label": "White Flash",
        "description": "Sudden white frame flash for 1 frame — shock, transition",
        "params": {"duration_frames": 1},
        "mood": "shock",
        "energy": 5,
        "best_roles": ["cut", "transition", "shock"],
        "sfx": "sfx/camera_flash.wav",
    },
    "black_flash": {
        "id": "black_flash",
        "category": "light",
        "label": "Black Flash",
        "description": "Sudden black frame for 1 frame — emphasizes cut, creates pause",
        "params": {"duration_frames": 1},
        "mood": "dramatic",
        "energy": 3,
        "best_roles": ["cut", "emphasis", "pause"],
        "sfx": "sfx/blackout.wav",
    },
    "text_pop_scale": {
        "id": "text_pop_scale",
        "category": "text",
        "label": "Text Pop on Emphasis (Scale + Entrance)",
        "description": "Emphasis caption scales in quickly — reinforces the spoken word",
        "params": {"scale_from": 0.8, "scale_to": 1.0, "duration_frames": 4},
        "mood": "energetic",
        "energy": 2,
        "best_roles": ["number", "stat", "key_claim", "emphasis"],
        "sfx": "sfx/pop_scale.wav",
    },
    "emoji_sticker_pop": {
        "id": "emoji_sticker_pop",
        "category": "text",
        "label": "Emoji/Sticker Pop (Scale + Bounce)",
        "description": "Sticker/emoji bounces in with scale and slight rotation",
        "params": {"sticker_file": "assets/stickers/star.png", "scale": 0.1, "bounce": True},
        "mood": "playful",
        "energy": 3,
        "best_roles": ["celebration", "milestone", "lightness"],
        "sfx": "sfx/bounce_pop.wav",
    },
    "zoom_blur_transition": {
        "id": "zoom_blur_transition",
        "category": "transition",
        "label": "Zoom Blur / Whip Transition",
        "description": "Zoom out with motion blur, transition to next clip — dynamic cut",
        "params": {"blur_strength": 0.8, "zoom_out": 1.5},
        "mood": "dynamic",
        "energy": 4,
        "best_roles": ["transition", "cut", "energy_shift"],
        "sfx": "sfx/whoosh_zoom.wav",
    },
    "black_and_white_flash": {
        "id": "black_and_white_flash",
        "category": "light",
        "label": "Black & White Flash",
        "description": "Clip turns B&W for 0.3s then back to color — emphasis, contrast",
        "params": {"duration_frames": 9},  # 0.3s @ 30fps
        "mood": "emphasis",
        "energy": 3,
        "best_roles": ["contrast", "flashback", "memory"],
        "sfx": None,
    },
}

# All effect families (v3 + v4 new)
EFFECT_FAMILIES_V4 = {**_LEGACY_FAMILIES}

# Add new families for v4 effects
EFFECT_FAMILIES_V4.update({
    "camera_shake": {
        "ids": ["camera_shake"],
        "energy": 4,
        "mood": "tension",
        "best_roles": ["shock", "mistake", "urgency"],
        "description": "Handheld shake — creates urgency and visceral impact.",
        "avoid_after": [],
    },
    "freeze_zoom": {
        "ids": ["freeze_frame_zoom"],
        "energy": 4,
        "mood": "punctuation",
        "best_roles": ["punchline", "stat", "revelation"],
        "description": "Freeze frame with zoom-in — punctuation mark on a moment.",
        "avoid_after": ["freeze_zoom"],
    },
    "speed_ramp": {
        "ids": ["speed_ramp"],
        "energy": 3,
        "mood": "building",
        "best_roles": ["reveal", "build_up"],
        "description": "Slow start, fast end — creates momentum and drama.",
        "avoid_after": [],
    },
    "blur_in": {
        "ids": ["blur_in"],
        "energy": 1,
        "mood": "elegant",
        "best_roles": ["entry", "intro"],
        "description": "Soft focus into clarity — elegant entry, arrival.",
        "avoid_after": [],
    },
    "vignette_pulse": {
        "ids": ["vignette_pulse"],
        "energy": 2,
        "mood": "intimate",
        "best_roles": ["emotion", "close_up"],
        "description": "Darkened edges with pulse — draws eye to center, intimacy.",
        "avoid_after": [],
    },
    "rgb_split": {
        "ids": ["rgb_split"],
        "energy": 3,
        "mood": "tech",
        "best_roles": ["tech_moment", "digital"],
        "description": "RGB channel split — digital glitch aesthetic.",
        "avoid_after": ["rgb_split"],
    },
    "light_leak": {
        "ids": ["light_leak_overlay"],
        "energy": 1,
        "mood": "cinematic",
        "best_roles": ["transition", "beauty"],
        "description": "Cinematic light leak overlay — warm, analog feel.",
        "avoid_after": [],
    },
    "flash_white": {
        "ids": ["white_flash"],
        "energy": 5,
        "mood": "shock",
        "best_roles": ["cut", "shock"],
        "description": "White flash for 1 frame — shock, wipe transition.",
        "avoid_after": ["flash", "flash_white"],
    },
    "flash_black": {
        "ids": ["black_flash"],
        "energy": 3,
        "mood": "dramatic",
        "best_roles": ["cut", "emphasis"],
        "description": "Black frame for 1 frame — creates pause, emphasis on cut.",
        "avoid_after": ["flash", "flash_black"],
    },
    "text_pop": {
        "ids": ["text_pop_scale"],
        "energy": 2,
        "mood": "energetic",
        "best_roles": ["number", "key_claim", "emphasis"],
        "description": "Text scales in on emphasis caption — reinforces spoken word.",
        "avoid_after": [],
    },
    "emoji_pop": {
        "ids": ["emoji_sticker_pop"],
        "energy": 3,
        "mood": "playful",
        "best_roles": ["celebration", "milestone"],
        "description": "Emoji/sticker bounces in — playful, celebratory.",
        "avoid_after": [],
    },
    "whip_transition": {
        "ids": ["zoom_blur_transition"],
        "energy": 4,
        "mood": "dynamic",
        "best_roles": ["transition", "cut"],
        "description": "Zoom blur transition — dynamic, high-energy cut.",
        "avoid_after": [],
    },
    "bw_flash": {
        "ids": ["black_and_white_flash"],
        "energy": 3,
        "mood": "emphasis",
        "best_roles": ["contrast", "flashback"],
        "description": "B&W flash for 0.3s — creates contrast, dreamlike.",
        "avoid_after": [],
    },
})

# Keep effects that have no timeline-safe MLT implementation out of the
# planner and editor selectors. Their old IDs remain recognizable so existing
# plans fail with a useful validation message instead of silently doing
# nothing.
UNSUPPORTED_EFFECTS = {
    "speed_ramp": "speed ramps change clip timing and are not safe in a fixed-frame segment",
    "light_leak_overlay": "light leak overlays need a real imported overlay track",
    "text_pop_scale": "animated caption scale is not implemented in the subtitle track",
    "emoji_sticker_pop": "sticker assets and timing are not implemented in the render graph",
    "zoom_blur_transition": "transitions must be configured on a segment boundary",
}
RENDERABLE_EXTENDED_EFFECTS = set(EXTENDED_EFFECTS) - set(UNSUPPORTED_EFFECTS)


def is_renderable_effect(effect_id: str) -> bool:
    return effect_id in _LEGACY_CATALOG or effect_id in RENDERABLE_EXTENDED_EFFECTS


for _family_name, _family in list(EFFECT_FAMILIES_V4.items()):
    _family["ids"] = [effect_id for effect_id in _family.get("ids", [])
                      if is_renderable_effect(effect_id)]
    if not _family["ids"]:
        del EFFECT_FAMILIES_V4[_family_name]

# Merge legacy effects into extended catalog
EFFECT_CATALOG_V4 = {**_LEGACY_CATALOG, **EXTENDED_EFFECTS}


def catalog_for_api() -> list[dict]:
    """Expose only effects that have an MLT implementation."""
    roles = {effect_id: family["best_roles"]
             for family in _LEGACY_FAMILIES.values() for effect_id in family["ids"]}
    return [
        {**effect,
         "energy": effect.get("energy", 2),
         "mood": effect.get("mood", "neutral"),
         "best_roles": effect.get("best_roles", roles.get(effect_id, [])),
         "category": effect.get("category", "motion" if effect_id in _LEGACY_CATALOG else "overlay"),
         "motion": effect.get("motion", effect.get("category", "")),
         "light": effect.get("light", "")}
        for effect_id, effect in EFFECT_CATALOG_V4.items()
        if is_renderable_effect(effect_id)
    ]

# ============================================================================
# CUSTOM MY_EFFECTS SYSTEM: User favorites, rules, weights
# ============================================================================

class MyEffectsPreset:
    """User's custom effect collection: favorites, rules, rules weights."""

    def __init__(self, yaml_path: Optional[Path] = None):
        self.yaml_path = yaml_path or (PROJECT_ROOT / "presets" / "my_effects.yaml")
        self.favorites = {}  # {effect_id: {"weight": float, "tags": [str]}}
        self.rules = []  # [{text: str, priority: "hard|soft"}]
        self.dislikes = set()  # effect_ids to never use
        self.custom_assets = {}  # {name: {type, path, tags, when_to_use}}
        self.selected_rafiei_style: Optional[str] = None
        self.load()

    def load(self):
        """Load from YAML if exists."""
        if self.yaml_path.exists():
            import yaml
            data = yaml.safe_load(self.yaml_path.read_text()) or {}
            self.favorites = data.get("favorites", {})
            self.rules = data.get("rules", [])
            self.dislikes = set(data.get("dislikes", []))
            self.custom_assets = data.get("custom_assets", {})
            self.selected_rafiei_style = data.get("selected_rafiei_style")

    def save(self):
        """Save to YAML."""
        import yaml
        self.yaml_path.parent.mkdir(exist_ok=True, parents=True)
        data = {
            "favorites": self.favorites,
            "rules": self.rules,
            "dislikes": list(self.dislikes),
            "custom_assets": self.custom_assets,
            "selected_rafiei_style": self.selected_rafiei_style,
        }
        self.yaml_path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))

    def add_favorite(self, effect_id: str, weight: float = 1.0, tags: list[str] | None = None):
        """Mark an effect as favorite."""
        self.favorites[effect_id] = {"weight": weight, "tags": tags or []}
        self.save()

    def remove_favorite(self, effect_id: str):
        """Unmark as favorite."""
        self.favorites.pop(effect_id, None)
        self.save()

    def add_rule(self, text: str, priority: str = "hard"):
        """Add a hard rule (editor's guidance on when to use which effects)."""
        self.rules.append({"text": text, "priority": priority})
        self.save()

    def add_dislike(self, effect_id: str):
        """Mark effect as never use."""
        self.dislikes.add(effect_id)
        self.save()


class EffectFeedback:
    """Learning from user edits: save segment→effect changes for few-shot learning."""

    def __init__(self, jsonl_path: Optional[Path] = None):
        self.jsonl_path = jsonl_path or (PROJECT_ROOT / "presets" / "effect_feedback.jsonl")
        self.examples = []
        self.load()

    def load(self):
        """Load feedback examples (last 20)."""
        if self.jsonl_path.exists():
            import jsonlines
            with jsonlines.open(self.jsonl_path) as reader:
                self.examples = list(reader)[-20:]  # Keep last 20

    def add(self, segment_text: str, role: str, old_effect: str, new_effect: str):
        """Log a user edit."""
        self.examples.append({
            "segment_text": segment_text,
            "role": role,
            "old_effect": old_effect,
            "new_effect": new_effect,
        })
        # Keep only last 20
        self.examples = self.examples[-20:]
        self.save()

    def save(self):
        """Save to JSONL."""
        import jsonlines
        self.jsonl_path.parent.mkdir(exist_ok=True, parents=True)
        with jsonlines.open(self.jsonl_path, mode="w") as writer:
            for ex in self.examples:
                writer.write(ex)

    def as_prompt_examples(self) -> str:
        """Format examples for LLM prompt (few-shot)."""
        if not self.examples:
            return ""
        lines = ["## Examples from user edits (last 20):"]
        for ex in self.examples[-5:]:  # Show last 5 in prompt
            lines.append(
                f"  - Segment: \"{ex['segment_text']}\", Role: {ex['role']} "
                f"→ Old: {ex['old_effect']}, New: {ex['new_effect']}"
            )
        return "\n".join(lines)


# ============================================================================
# EFFECT RENDERING: V4 filters (shake, blur, vignette, RGB split, etc.)
# ============================================================================

def effect_filter_xml_v4(effect_id: str, frames: int, width: int, height: int,
                         punch_frames: int, cover_scale: float = 1.0) -> str:
    """Generate MLT filter XML for v4 effects.

    Falls back to v3 rendering if effect not found.
    Unsupported extended effects fail rather than silently rendering unchanged.
    """
    from engine.effects import effect_filter_xml as legacy_render

    if effect_id not in EXTENDED_EFFECTS:
        return legacy_render(effect_id, frames, width, height, punch_frames,
                             cover_scale=cover_scale)

    if effect_id in UNSUPPORTED_EFFECTS:
        raise ValueError(f"effect {effect_id!r} cannot be rendered: {UNSUPPORTED_EFFECTS[effect_id]}")

    spec = EXTENDED_EFFECTS[effect_id]
    result = ""
    cs = cover_scale
    # Legacy effects always apply the source-to-portrait cover transform. V4
    # effects without their own affine need it as well or 16:9 input letterboxes.
    if cs > 1.001 and effect_id not in {"camera_shake", "freeze_frame_zoom", "zoom_blur_transition"}:
        result = (f'<filter mlt_service="affine">'
                  f'<property name="transition.rect">0={_rect(cs, width, height)}</property>'
                  f'<property name="transition.fill">1</property></filter>')

    # Camera shake: deterministic small translations over an overscanned frame.
    if effect_id == "camera_shake":
        intensity = max(1, int(spec["params"].get("intensity", 2)))
        freq = max(1, int(spec["params"].get("frequency", 8)))
        step = max(1, round(30 / (freq * 2)))
        scale = 1.06 * cs
        w, h = width * scale, height * scale
        offsets = ((intensity, -intensity), (-intensity, intensity),
                   (intensity, intensity), (-intensity, -intensity))
        keyframes = []
        for frame in range(0, max(frames, 1), step):
            dx, dy = offsets[(frame // step) % len(offsets)]
            x, y = (width - w) / 2 + dx, (height - h) / 2 + dy
            keyframes.append(f"{frame}={x:.1f} {y:.1f} {w:.1f} {h:.1f} 1")
        result += f"""<filter mlt_service="affine">
            <property name="transition.rect">{';'.join(keyframes)}</property>
            <property name="transition.fill">1</property>
        </filter>"""

    # Freeze frame + zoom
    elif effect_id == "freeze_frame_zoom":
        zoom_to = spec["params"].get("zoom_to", 1.3)
        hold_f = min(max(0, spec["params"].get("hold_frames", 3)), max(frames - 1, 0))
        zoom_end = min(max(frames - 1, 0), hold_f + 15)
        result += f"""<filter mlt_service="freeze">
            <property name="frame">{hold_f}</property>
            <property name="freeze_after">1</property>
        </filter>"""
        result += f"""<filter mlt_service="affine">
            <property name="transition.rect">0={_rect(1.0 * cs, width, height)};{zoom_end}={_rect(zoom_to * cs, width, height)}</property>
            <property name="transition.fill">1</property>
        </filter>"""

    # Blur in: keyframe the supported MLT blur parameter down to its minimum.
    elif effect_id == "blur_in":
        blur_start = spec["params"].get("blur_start", 20)
        result += f"""<filter mlt_service="boxblur">
            <property name="blur">0={blur_start};{min(9, max(frames - 1, 1))}=1</property>
        </filter>"""

    # Vignette pulse: animate MLT's native vignette opacity.
    elif effect_id == "vignette_pulse":
        strength = min(spec["params"].get("vignette_strength", 0.4), 0.16)
        result += f"""<filter mlt_service="vignette">
            <property name="radius">0.78</property>
            <property name="smooth">0.9</property>
            <property name="opacity">0=0;{min(8, max(frames - 1, 1))}={strength};{max(frames - 1, 1)}=0.08</property>
        </filter>"""

    # RGB split: shift the red and blue channels in opposite directions.
    elif effect_id == "rgb_split":
        offset = int(spec["params"].get("offset_px", 3))
        result += f"""<filter mlt_service="avfilter.rgbashift">
            <property name="av.rh">{offset}</property>
            <property name="av.bh">{-offset}</property>
            <property name="av.edge">smear</property>
        </filter>"""

    # A one-frame exposure flash at the beginning of the segment.
    elif effect_id in ("white_flash", "black_flash"):
        brightness = 1 if effect_id == "white_flash" else -1
        result += f"""<filter mlt_service="avfilter.eq">
            <property name="av.brightness">0={brightness};1=0</property>
            <property name="av.eval">frame</property>
        </filter>"""

    # Desaturate briefly, then restore the original colour.
    elif effect_id == "black_and_white_flash":
        if frames <= 10:
            saturation = "0"
        else:
            saturation = "0=0;9=0;10=1"
        result += f"""<filter mlt_service="avfilter.hue">
            <property name="av.s">{saturation}</property>
            <property name="position">filter</property>
        </filter>"""

    return result


def _rect(z: float, width: int, height: int, x: float = 0.5, y: float = 0.5) -> str:
    """MLT affine rect string."""
    w, h = width * z, height * z
    return f"{-(w - width) * x:.0f} {-(h - height) * y:.0f} {w:.0f} {h:.0f} 1"


# ============================================================================
# PREVIEW GENERATION: Render 2-second preview clips for each effect
# ============================================================================

def generate_preview_clips(video_path: Path, output_dir: Path):
    """Actually render short previews for every selectable effect.

    An effect is reported as rendered only after ffprobe confirms the temporary
    MP4 has a video stream and positive duration.
    """
    import subprocess
    import logging
    import math

    log = logging.getLogger(__name__)
    video_path = Path(video_path).resolve()
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Get video duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1:novalue=1", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        duration = float(result.stdout.strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("video has no positive finite duration")
    except Exception as e:
        log.error(f"Cannot probe video: {e}")
        return [], [("source", str(e))]

    preview_duration = min(2.0, duration)
    preview_start = max(0.0, (duration - preview_duration) / 2)
    preview_end = preview_start + preview_duration
    if round(preview_duration * 30) < 1:
        return [], [("source", "video is shorter than one 30 fps frame")]

    # Track which effects actually rendered
    rendered = []
    failed = []

    from engine.schema import EditPlan
    from engine.build_mlt import build
    from engine.render import render

    for effect_id, spec in EFFECT_CATALOG_V4.items():
        if not is_renderable_effect(effect_id):
            continue
        output_file = output_dir / f"{effect_id}.mp4"
        temporary_file = output_dir / f".{effect_id}.pending.mp4"

        # Reuse only a playable, nonempty cached artifact.
        if output_file.exists():
            try:
                media = json.loads(subprocess.check_output([
                    "ffprobe", "-v", "error", "-show_entries",
                    "format=duration:stream=codec_type", "-of", "json", str(output_file),
                ], text=True, timeout=10))
                valid = (output_file.stat().st_size > 0
                         and float(media.get("format", {}).get("duration", 0)) > 0
                         and any(s.get("codec_type") == "video" for s in media.get("streams", [])))
                if valid:
                    rendered.append(effect_id)
                    continue
            except Exception:
                pass
            output_file.unlink(missing_ok=True)

        try:
            plan = EditPlan(**{
                "version": "0.2",
                "style": "rafiei_reel",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "source": str(video_path),
                "segments": [{
                    "id": "s1",
                    "in": preview_start,
                    "out": preview_end,
                    "zoom": {"from": 1.0, "to": 1.0},
                }],
                "visual_effects": [{"segment_id": "s1", "type": effect_id}],
                "captions": [],
                "broll": [],
                "sfx": [],
                "export": {"file": str(output_file), "crf": 20},
            })
            build_dir = output_dir / f".{effect_id}.build"
            mlt, _ = build(plan, build_dir, base_dir=video_path.parent)
            render(mlt, temporary_file, preview=True)
            media = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration:stream=codec_type", "-of", "json", str(temporary_file),
            ], text=True, timeout=10))
            if (not any(s.get("codec_type") == "video" for s in media.get("streams", []))
                    or float(media.get("format", {}).get("duration", 0)) <= 0):
                raise RuntimeError("rendered effect preview has no playable video stream")
            temporary_file.replace(output_file)
            rendered.append(effect_id)

        except Exception as e:
            log.warning(f"Cannot render preview for {effect_id}: {e}")
            temporary_file.unlink(missing_ok=True)
            failed.append((effect_id, str(e)))

    log.info(f"Rendered {len(rendered)} effect previews; {len(failed)} failed")
    return rendered, failed
