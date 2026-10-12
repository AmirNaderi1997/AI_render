"""One hundred bounded MLT effect presets: ten motions times ten light treatments.

The catalog is shared by validation, planner, renderer, and UI. Effects never
change clip duration. MLT affine and brightness are the only required filters.
"""
from __future__ import annotations

MOTIONS = {
    "steady": "Unchanged framing",
    "hold_close": "Held close framing",
    "punch": "Quick punch in",
    "slow_push": "Slow push in",
    "slow_pull": "Slow pull out",
    "pan_left": "Pan left inside overscan",
    "pan_right": "Pan right inside overscan",
    "tilt_up": "Tilt up inside overscan",
    "tilt_down": "Tilt down inside overscan",
    "drift_diag": "Gentle diagonal drift",
}

LIGHTS = {
    "neutral": "No light change",
    "lift_soft": "Soft light lift",
    "lift_medium": "Medium light lift",
    "dim_soft": "Soft darkening",
    "dim_medium": "Medium darkening",
    "pulse_start": "Brief light accent at start",
    "pulse_end": "Brief light accent at end",
    "fade_in": "Gentle light fade in",
    "fade_out": "Gentle light fade out",
    "breath": "Subtle light swell",
    "desaturate": "Full desaturation — cinematic B&W treatment",
}

EFFECT_CATALOG = {
    f"{motion}__{light}": {"id": f"{motion}__{light}",
                             "motion": motion, "light": light,
                             "label": f"{motion.replace('_', ' ').title()} · {light.replace('_', ' ').title()}",
                             "description": f"{motion_description}; {light_description}",
                             "needs_framing_review": motion in {
                                 "pan_left", "pan_right", "tilt_up", "tilt_down", "drift_diag"},
                             "strong_accent": light in {"pulse_start", "pulse_end"}}
    for motion, motion_description in MOTIONS.items()
    for light, light_description in LIGHTS.items()
}

LEGACY_EFFECTS = {
    "steady": "steady__neutral", "punch": "punch__neutral",
    "slow_push": "slow_push__neutral", "slow_pull": "slow_pull__neutral",
    "pan_left": "pan_left__neutral", "pan_right": "pan_right__neutral",
    "flash": "steady__pulse_start",
}

