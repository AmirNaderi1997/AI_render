#!/usr/bin/env python3
"""Test vision-aware effect selection and real render through the app.

Usage:
    python test_vision_render.py
"""
import json
import time
import requests
from pathlib import Path
import subprocess

API_BASE = "http://localhost:8000"
PROJECT_ROOT = Path(__file__).parent

def wait_for_job_status(job_id: str, phase: str, timeout: int = 300):
    """Poll until a job phase is complete."""
    t0 = time.time()
    endpoint = f"{API_BASE}/jobs/{job_id}/generate-plan/status" if phase == "generate" else f"{API_BASE}/jobs/{job_id}/render/status"

    while time.time() - t0 < timeout:
        try:
            r = requests.get(endpoint)
            data = r.json()
            status = data.get("status")

            if phase == "generate":
                print(f"[{phase}] status={status}, stage={data.get('stage', '?')}, model={data.get('model', '?')}")
            else:
                print(f"[{phase}] status={status}, progress={data.get('progress', '?')}%")

            if status == "done":
                return data
            elif status == "failed":
                print(f"ERROR: {data.get('message', 'unknown error')}")
                raise RuntimeError(f"Job {job_id} {phase} failed")
        except Exception as e:
            print(f"Error polling: {e}")

        time.sleep(5)

    raise TimeoutError(f"Job {job_id} {phase} timed out after {timeout}s")

def main():
    print("=== Test: Vision-aware effect selection + real render ===\n")

    # Step 1: Create job with video
    print("1. Creating job...")
    video_path = PROJECT_ROOT / "raw" / "MYVIDEO.mp4"
    my_effects_path = PROJECT_ROOT / "presets" / "my_effects_sample.yaml"

    if not video_path.exists():
        print(f"ERROR: {video_path} not found")
        return

    with open(video_path, "rb") as f:
        files = {"video": ("MYVIDEO.mp4", f)}
        r = requests.post(f"{API_BASE}/jobs", files=files)

    if r.status_code != 200:
        print(f"ERROR: {r.text}")
        return

    result = r.json()
    job_id = result["job"]["id"]
    print(f"   Job created: {job_id}\n")

    # Step 2: Generate plan with vision-aware effect selection
    print("2. Generating plan (with vision model for effect selection)...")
    r = requests.post(
        f"{API_BASE}/jobs/{job_id}/generate-plan",
        json={
            "style": "rafiei_reel",
            "instruction": "",
            "language": "fa",
        }
    )
    if r.status_code != 200:
        print(f"ERROR: {r.text}")
        return

    # Wait for generation to complete
    result = wait_for_job_status(job_id, "generate", timeout=600)
    print(f"   Generation complete!")
    print(f"   Model: {result.get('model')}")
    print(f"   Cost: ${result.get('cost_usd', 0):.4f}")
    print(f"   Tokens: {result.get('input_tokens')} in / {result.get('output_tokens')} out\n")

    # Step 3: Get the plan and show vision analysis
    print("3. Fetching plan with vision analysis...")
    r = requests.get(f"{API_BASE}/jobs/{job_id}/plan.json")
    if r.status_code != 200:
        print(f"ERROR: Could not fetch plan")
        return

    plan = r.json()
    segments = plan.get("segments", [])
    effects = plan.get("visual_effects", [])

    print(f"   Plan has {len(segments)} segments, {len(effects)} effects")
    print(f"   Showing first 3 segments with vision analysis:")

    for i, (seg, eff) in enumerate(zip(segments[:3], effects[:3])):
        print(f"\n   Segment {seg['id']} ({seg['in']:.1f}s - {seg['out']:.1f}s):")
        print(f"     Effect: {eff['type']}")
        print(f"     Reason: {eff.get('_reason', 'N/A')[:100]}")

    # Step 4: Render the video
    print(f"\n4. Rendering video...")
    r = requests.post(f"{API_BASE}/jobs/{job_id}/render")
    if r.status_code != 200:
        print(f"ERROR: {r.text}")
        return

    # Wait for render to complete
    result = wait_for_job_status(job_id, "render", timeout=1200)
    print(f"   Render complete!")

    # Step 5: Get job info and show results
    print(f"\n5. Job summary:")
    r = requests.get(f"{API_BASE}/jobs/{job_id}")
    if r.status_code == 200:
        job = r.json()
        print(f"   Job ID: {job_id}")
        print(f"   Status: {job.get('status')}")

        # List exports
        exports_dir = PROJECT_ROOT / "jobs" / job_id / "exports"
        if exports_dir.exists():
            exports = list(exports_dir.glob("*.mp4"))
            if exports:
                export_path = exports[0]
                print(f"   Final MP4: {export_path.relative_to(PROJECT_ROOT)}")

                # Get duration using ffprobe
                try:
                    r = subprocess.run([
                        "ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(export_path)
                    ], capture_output=True, text=True, check=True)
                    duration = json.loads(r.stdout)["format"]["duration"]
                    print(f"   Duration: {duration:.1f}s")
                except:
                    pass

    print(f"\nDone! Job {job_id}")

if __name__ == "__main__":
    main()
