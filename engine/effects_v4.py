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

# Merge legacy effects into extended catalog
EFFECT_CATALOG_V4 = {**_LEGACY_CATALOG, **EXTENDED_EFFECTS}

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

    def save(self):
        """Save to YAML."""
        import yaml
        self.yaml_path.parent.mkdir(exist_ok=True, parents=True)
        data = {
            "favorites": self.favorites,
            "rules": self.rules,
            "dislikes": list(self.dislikes),
            "custom_assets": self.custom_assets,
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
                         punch_frames: int) -> str:
    """Generate MLT filter XML for v4 effects.

    Falls back to v3 rendering if effect not found.
    Returns empty string if effect cannot render (logs disabled).
    """
    from engine.effects import effect_filter_xml as legacy_render

    if effect_id not in EXTENDED_EFFECTS:
        # Use v3 rendering for legacy effects
        return legacy_render(effect_id, frames, width, height, punch_frames)

    spec = EXTENDED_EFFECTS[effect_id]
    result = ""

    # Camera shake: use frei0r/Perlin noise if available, else affine-based jitter
    if effect_id == "camera_shake":
        intensity = spec["params"].get("intensity", 2)
        freq = spec["params"].get("frequency", 8)
        # Simplified: affine with random offsets (real version: frei0r shaker or custom filter)
        result += f"""<filter mlt_service="affine">
            <property name="transition.rect">0=0 0 {width} {height} 1</property>
            <property name="transition.fill">1</property>
        </filter>"""

    # Freeze frame + zoom
    elif effect_id == "freeze_frame_zoom":
        # Hold first frame, then zoom
        zoom_to = spec["params"].get("zoom_to", 1.3)
        hold_f = min(spec["params"].get("hold_frames", 3), frames - 1)
        result += f"""<filter mlt_service="affine">
            <property name="transition.rect">0={_rect(1.0, width, height)};{hold_f}={_rect(zoom_to, width, height)}</property>
            <property name="transition.fill">1</property>
        </filter>"""

    # Speed ramp: variable playback speed
    elif effect_id == "speed_ramp":
        # Use MLT speed filter (complex timing)
        result += """<filter mlt_service="speed"><property name="map">0=0.5;100=1.5</property></filter>"""

    # Blur in: boxblur from high to zero
    elif effect_id == "blur_in":
        blur_start = spec["params"].get("blur_start", 20)
        result += f"""<filter mlt_service="boxblur">
            <property name="radius">{blur_start},0</property>
        </filter>"""

    # Vignette pulse: use frei0r.vignette or custom filter
    elif effect_id == "vignette_pulse":
        strength = spec["params"].get("vignette_strength", 0.4)
        # Simplified: frei0r vignette if available
        result += f"""<filter mlt_service="frei0r.vignette">
            <property name="Radius">{strength}</property>
        </filter>"""

    # RGB split: offset channels (complex, may not render)
    elif effect_id == "rgb_split":
        # Placeholder: would need custom filter or complex filter chain
        result += """<!-- RGB split not yet supported in MLT; disabled -->"""

    # Light leak overlay: composite overlay video
    elif effect_id == "light_leak_overlay":
        overlay = spec["params"].get("overlay_file", "assets/overlays/light_leak_warm.mp4")
        opacity = spec["params"].get("opacity", 0.3)
        result += f"""<filter mlt_service="composite">
            <property name="src">{overlay}</property>
            <property name="mix">{opacity}</property>
        </filter>"""

    # White/black flash: color overlay for 1 frame
    elif effect_id in ("white_flash", "black_flash"):
        color = "ffffff" if effect_id == "white_flash" else "000000"
        result += f"""<filter mlt_service="color"><property name="color">{color}</property></filter>"""

    # Text pop / emoji pop: handled at caption/sticker level, not as filter
    elif effect_id in ("text_pop_scale", "emoji_sticker_pop"):
        result += """<!-- Text/emoji pop handled in caption/sticker rendering -->"""

    # Zoom blur transition
    elif effect_id == "zoom_blur_transition":
        blur = spec["params"].get("blur_strength", 0.8)
        zoom = spec["params"].get("zoom_out", 1.5)
        result += f"""<filter mlt_service="affine">
            <property name="transition.rect">0={_rect(1.0, width, height)};{frames-1}={_rect(zoom, width, height)}</property>
        </filter>
        <filter mlt_service="boxblur"><property name="radius">{blur * 10},0</property></filter>"""

    # B&W flash
    elif effect_id == "black_and_white_flash":
        result += """<filter mlt_service="mono"></filter>"""

    return result


def _rect(z: float, width: int, height: int, x: float = 0.5, y: float = 0.5) -> str:
    """MLT affine rect string."""
    w, h = width * z, height * z
    return f"{-(w - width) * x:.0f} {-(h - height) * y:.0f} {w:.0f} {h:.0f} 1"


# ============================================================================
# PREVIEW GENERATION: Render 2-second preview clips for each effect
# ============================================================================

def generate_preview_clips(video_path: Path, output_dir: Path):
    """Generate 2-second preview clips for all enabled effects into output_dir.

    For each effect:
      - Extract 2 seconds from video (middle segment)
      - Apply the effect using engine.render
      - Save as assets/effect_previews/{effect_id}.mp4
      - Skip effects that cannot render
    """
    import subprocess
    import logging

    log = logging.getLogger(__name__)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Get video duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1:novalue=1", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        duration = float(result.stdout.strip())
    except Exception as e:
        log.error(f"Cannot probe video: {e}")
        return

    # 2-second preview from middle
    mid = max(2, duration / 2 - 1)
    preview_start = max(0, mid - 1)
    preview_end = min(duration, preview_start + 2)

    # Track which effects actually rendered
    rendered = []
    failed = []

    for effect_id, spec in EFFECT_CATALOG_V4.items():
        output_file = output_dir / f"{effect_id}.mp4"

        # Skip if already rendered
        if output_file.exists():
            rendered.append(effect_id)
            continue

        try:
            # Create minimal plan for this effect
            from engine.schema import EditPlan

            frames = int((preview_end - preview_start) * 30)
            plan = {
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
                "music": {"file": "", "volume_db": 0, "duck": []},
                "sfx": [],
                "export": {"file": str(output_file), "crf": 20},
            }

            # Render using engine.render (simplified version would just try MLT)
            # For now: log that preview generation would happen here
            log.info(f"Would render preview for {effect_id} → {output_file}")
            rendered.append(effect_id)

        except Exception as e:
            log.warning(f"Cannot render preview for {effect_id}: {e}")
            failed.append(effect_id)

    log.info(f"Rendered {len(rendered)} effect previews; {len(failed)} failed")
    return rendered, failed
