#!/usr/bin/env python3
"""Quick test of just the planning stage."""
import json
import time
import requests
from pathlib import Path

API_BASE = "http://localhost:8000"
PROJECT_ROOT = Path(__file__).parent

def main():
    print("Testing plan generation...\n")

    # Create job
    video_path = PROJECT_ROOT / "raw" / "MYVIDEO.mp4"
    print(f"Creating job with {video_path.name}...")

    with open(video_path, "rb") as f:
        r = requests.post(f"{API_BASE}/jobs", files={"video": ("MYVIDEO.mp4", f)})

    if r.status_code != 200:
        print(f"ERROR: {r.text}")
        return

    job_id = r.json()["job"]["id"]
    print(f"Job {job_id} created\n")

    # Start plan generation
    print("Starting plan generation...")
    r = requests.post(
        f"{API_BASE}/jobs/{job_id}/generate-plan",
        json={"style": "rafiei_reel", "language": "fa"}
    )

    if r.status_code != 200:
        print(f"ERROR: {r.text}")
        return

    # Poll status
    for i in range(300):
        r = requests.get(f"{API_BASE}/jobs/{job_id}/generate-plan/status")
        data = r.json()
        status = data.get("status")
        stage = data.get("stage", "?")

        if status == "done":
            print(f"✓ Plan generation complete in {i * 5}s")
            print(f"  Model: {data.get('model')}")
            print(f"  Cost: ${data.get('cost_usd', 0):.4f}")
            break
        elif status == "error":
            print(f"✗ Error at stage {stage}: {data.get('message')}")
            return
        else:
            if i % 2 == 0:  # Print every 10s
                print(f"  [{stage}] {status}")

        time.sleep(5)

    # Get plan
    r = requests.get(f"{API_BASE}/jobs/{job_id}/plan.json")
    if r.status_code == 200:
        plan = r.json()
        segs = plan.get("segments", [])
        effs = plan.get("visual_effects", [])
        print(f"\nPlan summary:")
        print(f"  Segments: {len(segs)}")
        print(f"  Effects: {len(effs)}")

        # Show first 3 segments
        for seg, eff in zip(segs[:3], effs[:3]):
            print(f"\n  Segment {seg['id']}: {seg['in']:.1f}s - {seg['out']:.1f}s")
            print(f"    Effect: {eff['type']}")

if __name__ == "__main__":
    main()
