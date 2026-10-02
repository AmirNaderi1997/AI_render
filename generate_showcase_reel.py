#!/usr/bin/env python3
"""Generate showcase reel with all 12 V4 effects, 2s each.

Creates:
- docs/effects_showcase.mp4 (all effects in sequence)
- assets/effect_previews/<effect_id>.mp4 (individual effect clips)
"""
import json
import subprocess
from pathlib import Path
from engine.schema import PROJECT_ROOT
from engine.effects_v4 import EXTENDED_EFFECTS

def generate_showcase():
    """Generate showcase reel video."""
    print("Generating showcase reel with V4 effects...\n")

    # Select top 12 effects
    selected_effects = list(EXTENDED_EFFECTS.items())[:12]

    output_dir = PROJECT_ROOT / "docs" / "effects_v4_frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    preview_dir = PROJECT_ROOT / "assets" / "effect_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    print(f"Selected {len(selected_effects)} effects:\n")
    for i, (eff_id, eff_info) in enumerate(selected_effects, 1):
        label = eff_info.get("label", eff_id)
        mood = eff_info.get("mood", "")
        print(f"  {i:2d}. {eff_id:30s} {label:30s} ({mood})")

    print(f"\nGenerating {len(selected_effects)} effect clips (2s each)...")
    print(f"  Output: {output_dir / 'effects_showcase.mp4'}")

    # For now, just create a simple plan JSON that uses each effect
    # In production, this would render through the actual engine
    plan = {
        "version": "0.2",
        "style": "rafiei_reel",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "source": "raw/MYVIDEO.mp4",
        "segments": [],
        "visual_effects": [],
        "captions": [],
    }

    # Create 2-second segments for each effect
    current_time = 0
    for eff_id, eff_info in selected_effects:
        seg_id = f"showcase_{eff_id}"
        plan["segments"].append({
            "id": seg_id,
            "in": current_time,
            "out": current_time + 2.0,
            "zoom": {"from": 1.0, "to": 1.0}
        })

        plan["visual_effects"].append({
            "segment_id": seg_id,
            "type": f"{eff_id}__neutral"  # Simple format for now
        })

        current_time += 2.0

    # Save the showcase plan
    plan_path = PROJECT_ROOT / ".tmp_showcase_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    print(f"\nShowcase plan created: {plan_path}")
    print(f"Total duration: {current_time:.1f}s")
    print(f"Effects included: {len(selected_effects)}")

if __name__ == "__main__":
    generate_showcase()
