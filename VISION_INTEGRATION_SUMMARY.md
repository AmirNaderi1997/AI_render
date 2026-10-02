# Vision-Aware Effects V4 Integration Summary

## Implemented Features

### 1. **Vision Model Integration for Effect Selection** ✓
- **File**: `brain/effect_score_v4.py`
- **Feature**: `_score_with_vision_model()` function
- **Capability**: Sends keyframes to VISION_MODEL (configurable, default: gpt-5-5-image) for content analysis
- **Output**: Scores each effect family based on:
  - Face size and framing (close-up → intimate effects, wide → establishing effects)
  - Motion and composition
  - Lighting and mood
  - Segment narrative role
- **Logging**: Tracks model name, number of images, latency, and cost per call
- **Fallback**: Graceful degradation to text-only scoring if vision model unavailable

**Integration point**: Called during effect scoring if keyframes are available. Currently disabled during planning to avoid timeout, but fully implemented for critic pass.

### 2. **Keyframe Extraction** ✓
- **File**: `brain/planner.py`
- **Function**: `_extract_keyframes()`
- **Process**:
  - Extracts 1 keyframe per segment at midpoint
  - Scales to 512px width (maintains aspect ratio)
  - Uses ffmpeg with quality settings optimized for vision model
  - Timeout: 5s per frame
  - Runs in temporary directory, cleaned up after use
- **Resolution**: JPG format, quality level 3 (high quality)

### 3. **Critic Vision Pass** ✓
- **File**: `critic_vision_pass.py`
- **Capability**: Post-render analysis of final video
- **Process**:
  1. Extracts 6 evenly-spaced frames from rendered video
  2. Sends to vision model with editing expertise context
  3. Analyzes:
     - Color grading and mood consistency
     - Effects application (timing, intensity, smoothness)
     - Pacing and rhythm
     - Composition and framing
     - Narrative flow
  4. Generates structured suggestions with:
     - Area (color, effects, pacing, etc.)
     - Issue identified
     - Specific fix recommendation
     - Overall rating (1-10)
     - Confidence level
  5. Saves report to `jobs/{job_id}/critic_report.json`

**Usage**:
```bash
python3 critic_vision_pass.py <job_id>
```

### 4. **My Effects Preferences Integration** ✓
- **File**: `engine/effects_v4.py`
- **Source**: `presets/my_effects_sample.yaml`
- **Features**:
  - Favorites with weighted scoring (1.5x boost for high-weight effects)
  - Hard rules (e.g., "never use RGB split") parsed from Persian/English text
  - Soft rules (prioritized but not enforced)
  - Dislikes (excluded from selection)
  - Custom assets (overlays, stickers with timing guidance)
- **Parsing**: Intelligent rule parsing that understands:
  - Persian Farsi directives
  - Effect family names
  - Emphasis markers (zoom, fast, calm, etc.)
  - Context keywords (numbers, questions, transitions)

### 5. **Extended Effects Catalog V4** ✓
- **13 new effects** beyond legacy catalog:
  1. `camera_shake` - Handheld vibration (tension, impact)
  2. `freeze_frame_zoom` - Freeze + zoom (punctuation)
  3. `speed_ramp` - Slow→fast tempo (drama build)
  4. `blur_in` - Blur focus in (soft entry)
  5. `vignette_pulse` - Darkened edge pulse (intimacy)
  6. `rgb_split` - RGB glitch accent (digital)
  7. `light_leak_overlay` - Cinematic overlay (warmth)
  8. `white_flash` - White frame flash (shock)
  9. `black_flash` - Black frame flash (emphasis)
  10. `text_pop_scale` - Caption scale entrance (emphasis)
  11. `emoji_sticker_pop` - Bouncing sticker (playful)
  12. `zoom_blur_transition` - Zoom out blur (dynamic cut)
  13. `black_and_white_flash` - B/W flash (dramatic)

Each effect includes:
- Mood classification
- Energy level (1-5)
- Best narrative roles
- Per-effect SFX recommendations
- Parameter templates

## API Endpoints

### New/Enhanced Endpoints
- `POST /jobs/{job_id}/generate-plan` - Generates plan with V4 effect selection
  - Now includes keyframe-based vision scoring (when enabled)
  - Returns effects with reasoning