# Named effect families for the LLM planner.
# The LLM sees family names + descriptions; Python picks the specific effect ID.
EFFECT_FAMILIES: dict[str, dict] = {
    "still": {
        "ids": ["steady__neutral"],
        "energy": 1, "mood": "neutral",
        "best_roles": ["exposition", "list_item", "pause", "transition"],
        "description": "Locked frame, no movement, no light change. Safe default for calm speech.",
        "avoid_after": [],
    },
    "lift": {
        "ids": ["steady__lift_soft", "steady__lift_medium"],
        "energy": 2, "mood": "optimistic",
        "best_roles": ["claim", "benefit", "cta", "solution"],
        "description": "Still frame with gentle brightening — warmth and confidence.",
        "avoid_after": ["lift"],
    },
    "breathe": {
        "ids": ["steady__breath", "steady__fade_in"],
        "energy": 1, "mood": "calm",
        "best_roles": ["story", "reflection", "transition"],
        "description": "Gentle light swell — a breath of space between ideas.",
        "avoid_after": [],
    },
    "dim": {
        "ids": ["steady__dim_soft", "steady__dim_medium"],
        "energy": 1, "mood": "serious",
        "best_roles": ["problem", "warning", "contrast"],
        "description": "Still frame with subtle darkening — weight and gravity.",
        "avoid_after": ["dim"],
    },
    "flash": {
        "ids": ["steady__pulse_start", "punch__pulse_start"],
        "energy": 4, "mood": "impact",
        "best_roles": ["hook", "turning_point", "number", "stat"],
        "description": "Brief light flash at the start — snaps attention. Use sparingly (max 1 per 8 s).",
        "avoid_after": ["flash", "flash_end", "punch_bright"],
    },
    "flash_end": {
        "ids": ["steady__pulse_end", "punch__pulse_end"],
        "energy": 3, "mood": "impact",
        "best_roles": ["punchline", "cta", "conclusion"],
        "description": "Light flash at the end — energy on the exit frame.",
        "avoid_after": ["flash", "flash_end"],
    },
    "close_hold": {
        "ids": ["hold_close__neutral", "hold_close__lift_soft"],
        "energy": 2, "mood": "intimate",
        "best_roles": ["question", "emotion", "direct_address"],
        "description": "Slightly closer held framing — intimacy and direct eye contact.",
        "avoid_after": [],
    },
    "punch": {
        "ids": ["punch__neutral", "punch__lift_soft"],
        "energy": 4, "mood": "assertive",
        "best_roles": ["key_claim", "emphasis", "call_to_action", "hook"],
        "description": "Quick zoom-in — lands like a visual exclamation point on a key word.",
        "avoid_after": ["punch", "punch_bright"],
    },
    "punch_bright": {
        "ids": ["punch__lift_medium", "punch__fade_in"],
        "energy": 5, "mood": "energetic",
        "best_roles": ["hook", "turning_point", "strongest_claim"],
        "description": "Punch-in with brightening — maximum impact. Use at most once per video.",
        "avoid_after": ["punch", "punch_bright", "flash"],
    },
    "slow_push": {
        "ids": ["slow_push__neutral", "slow_push__lift_soft"],
        "energy": 2, "mood": "building",
        "best_roles": ["explanation", "list_item", "build_up"],
        "description": "Slow creep forward — builds engagement as the idea develops.",
        "avoid_after": ["slow_push", "slow_push_bright"],
    },
    "slow_push_bright": {
        "ids": ["slow_push__lift_medium", "slow_push__breath"],
        "energy": 3, "mood": "warm",
        "best_roles": ["benefit", "solution", "positive_claim"],
        "description": "Slow push with warming — optimistic, forward momentum.",
        "avoid_after": ["slow_push", "slow_push_bright"],
    },
    "slow_pull": {
        "ids": ["slow_pull__neutral", "slow_pull__dim_soft"],
        "energy": 2, "mood": "reflective",
        "best_roles": ["conclusion", "reflection", "before_cta"],
        "description": "Gentle pull back — perspective and pause before the close.",
        "avoid_after": ["slow_pull"],
    },
    "slow_pull_dim": {
        "ids": ["slow_pull__dim_medium", "slow_pull__fade_out"],
        "energy": 1, "mood": "somber",
        "best_roles": ["problem", "contrast", "low_point"],
        "description": "Pull back with darkening — weight and consequence.",
        "avoid_after": ["slow_pull", "slow_pull_dim"],
    },
    "drift": {
        "ids": ["pan_left__neutral", "pan_right__neutral", "drift_diag__neutral"],
        "energy": 2, "mood": "dynamic",
        "best_roles": ["scene_setting", "list_item", "variety"],
        "description": "Lateral or diagonal drift — visual variety. Always check framing.",
        "avoid_after": [],
        "framing_check": True,
    },
    "tilt": {
        "ids": ["tilt_up__lift_soft", "tilt_down__dim_soft"],
        "energy": 3, "mood": "dramatic",
        "best_roles": ["reveal", "turning_point"],
        "description": "Tilt with light — dramatic reveal. Requires framing check.",
        "avoid_after": ["drift", "tilt"],
        "framing_check": True,
    },
    "bw": {
        "ids": ["steady__desaturate", "slow_push__desaturate"],
        "energy": 1, "mood": "serious",
        "best_roles": ["loss", "contrast", "flashback", "heavy_statement", "warning"],
        "description": "Full desaturation — cinematic B&W. Use for weight, consequence, or heavy emotional beats. Max once per video.",
        "avoid_after": ["bw"],
    },
}

# Annotate catalog entries with their family
for _family_name, _family in EFFECT_FAMILIES.items():
    for _eid in _family["ids"]:
        if _eid in EFFECT_CATALOG:
            EFFECT_CATALOG[_eid]["family"] = _family_name
            EFFECT_CATALOG[_eid]["energy"] = _family["energy"]
            EFFECT_CATALOG[_eid]["mood"] = _family["mood"]
# Remaining entries (not in any family) get family="other"
for _eid, _entry in EFFECT_CATALOG.items():
    if "family" not in _entry:
        _entry["family"] = "other"
        _entry["energy"] = 2
        _entry["mood"] = "neutral"


def families_for_llm() -> list[dict]:
    """Compact family list for the planner LLM prompt (~15 items, not 100)."""
    return [
        {
            "family": name,
            "energy": info["energy"],
            "mood": info["mood"],
            "best_roles": info["best_roles"],
            "description": info["description"],
            "example_id": info["ids"][0],
            "framing_check": info.get("framing_check", False),
        }
        for name, info in EFFECT_FAMILIES.items()
    ]


