#!/usr/bin/env python3
"""Compare Whisper large-v3 vs ElevenLabs Scribe v2 on raw/MYVIDEO.mp4."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.transcribe import file_hash, transcribe

VIDEO = Path(__file__).resolve().parent.parent / "raw" / "MYVIDEO.mp4"
OUT_BASE = Path(__file__).resolve().parent.parent / "docs" / "asr_compare"


def run_engine(engine: str, model_size: str | None = None) -> dict:
    out_dir = OUT_BASE / engine
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    result = transcribe(
        VIDEO, out_dir,
        model_size=model_size,
        language="fa",
        engine=engine,
    )
    elapsed = time.monotonic() - t0

    cost = 0.0
    cost_path = out_dir / "asr_cost.json"
    if cost_path.exists():
        cost = json.loads(cost_path.read_text()).get("cost_usd", 0)

    return {
        "engine": engine,
        "model_size": model_size,
        "word_count": len(result.get("words", [])),
        "sentence_count": len(result.get("sentences", [])),
        "duration": result.get("duration", 0),
        "elapsed_sec": round(elapsed, 2),
        "cost_usd": cost,
        "sentences": result.get("sentences", [])[:5],
        "words": result.get("words", []),
    }


def main():
    if not VIDEO.exists():
        print(f"ERROR: {VIDEO} not found")
        sys.exit(1)

    print(f"Video: {VIDEO.name} ({VIDEO.stat().st_size / 1e6:.1f} MB)")
    print(f"File hash: {file_hash(VIDEO)}")
    print()

    # Run Whisper large-v3
    print("=" * 60)
    print("Running Whisper large-v3...")
    whisper_result = run_engine("whisper", model_size="large-v3")
    print(f"  Words: {whisper_result['word_count']}")
    print(f"  Sentences: {whisper_result['sentence_count']}")
    print(f"  Audio duration: {whisper_result['duration']:.1f}s")
    print(f"  Elapsed: {whisper_result['elapsed_sec']:.1f}s")
    print(f"  Cost: ${whisper_result['cost_usd']:.4f}")
    print()

    # Run ElevenLabs
    print("=" * 60)
    print("Running ElevenLabs Scribe v2...")
    elevenlabs_result = run_engine("elevenlabs")
    print(f"  Words: {elevenlabs_result['word_count']}")
    print(f"  Sentences: {elevenlabs_result['sentence_count']}")
    print(f"  Audio duration: {elevenlabs_result['duration']:.1f}s")
    print(f"  Elapsed: {elevenlabs_result['elapsed_sec']:.1f}s")
    print(f"  Cost: ${elevenlabs_result['cost_usd']:.4f}")
    print()

    # Side by side: first 5 sentences
    print("=" * 60)
    print("SIDE-BY-SIDE: First 5 sentences")
    print("=" * 60)
    w_sents = whisper_result["sentences"]
    e_sents = elevenlabs_result["sentences"]
    for i in range(min(5, max(len(w_sents), len(e_sents)))):
        print(f"\n--- Sentence {i+1} ---")
        if i < len(w_sents):
            print(f"  Whisper:     {w_sents[i]['text']}")
        if i < len(e_sents):
            print(f"  ElevenLabs:  {e_sents[i]['text']}")

    # Flagged words (low confidence)
    print()
    print("=" * 60)
    print("LOW-CONFIDENCE WORDS (prob < 0.5)")
    print("=" * 60)
    w_flagged = [w for w in whisper_result["words"] if w.get("prob", 1) < 0.5]
    e_flagged = [w for w in elevenlabs_result["words"] if w.get("prob", 1) < 0.5]
    print(f"  Whisper:     {len(w_flagged)} flagged words")
    print(f"  ElevenLabs:  {len(e_flagged)} flagged words")

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'':20s} {'Whisper large-v3':>20s} {'ElevenLabs Scribe v2':>22s}")
    print(f"{'Words':20s} {whisper_result['word_count']:>20d} {elevenlabs_result['word_count']:>22d}")
    print(f"{'Sentences':20s} {whisper_result['sentence_count']:>20d} {elevenlabs_result['sentence_count']:>22d}")
    print(f"{'Flagged words':20s} {len(w_flagged):>20d} {len(e_flagged):>22d}")
    print(f"{'Elapsed (sec)':20s} {whisper_result['elapsed_sec']:>20.1f} {elevenlabs_result['elapsed_sec']:>22.1f}")
    print(f"{'Cost ($)':20s} {whisper_result['cost_usd']:>20.4f} {elevenlabs_result['cost_usd']:>22.4f}")

    # Save full results
    report_path = OUT_BASE / "comparison.json"
    report_path.write_text(json.dumps({
        "whisper": {k: v for k, v in whisper_result.items() if k != "words"},
        "elevenlabs": {k: v for k, v in elevenlabs_result.items() if k != "words"},
    }, indent=2, ensure_ascii=False))
    print(f"\nFull results saved to {report_path}")


if __name__ == "__main__":
    main()
