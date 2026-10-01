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


def canonical_effect(effect_id: str) -> str:
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
                      punch_frames: int) -> str | None:
    last = max(1, frames - 1)
    short = min(max(1, punch_frames), last)
    r = lambda z, x=0.5, y=0.5: _rect(z, width, height, x, y)
    if motion == "steady":
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
    }
    return levels[light]


def effect_filter_xml(effect_id: str, frames: int, width: int, height: int,
                      punch_frames: int) -> str:
    spec = EFFECT_CATALOG[canonical_effect(effect_id)]
    motion = _motion_keyframes(spec["motion"], frames, width, height, punch_frames)
    light = _light_keyframes(spec["light"], frames)
    result = ""
    if motion:
        result += ('<filter mlt_service="affine">'
                   f'<property name="transition.rect">{motion}</property>'
                   '<property name="transition.fill">1</property></filter>')
    if light:
        result += ('<filter mlt_service="brightness">'
                   f'<property name="level">{light}</property></filter>')
    return result
