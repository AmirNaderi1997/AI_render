#!/usr/bin/env python3
"""Full pipeline test: ElevenLabs + correction + planner + render on MYVIDEO.mp4"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Ensure ELEVENLABS_API_KEY is available
if not os.getenv("ELEVENLABS_API_KEY"):
    print("ERROR: ELEVENLABS_API_KEY not set")
    sys.exit(1)

from brain.transcribe import transcribe, effective_transcript, file_hash
from brain.correct import auto_correct, load_glossary, expand_corrections_for_save
from brain.silence import detect_pauses
from brain.planner import generate_plan
from brain.transcribe import save_corrections
from engine.build_mlt import build
from engine.render import render as run_render


def main():
    video_path = Path("/Users/amirhossein/Documents/AI_render/raw/MYVIDEO.mp4")
    if not video_path.exists():
        print(f"ERROR: {video_path} not found")
        sys.exit(1)

    with tempfile.TemporaryDirectory(prefix="stage2_") as tmpdir:
        job_dir = Path(tmpdir)
        raw_dir = job_dir / "raw"
        raw_dir.mkdir()

        # Copy video to job dir
        import shutil
        shutil.copy(video_path, raw_dir / video_path.name)

        print("=" * 80)
        print("STAGE 2 FULL PIPELINE TEST: ElevenLabs + Correction + Plan + Render")
        print("=" * 80)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 1. TRANSCRIBE with ElevenLabs
        print("\n[1/4] TRANSCRIPTION with ElevenLabs…")
        start = time.time()
        digest = file_hash(raw_dir / video_path.name)
        transcript = transcribe(
            raw_dir / video_path.name,
            job_dir,
            language="fa",
            engine="elevenlabs",
        )
        t_asr = time.time() - start

        asr_cost_path = job_dir / "asr_cost.json"
        asr_info = {}
        if asr_cost_path.exists():
            asr_info = json.loads(asr_cost_path.read_text())

        print(f"  ✓ {len(transcript.get('words', []))} words transcribed in {t_asr:.1f}s")
        print(f"  ✓ Engine: {transcript.get('engine', 'unknown')}")
        print(f"  ✓ Duration: {transcript.get('duration', 0):.2f}s")
        if asr_info:
            print(f"  ✓ Cost: ${asr_info.get('cost_usd', 0):.4f} ({asr_info.get('audio_seconds', 0):.1f}s audio)")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 2. AUTO-CORRECT transcript
        print("\n[2/4] AUTO-CORRECTION with LLM…")
        start = time.time()

        import yaml
        from engine.schema import PROJECT_ROOT
        preset_path = PROJECT_ROOT / "presets" / "rafiei_reel.yaml"
        preset = yaml.safe_load(preset_path.read_text()) if preset_path.exists() else {}

        glossary = load_glossary()
        corrections, corr_usage = auto_correct(transcript, preset, glossary)
        t_corr = time.time() - start

        if not corrections:
            print("  ✓ No corrections needed")
            corrections_applied = []
        else:
            # Apply high-confidence corrections
            min_conf = float(preset.get("correction", {}).get("auto_apply_min_confidence", 0.85))
            auto_apply = [c for c in corrections if c["confidence"] >= min_conf]
            suggestions = [c for c in corrections if c["confidence"] < min_conf]

            print(f"  ✓ {len(corrections)} total corrections proposed")
            print(f"    - Auto-apply (conf >= {min_conf}): {len(auto_apply)}")
            print(f"    - Suggestions (conf < {min_conf}): {len(suggestions)}")

            if auto_apply:
                base_key = transcript.get("cache_key") or transcript.get("file_hash", "")
                save_items = expand_corrections_for_save(auto_apply, transcript.get("words", []))
                save_corrections(job_dir, base_key, save_items)
                transcript = effective_transcript(job_dir)
                corrections_applied = auto_apply
                print(f"  ✓ Applied {len(auto_apply)} corrections to transcript")

                # Report corrections
                for c in auto_apply[:5]:  # First 5
                    print(f"    - {c['old']!r} → {c['new']!r} ({c.get('reason', 'unknown')})")
                if len(auto_apply) > 5:
                    print(f"    ... and {len(auto_apply) - 5} more")

        print(f"  ✓ Correction time: {t_corr:.1f}s")
        print(f"  ✓ Correction model: {corr_usage.model or '(default)'}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 3. SILENCE DETECTION + PLANNING
        print("\n[3/4] PLANNING with LLM (includes off-camera talk removal)…")
        start = time.time()

        pauses = detect_pauses(raw_dir / video_path.name, transcript["words"], preset="rafiei_reel")

        source_rel = f"raw/{video_path.name}"
        plan_data, plan_usage = generate_plan(
            job_dir=job_dir,
            transcript=transcript,
            keep_ranges=pauses["keep"],
            remove_ranges=pauses["remove"],
            source_rel=source_rel,
            preset_name="rafiei_reel",
            instruction="",
        )
        t_plan = time.time() - start

        print(f"  ✓ Plan generated in {t_plan:.1f}s")
        print(f"  ✓ Segments: {len(plan_data.get('segments', []))}")
        print(f"  ✓ Captions: {len(plan_data.get('captions', []))}")
        print(f"  ✓ Plan model: {plan_usage.model}")

        # Report segments and kept/removed
        kept_segs = plan_data.get("segments", [])
        total_kept = sum(s.get("out", 0) - s.get("in", 0) for s in kept_segs)
        total_source = transcript.get("duration", 0)
        removed = total_source - total_kept

        print(f"\n  KEPT vs REMOVED:")
        print(f"    - Source duration: {total_source:.2f}s")
        print(f"    - Kept duration: {total_kept:.2f}s")
        print(f"    - Removed duration: {removed:.2f}s ({100*removed/total_source if total_source else 0:.1f}%)")

        # Sample of removed segments (via pauses/remove_ranges)
        if pauses["remove"]:
            print(f"\n  REMOVED RANGES (off-camera talk, pauses, false starts):")
            for start_t, end_t in pauses["remove"][:5]:
                dur = end_t - start_t
                # Find words in this range
                words_in_range = [w for w in transcript.get("words", [])
                                 if start_t <= w.get("start", 0) < end_t]
                text = " ".join(w["w"] for w in words_in_range)
                if text:
                    print(f"    [{start_t:.2f}–{end_t:.2f}] ({dur:.2f}s): {text[:60]}")
            if len(pauses["remove"]) > 5:
                print(f"    … and {len(pauses['remove']) - 5} more removed ranges")

        # Report captions with times
        print(f"\n  CAPTIONS IN ORDER:")
        captions = plan_data.get("captions", [])
        for i, cap in enumerate(captions[:10]):
            start_t = cap.get("start", 0)
            end_t = cap.get("end", 0)
            text = cap.get("text", "")
            style = cap.get("style", "normal")
            print(f"    [{start_t:.2f}–{end_t:.2f}] {style}: {text}")
        if len(captions) > 10:
            print(f"    … and {len(captions) - 10} more captions")

        # Save plan for render
        plan_path = job_dir / "plan.json"
        plan_path.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 4. RENDER
        print("\n[4/4] RENDERING video…")
        start = time.time()

        try:
            # Build MLT project
            build(plan_data, job_dir)
            project_path = job_dir / "project.mlt"
            print(f"  ✓ MLT project built: {project_path.name}")

            # Run render
            exports_dir = job_dir / "exports"
            exports_dir.mkdir(exist_ok=True)
            export_file = exports_dir / "v1.mp4"

            run_render(project_path, export_file, loudnorm=False)
            t_render = time.time() - start

            if export_file.exists():
                size_mb = export_file.stat().st_size / (1024 * 1024)
                print(f"  ✓ Rendered: {export_file.name} ({size_mb:.1f} MB) in {t_render:.1f}s")
            else:
                print(f"  ✗ Render failed — output file not created")
        except Exception as e:
            print(f"  ✗ Render error: {e}")
            t_render = 0

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # SUMMARY
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)

        total_cost = asr_info.get("cost_usd", 0) + (plan_usage.cost_estimate or 0)
        total_time = t_asr + t_corr + t_plan + t_render

        print(f"\n📊 METRICS:")
        print(f"  - Source duration: {total_source:.2f}s")
        print(f"  - Output duration: {total_kept:.2f}s")
        print(f"  - Segments kept: {len(kept_segs)}")
        print(f"  - Captions: {len(captions)}")
        print(f"  - Corrections applied: {len(corrections_applied)}")

        print(f"\n💰 COST:")
        print(f"  - ASR (ElevenLabs): ${asr_info.get('cost_usd', 0):.4f}")
        print(f"  - LLM (correction + planning): ${plan_usage.cost_estimate or 0:.4f}")
        print(f"  - Total: ${total_cost:.4f}")

        print(f"\n⏱️  PROCESSING TIME:")
        print(f"  - ASR: {t_asr:.1f}s")
        print(f"  - Correction: {t_corr:.1f}s")
        print(f"  - Planning: {t_plan:.1f}s")
        print(f"  - Rendering: {t_render:.1f}s")
        print(f"  - Total: {total_time:.1f}s")

        print(f"\n🎬 FRAME PATHS (5 sample frames from output):")
        # Save sample info: would render frames in real use
        for i, seg in enumerate(kept_segs[:5]):
            seg_in = seg.get("in", 0)
            seg_out = seg.get("out", 0)
            duration = seg_out - seg_in
            # Compute output time of segment start
            acc = 0
            for s in kept_segs[:i]:
                acc += s.get("out", 0) - s.get("in", 0)
            print(f"  - Segment {seg['id']}: source [{seg_in:.2f}–{seg_out:.2f}] → output [{acc:.2f}–{acc + duration:.2f}]")

        print("\n✅ PIPELINE COMPLETE")


if __name__ == "__main__":
    main()
