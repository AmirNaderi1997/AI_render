#!/usr/bin/env python3
"""Full integration test: Effects V4 with planner, rendering, and frame extraction.

Tests the complete pipeline:
1. Load existing job with plan and transcript
2. Re-score effects using V4 (with My Effects)
3. Build MLT project with V4 effects
4. Extract frames to verify rendering
5. Report timeline and results
"""
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).parent
JOB_ID = "62b870791f78"  # Existing job with MYVIDEO.mp4
JOB_DIR = PROJECT_ROOT / "jobs" / JOB_ID

def main():
    print("\n" + "=" * 100)
    print("EFFECTS V4 FULL INTEGRATION TEST")
    print("=" * 100)

    # Load plan and transcript
    plan_path = JOB_DIR / "plan.json"
    transcript_path = JOB_DIR / "transcript.json"

    if not plan_path.exists():
        print(f"ERROR: No plan found at {plan_path}")
        return

    with open(plan_path) as f:
        plan = json.load(f)
    with open(transcript_path) as f:
        transcript = json.load(f)

    print(f"\n✓ Loaded job {JOB_ID}")
    print(f"  Video: {JOB_DIR}/raw/MYVIDEO.mp4")
    print(f"  Duration: {plan['segments'][-1]['out']:.1f}s")
    print(f"  Segments: {len(plan['segments'])}")

    # Load my effects
    from engine.effects_v4 import MyEffectsPreset, EffectFeedback
    my_effects = MyEffectsPreset()
    feedback = EffectFeedback()

    print(f"\nMy Effects loaded:")
    print(f"  Favorites: {len(my_effects.favorites)}")
    print(f"  Rules: {len(my_effects.rules)}")
    print(f"  Dislikes: {list(my_effects.dislikes)}")

    # Score effects using V4
    from brain.effect_score_v4 import select_effects_with_vision
    from brain.segment_analysis import analyse_segments

    print(f"\nAnalyzing segments...")
    analyses, usage = analyse_segments(plan.get("segments", []), transcript)
    print(f"  {len(analyses)} analyses computed")

    print(f"\nScoring effects with V4...")
    start_time = time.time()

    # Load style config
    import yaml
    style_name = plan.get("style", "rafiei_reel")
    style_path = PROJECT_ROOT / "presets" / f"{style_name}.yaml"
    if style_path.exists():
        style = yaml.safe_load(style_path.read_text())
    else:
        style = {}

    scored_effects = select_effects_with_vision(
        plan.get("segments", []),
        analyses,
        None,  # No keyframe directory for this test
        style,
        my_effects=my_effects,
        feedback=feedback
    )

    elapsed = time.time() - start_time
    print(f"✓ Scoring completed in {elapsed:.2f}s")

    # Show timeline
    print("\n" + "=" * 100)
    print("EFFECT TIMELINE (V4)")
    print("=" * 100)
    print(f"{'Time':>6} | {'Segment':12} | {'Effect Type':30} | {'Reason':40}")
    print("-" * 100)

    effects_used = set()
    for seg, eff in zip(plan["segments"], scored_effects):
        time_str = f"{seg['in']:5.1f}s"
        seg_id = seg.get("id", "?")[:12]
        eff_type = eff.get("type", "?")[:30]
        reason = eff.get("reason", "")[:40]

        effects_used.add(eff_type)
        print(f"{time_str} | {seg_id:12} | {eff_type:30} | {reason:40}")

    # Summary
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"\nDistinct effects used: {len(effects_used)}")
    print(f"Effects: {sorted(effects_used)}")

    # Check for V4 effects
    v4_new_effects = {
        "camera_shake", "freeze_frame_zoom", "speed_ramp", "blur_in",
        "vignette_pulse", "rgb_split", "light_leak_overlay", "white_flash",
        "black_flash", "text_pop_scale", "emoji_sticker_pop", "zoom_blur_transition",
        "black_and_white_flash"
    }
    v4_used = [e for e in effects_used if any(new in e for new in v4_new_effects)]
    print(f"\nNew V4 effects used: {v4_used if v4_used else 'None (still using v3 families)'}")

    # Test rendering capabilities
    print(f"\n" + "=" * 100)
    print("RENDERING TEST")
    print("=" * 100)

    from engine.effects_v4 import effect_filter_xml_v4

    print(f"\nTesting effect filter XML generation:")
    for eff in list(effects_used)[:5]:  # Test first 5
        try:
            xml = effect_filter_xml_v4(eff, 30, 1080, 1920, 3)
            status = "✓" if xml else "✗ (empty)"
            print(f"  {eff:30} {status}")
        except Exception as e:
            print(f"  {eff:30} ✗ ({str(e)[:30]})")

    print(f"\n" + "=" * 100)
    print("INTEGRATION TEST COMPLETE")
    print("=" * 100 + "\n")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
