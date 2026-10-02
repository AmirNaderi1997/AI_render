#!/usr/bin/env python3
"""Critic pass: Run vision model on 6 frames from rendered video, suggest improvements.

Usage:
    python critic_vision_pass.py <job_id>
"""
import sys
import json
import subprocess
import tempfile
from pathlib import Path
from brain.llm import chat_vision

def extract_frames(video_path: Path, num_frames: int = 6) -> list[Path]:
    """Extract evenly-spaced frames from video."""
    # Get duration
    r = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(video_path)
    ], capture_output=True, text=True, check=True)

    duration = float(json.loads(r.stdout)["format"]["duration"])

    # Extract frames
    tmpdir = Path(tempfile.mkdtemp(prefix="critic_frames_"))
    frames = []

    for i in range(num_frames):
        time = (duration / num_frames) * i
        frame_path = tmpdir / f"frame_{i:02d}.jpg"

        subprocess.run([
            "ffmpeg", "-y", "-ss", str(time), "-i", str(video_path),
            "-vf", "scale=512:-1",
            "-vframes", "1",
            "-q:v", "3",
            str(frame_path),
        ], capture_output=True, check=True)

        frames.append(frame_path)

    return frames

def critic_analysis(frames: list[Path], duration: float) -> dict:
    """Run vision model analysis on frames."""
    system_prompt = """You are a professional video editor and color grading expert.

Analyze the provided 6 frames from a rendered video. Suggest improvements:
1. Color grading and mood consistency
2. Effects application (timing, intensity, smoothness)
3. Pacing and rhythm
4. Composition and framing
5. Overall narrative flow

Format your response as JSON with:
- suggestions: list of {area, issue, fix} objects
- overall_rating: 1-10
- confidence: "high" | "medium" | "low"
"""

    user_prompt = f"""These 6 frames are from a {duration:.1f}s edited video.

Analyze them and suggest specific improvements. Focus on:
- Does each effect work well with the content?
- Is the pacing natural?
- Any jarring transitions or timing issues?
- Any color/brightness inconsistencies?

Be constructive and specific."""

    try:
        text, usage = chat_vision(
            system=system_prompt,
            user=user_prompt,
            images=frames,
            return_json=False,
            model="claude-opus-5-5",  # Use better model for critique
            max_tokens=2048,
        )

        # Extract JSON from response (handle markdown code blocks)
        text = str(text)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        # Try to parse JSON
        try:
            response = json.loads(text)
        except json.JSONDecodeError:
            # Find first { and last } and try again
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                response = json.loads(text[start:end])
            else:
                print(f"\n✗ Could not extract JSON from response")
                return None

        print(f"\n✓ Vision analysis complete")
        print(f"  Model: {usage.model}")
        print(f"  Tokens: {usage.input_tokens} in / {usage.output_tokens} out")
        print(f"  Cost: ${usage.cost_estimate:.4f}")

        return response

    except Exception as e:
        print(f"\n✗ Vision analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python critic_vision_pass.py <job_id>")
        sys.exit(1)

    job_id = sys.argv[1]
    project_root = Path(__file__).parent

    # Find rendered video
    exports_dir = project_root / "jobs" / job_id / "exports"
    if not exports_dir.exists():
        print(f"ERROR: No exports for job {job_id}")
        sys.exit(1)

    videos = list(exports_dir.glob("*.mp4"))
    if not videos:
        print(f"ERROR: No MP4 files in {exports_dir}")
        sys.exit(1)

    video_path = videos[0]
    print(f"Analyzing {video_path.name}...")

    # Get duration
    r = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(video_path)
    ], capture_output=True, text=True, check=True)
    duration = float(json.loads(r.stdout)["format"]["duration"])

    # Extract frames
    print(f"Extracting 6 frames from {duration:.1f}s video...")
    frames = extract_frames(video_path, num_frames=6)
    print(f"Extracted: {[f.name for f in frames]}")

    # Run vision analysis
    print(f"\nRunning vision analysis...")
    analysis = critic_analysis(frames, duration)

    if analysis:
        print(f"\n=== CRITIC REPORT ===")
        print(f"Overall Rating: {analysis.get('overall_rating', '?')}/10")
        print(f"Confidence: {analysis.get('confidence', '?')}")

        suggestions = analysis.get("suggestions", [])
        if suggestions:
            print(f"\nSuggestions ({len(suggestions)}):")
            for i, sugg in enumerate(suggestions, 1):
                print(f"  {i}. [{sugg.get('area', '?')}] {sugg.get('issue', '?')}")
                print(f"     → Fix: {sugg.get('fix', '?')}")

        # Save report
        report_path = project_root / "jobs" / job_id / "critic_report.json"
        report_path.write_text(json.dumps({
            "video": str(video_path),
            "duration": duration,
            "analysis": analysis,
            "frames": [str(f) for f in frames],
        }, indent=2))

        print(f"\nReport saved to: {report_path.relative_to(project_root)}")

if __name__ == "__main__":
    main()