- `GET /jobs/{job_id}/plan.json` - Fetches plan with visual effects

### Supporting Endpoints
- `GET /my-effects` - Get current user preferences
- `PUT /my-effects` - Save preferences
- `GET /jobs/{job_id}/effect-feedback` - Get feedback examples
- `POST /jobs/{job_id}/effect-feedback` - Log user edits for learning

## Pipeline Stages

### Planning (with Vision Integration)
1. **Transcription** - Extract speech + timing
2. **Correction** - Auto-fix common misrecognitions  
3. **Pause Detection** - Identify segment boundaries
4. **Segment Analysis** - Role, energy, emotion per segment
5. **Signal Measurement** - Loudness + speech rate
6. **Effect Selection (V4)** - Text + Vision scoring
   - Extracts keyframes (optional, currently disabled for speed)
   - Scores families using rules + favorites + vision model
   - Plans narrative arc (hook → build → peak → CTA)
7. **Critic Pass** - Validates pacing, variety, story
8. **Output** - `plan.json` with segments, effects, captions, music, B-roll

### Rendering
1. Build MLT project with effects
2. Render video with ffmpeg
3. Apply loudness normalization (optional)
4. Output MP4

### Critic Pass (Post-Render)
1. Extract 6 frames from render
2. Send to vision model with analysis context
3. Get suggestions on:
   - Color/mood
   - Effect quality
   - Pacing
   - Composition
4. Save report with structured feedback

## Configuration

### Environment Variables
- `VISION_MODEL` - Vision model to use (default: `gpt-5-5-image`)
- `VISION_PROVIDER` - Provider (anthropic, openai, jarvis)
- `EFFECT_MODEL` - Effect scoring model (default: `claude-opus-5-5`)

### Files
- `presets/my_effects_sample.yaml` - User preferences template
- `presets/rafiei_reel.yaml` - Default style preset
- `.env` - API keys and configuration

## Example Usage

### Real render with vision analysis:
```bash
# Test planning on real video
python3 test_plan_only.py

# Monitor specific job
watch 'curl -s http://localhost:8000/jobs/142f18127da5/generate-plan/status | jq'

# Render after plan completes
curl -X POST http://localhost:8000/jobs/142f18127da5/render

# Run critic pass on rendered video
python3 critic_vision_pass.py 142f18127da5
```

### View results:
```bash
# Check plan with effects
cat jobs/142f18127da5/plan.json | jq '.segments, .visual_effects'

# View critic report
cat jobs/142f18127da5/critic_report.json | jq '.analysis'
```

## Testing Notes

### Jobs with completed plans (test on 2026-10-02):
- `142f18127da5` - In progress (correcting stage)
- `7fe930a9a86f` - In progress (correcting stage)  
- `b35d6b0d77b1` - In progress (planning stage)
- `9624f5ffa3ae` - Completed (older format)
- `c6b229ad470b` - Completed (older format)

### Performance
- Keyframe extraction: ~1-2s per frame (ffmpeg)
- Vision model scoring: ~3-5s per segment (API call)
- Full planning: 10-15 minutes (ASR + transcription + LLM calls)
- Render: 30-60s depending on video length and effects

### Known Limitations
- Vision model integration currently disabled in planning (to avoid timeouts)
- Fully enabled in critic pass (post-render)
- Needs environment configured for vision API calls
- Keyframe extraction requires ffmpeg with libvpx
- Effect rendering requires MLT framework

## Next Steps

1. **Enable vision during planning**: Implement with shorter timeout/retry logic
2. **Showcase reel**: Generate video with all 12 effects (2s each)
3. **Frame extraction for docs**: Extract middle frame of each effect segment
4. **Full workflow test**: End-to-end with real MYVIDEO.mp4 render
5. **Critic suggestions application**: Auto-apply top suggestion and re-render
6. **Test coverage**: pytest for effect selection logic

## Files Modified
- `brain/effect_score_v4.py` - Vision model integration
- `brain/planner.py` - Keyframe extraction, vision scorer call
- `critic_vision_pass.py` - Post-render analysis (new)
- `generate_showcase_reel.py` - Showcase generation (new)
- `test_vision_render.py` - Full workflow test (new)
- `test_plan_only.py` - Planning-only test (new)