def family_to_effect_id(family: str, segment_index: int = 0, prev_family: str = "") -> str:
    """Pick a specific effect ID from a family.

    Rotates through the family's IDs to provide variety. Avoids the first ID
    if it was the previous segment's choice and alternatives exist.
    """
    info = EFFECT_FAMILIES.get(family)
    if not info:
        return "steady__neutral"
    ids = info["ids"]
    idx = segment_index % len(ids)
    chosen = ids[idx]
    # If chosen equals the previous segment's family base ID, try the next one
    if len(ids) > 1 and chosen == ids[0] and prev_family == family:
        chosen = ids[1 % len(ids)]
    return chosen


def canonical_effect(effect_id: str) -> str:
    # Accept family names as shorthand
    if effect_id in EFFECT_FAMILIES:
        return EFFECT_FAMILIES[effect_id]["ids"][0]
    effect_id = LEGACY_EFFECTS.get(effect_id, effect_id)
    if effect_id not in EFFECT_CATALOG:
        raise ValueError(f"unknown visual effect: {effect_id}")
    return effect_id


def catalog_for_api() -> list[dict]:
    return list(EFFECT_CATALOG.values())


def _rect(z: float, width: int, height: int, x: float = 0.5, y: float = 0.5) -> str:
    w, h = width * z, height * z
    return f"{-(w - width) * x:.0f} {-(h - height) * y:.0f} {w:.0f} {h:.0f} 1"


def _motion_keyframes(motion: str, frames: int, width: int, height: int,
                      punch_frames: int, cover_scale: float = 1.0) -> str | None:
    last = max(1, frames - 1)
    short = min(max(1, punch_frames), last)
    cs = cover_scale
    r = lambda z, x=0.5, y=0.5: _rect(z * cs, width, height, x, y)
    if motion == "steady":
        if cs > 1.01:
            return f"0={r(1.0)}"
        return None
    if motion == "hold_close":
        return f"0={r(1.10)}"
    if motion == "punch":
        return f"0={r(1.0)};{short}={r(1.15)}"
    if motion == "slow_push":
        return f"0={r(1.0)};{last}={r(1.08)}"
    if motion == "slow_pull":
        return f"0={r(1.08)};{last}={r(1.0)}"
    endpoints = {
        "pan_left": (r(1.12, 1.0, 0.5), r(1.12, 0.0, 0.5)),
        "pan_right": (r(1.12, 0.0, 0.5), r(1.12, 1.0, 0.5)),
        "tilt_up": (r(1.12, 0.5, 1.0), r(1.12, 0.5, 0.0)),
        "tilt_down": (r(1.12, 0.5, 0.0), r(1.12, 0.5, 1.0)),
        "drift_diag": (r(1.12, 0.0, 0.0), r(1.12, 1.0, 1.0)),
    }
    start, end = endpoints[motion]
    return f"0={start};{last}={end}"


def _light_keyframes(light: str, frames: int) -> str | None:
    last = max(1, frames - 1)
    short = min(3, last)
    levels = {
        "neutral": None,
        "lift_soft": "0=1.04", "lift_medium": "0=1.08",
        "dim_soft": "0=0.96", "dim_medium": "0=0.92",
        "pulse_start": f"0=1.20;{short}=1.0",
        "pulse_end": f"0=1.0;{max(0, last-short)}=1.0;{last}=1.20",
        "fade_in": f"0=0.82;{min(6, last)}=1.0",
        "fade_out": f"0=1.0;{max(0, last-6)}=1.0;{last}=0.82",
        "breath": f"0=1.0;{max(1, last//2)}=1.05;{last}=1.0",
        "desaturate": None,  # handled separately via avfilter.hue
    }
    return levels[light]


def effect_filter_xml(effect_id: str, frames: int, width: int, height: int,
                      punch_frames: int, cover_scale: float = 1.0) -> str:
    spec = EFFECT_CATALOG[canonical_effect(effect_id)]
    motion = _motion_keyframes(spec["motion"], frames, width, height, punch_frames,
                               cover_scale=cover_scale)
    light = _light_keyframes(spec["light"], frames)
    result = ""
    if motion:
        result += ('<filter mlt_service="affine">'
                   f'<property name="transition.rect">{motion}</property>'
                   '<property name="transition.fill">1</property></filter>')
    if light:
        result += ('<filter mlt_service="brightness">'
                   f'<property name="level">{light}</property></filter>')
    if spec["light"] == "desaturate":
        result += ('<filter mlt_service="avfilter.hue">'
                   '<property name="av.s">0</property>'
                   '<property name="position">filter</property></filter>')
    return result
