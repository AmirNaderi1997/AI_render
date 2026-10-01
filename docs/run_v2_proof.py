"""Real-run V2 proof script.

Runs the smarter brain V2 pipeline on job b5c8530cb28f and on raw/MYVIDEO.mp4
and writes the comparison results to docs/proof_v2.md.

Usage:
    cd ~/Documents/AI_render
    python docs/run_v2_proof.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
log = logging.getLogger("v2_proof")

# Load environment
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)


def _build_effect_timeline(effects_v2, effect_analysis, words, plan_data):
    seg_text_map: dict = {}
    for seg in plan_data.get("segments", []):
        seg_words = [w["w"] for w in words
                     if seg.get("in", 0) - 0.05 <= w.get("start", 0) <= seg.get("out", 0) + 0.05]
        seg_text_map[seg["id"]] = " ".join(seg_words)[:80]
    return [
        {
            "seg": e["segment_id"],
            "type": e["type"],
            "family": ea.get("family", ""),
            "reason": ea.get("reason", ""),
            "intensity": ea.get("intensity", ""),
            "text": seg_text_map.get(e["segment_id"], ""),
        }
        for e, ea in zip(effects_v2, effect_analysis)
    ]


def run_on_job(job_dir: Path, video_path: Path, label: str) -> dict:
    """Run V2 correction + plan generation on an existing transcript + video."""
    log.info("=== %s: %s ===", label, job_dir)
    t0 = time.time()

    from brain.transcribe import effective_transcript, transcribe
    from brain.correct import auto_correct, load_glossary, detect_suspect_words
    from brain.silence import detect_pauses
    from brain.planner import generate_plan

    # 1. Load or generate transcript
    transcript_path = job_dir / "transcript.json"
    if not transcript_path.exists():
        log.info("No transcript found — running Whisper on %s", video_path)
        from brain.glossary import build_initial_prompt
        glossary = load_glossary()
        hint = build_initial_prompt(glossary, "fa")
        transcribe(video_path, job_dir, language="fa", initial_prompt=hint)
    transcript = effective_transcript(job_dir)
    words = transcript["words"]
    log.info("Transcript: %d words, lang=%s, model=%s",
             len(words), transcript.get("language"), transcript.get("model_size"))

    # 2. Run V2 auto-correct
    glossary = load_glossary()
    preset_path = ROOT / "presets" / "rafiei_reel.yaml"
    import yaml
    preset = yaml.safe_load(preset_path.read_text())

    flagged_before = detect_suspect_words(words, threshold=0.60, glossary=glossary)
    decode_disagree = [w for w in words if "alt_w" in w]

    corrections, corr_usage = auto_correct(transcript, preset, glossary)
    auto_applied = [c for c in corrections if c["confidence"] >= 0.85]
    suggestions = [c for c in corrections if c["confidence"] < 0.85]

    log.info("Corrections: %d total (%d auto, %d suggestions)",
             len(corrections), len(auto_applied), len(suggestions))

    # 3. Detect pauses
    pauses = detect_pauses(video_path, transcript["words"], preset="rafiei_reel")

    # 4. Generate plan (V2 with segment analysis + scored effects)
    source_rel = f"raw/{video_path.name}"
    plan_data, plan_usage = generate_plan(
        job_dir=job_dir,
        transcript=transcript,
        keep_ranges=pauses["keep"],
        remove_ranges=pauses["remove"],
        source_rel=source_rel,
        preset_name="rafiei_reel",
        on_progress=lambda msg: log.info("  plan: %s", msg),
    )

    elapsed = time.time() - t0

    # Collect effect analysis
    effects_v2 = plan_data.get("visual_effects", [])
    effect_analysis = plan_data.get("effect_analysis", [])
    families_used = list({e.get("_family", ea.get("family", ""))
                          for e, ea in zip(effects_v2, effect_analysis)
                          if ea.get("family")})
    # Count distinct effect types
    distinct_types = list({e["type"] for e in effects_v2})
    lights_used = list({e["type"].split("__")[1] for e in effects_v2 if "__" in e["type"]
                        and e["type"].split("__")[1] != "neutral"})

    total_usage_usd = (
        (corr_usage.input_tokens + plan_usage.input_tokens) * 0.000003 +
        (corr_usage.output_tokens + plan_usage.output_tokens) * 0.000015
    )

    return {
        "label": label,
        "words": len(words),
        "flagged_before_llm": len(flagged_before),
        "decode_disagree": len(decode_disagree),
        "corrections_proposed": len(corrections),
        "auto_applied": auto_applied,
        "suggestions": suggestions,
        "segments": len(plan_data.get("segments", [])),
        "captions": len(plan_data.get("captions", [])),
        "distinct_effect_types": len(distinct_types),
        "distinct_families": len(families_used),
        "families_used": families_used,
        "lights_used": lights_used,
        "effect_timeline": _build_effect_timeline(effects_v2, effect_analysis, words, plan_data),
        "llm_cost_usd": round(total_usage_usd, 4),
        "correction_tokens_in": corr_usage.input_tokens,
        "correction_tokens_out": corr_usage.output_tokens,
        "plan_tokens_in": plan_usage.input_tokens,
        "plan_tokens_out": plan_usage.output_tokens,
        "elapsed_sec": round(elapsed, 1),
        "plan_data": plan_data,
    }


def write_report(results: list[dict], out_path: Path) -> None:
    md = ["# V2 Real-Run Proof\n\nDate: 2026-10-01. Pipeline: smarter brain V2 (commit after 3bcada6).\n"]

    for r in results:
        md.append(f"\n## {r['label']}\n")
        md.append(f"- Words: {r['words']} | Pre-flagged: {r['flagged_before_llm']} | "
                  f"Decode disagree: {r['decode_disagree']}\n")
        md.append(f"- Corrections proposed: {r['corrections_proposed']} "
                  f"({len(r['auto_applied'])} auto, {len(r['suggestions'])} suggestions)\n")
        md.append(f"- Segments: {r['segments']} | Captions: {r['captions']}\n")
        md.append(f"- Distinct effect types: {r['distinct_effect_types']} | "
                  f"Distinct families: {r['distinct_families']}\n")
        md.append(f"- Families used: {', '.join(r['families_used']) or 'none'}\n")
        md.append(f"- Non-neutral lights used: {', '.join(r['lights_used']) or 'none'}\n")
        md.append(f"- LLM cost: ${r['llm_cost_usd']:.4f} "
                  f"({r['correction_tokens_in']+r['plan_tokens_in']} in / "
                  f"{r['correction_tokens_out']+r['plan_tokens_out']} out tokens)\n")
        md.append(f"- Elapsed: {r['elapsed_sec']}s\n")

        md.append("\n### Auto-applied corrections (10 shown)\n")
        md.append("| idx | old | new | conf | reason |\n|-----|-----|-----|------|--------|\n")
        for c in r["auto_applied"][:10]:
            md.append(f"| {c['index']} | {c['old']} | {c['new']} | {c['confidence']:.2f} | {c['reason'][:60]} |\n")

        md.append("\n### Suggestions\n")
        md.append("| idx | old | new | conf |\n|-----|-----|-----|------|\n")
        for c in r["suggestions"][:10]:
            md.append(f"| {c['index']} | {c['old']} | {c['new']} | {c['confidence']:.2f} |\n")

        md.append("\n### Effect timeline\n")
        md.append("| seg | type | family | intensity | reason |\n|-----|------|--------|-----------|--------|\n")
        for e in r["effect_timeline"]:
            md.append(f"| {e['seg']} | {e['type']} | {e['family']} | {e['intensity']} | {str(e['reason'])[:60]} |\n")

    # Before/after comparison table for job b5c8530cb28f
    md.append("\n## Before/After comparison (job b5c8530cb28f)\n\n")
    md.append("| metric | baseline (V1) | V2 result | target |\n")
    md.append("|--------|--------------|-----------|--------|\n")

    v2 = next((r for r in results if "b5c8530" in r["label"]), None)
    if v2:
        md.append(f"| Distinct effect types | 3 | {v2['distinct_effect_types']} | ≥ 6 |\n")
        md.append(f"| Distinct families | 3 | {v2['distinct_families']} | ≥ 6 |\n")
        md.append(f"| Non-neutral lights | 0 | {len(v2['lights_used'])} | ≥ 3 |\n")
        md.append(f"| Corrections proposed | 8 (5 auto+3 sugg) | {v2['corrections_proposed']} | ≥ 8 |\n")
        md.append(f"| LLM cost | $0.060 | ${v2['llm_cost_usd']:.4f} | ≤ $0.12 |\n")

    out_path.write_text("".join(md), encoding="utf-8")
    log.info("Report written to %s", out_path)


if __name__ == "__main__":
    results = []

    # Job b5c8530cb28f (Persian, use saved transcript)
    job_dir = ROOT / "jobs" / "b5c8530cb28f"
    video = job_dir / "raw" / "MYVIDEO.mp4"
    if video.exists():
        try:
            r = run_on_job(job_dir, video, "b5c8530cb28f (Persian reel)")
            results.append(r)
            # Save new plan
            new_plan_path = job_dir / "plan_v2.json"
            new_plan_path.write_text(json.dumps(r["plan_data"], indent=2, ensure_ascii=False))
            log.info("V2 plan saved to %s", new_plan_path)
        except Exception as exc:
            log.error("Failed on b5c8530cb28f: %s", exc)
            import traceback; traceback.print_exc()
    else:
        log.warning("Video not found: %s", video)

    # Persian video in raw/
    raw_video = ROOT / "raw" / "MYVIDEO.mp4"
    if raw_video.exists() and str(raw_video) != str(video):
        # Create a temp job dir for this video
        import tempfile, shutil
        tmp_job = ROOT / "jobs" / "raw_myvideo_v2"
        tmp_job.mkdir(exist_ok=True)
        (tmp_job / "raw").mkdir(exist_ok=True)
        (tmp_job / "exports").mkdir(exist_ok=True)
        dst = tmp_job / "raw" / "MYVIDEO.mp4"
        if not dst.exists():
            shutil.copy(raw_video, dst)
        try:
            r2 = run_on_job(tmp_job, dst, "raw/MYVIDEO.mp4 (Persian)")
            results.append(r2)
        except Exception as exc:
            log.error("Failed on raw/MYVIDEO: %s", exc)
            import traceback; traceback.print_exc()

    if results:
        write_report(results, ROOT / "docs" / "proof_v2.md")
        print("\n=== SUMMARY ===")
        for r in results:
            print(f"\n{r['label']}:")
            print(f"  Distinct effect types: {r['distinct_effect_types']} (baseline: 3)")
            print(f"  Distinct families: {r['distinct_families']} (baseline: 3)")
            print(f"  Non-neutral lights: {len(r['lights_used'])} (baseline: 0)")
            print(f"  Corrections proposed: {r['corrections_proposed']} (baseline: 8)")
            print(f"  LLM cost: ${r['llm_cost_usd']:.4f} (baseline: $0.060)")
    else:
        print("No results — check logs for errors")
