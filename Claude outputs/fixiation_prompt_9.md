# Fixiation Prompt 9: Core AI Brain, Render Engine, Job Pipeline, and Web UI

Read every file listed below, then **fix** anything broken and **verify** every claim. Run all tests to confirm green before and after any changes.

---

## Part A — AI Brain: Transcription Pipeline

### Files to read

- `brain/transcribe.py` — main transcription entry point (Whisper + ElevenLabs routing)
- `brain/transcribe_elevenlabs.py` — ElevenLabs Scribe v2 engine
- `brain/correct.py` — LLM-based auto-correction with similarity guardrails
- `brain/glossary.py` — glossary learning (wrong→right persistence)
- `brain/silence.py` — silence/pause detection (ffmpeg + word gaps)
- `brain/signals.py` — per-segment audio signal measurement (LUFS + speech rate)

### Items to verify/fix

1. **Whisper↔ElevenLabs engine selection** — `transcribe.py:choose_engine()` selects whisper vs elevenlabs based on language and whether `ELEVENLABS_API_KEY` is set. Verify: (a) for Persian (`fa`) with ELEVENLABS_API_KEY set, `transcribe()` tries ElevenLabs first and falls back to Whisper on failure, (b) for English or missing API key, it goes straight to Whisper, (c) the `asr_engine` parameter from the UI (`"auto"`, `"elevenlabs"`, `"whisper"`) is respected — if the user picks `"whisper"`, ElevenLabs is never called even when the key is set, (d) the fallback path logs a warning when ElevenLabs fails and doesn't swallow the original error context.

2. **ElevenLabs Scribe retry and fallback chain** — `transcribe_elevenlabs.py` has a 3-tier retry: scribe_v2 → retry scribe_v2 → scribe_v1. Verify: (a) the first retry genuinely re-seeks the file handle (`f.seek(0)`) before the second attempt, (b) the v1 fallback also seeks to 0, (c) the `RuntimeError` raised on total failure includes the actual API error message (not just "ElevenLabs API failed"), (d) the cost calculation correctly applies the 1.2× multiplier for keyterms (`cost = round(cost * 1.2, 6)` only when keyterms is truthy), (e) the transcript cache uses a hash that includes `keyterms` so re-running with different keyterms doesn't serve a stale cache hit.

3. **Persian script normalization consistency** — Both `transcribe.py:_normalize_persian()` and `transcribe_elevenlabs.py:_normalize_persian()` convert Arabic ي→ی and ك→ک. Verify: (a) both functions handle the same set of character mappings (the elevenlabs version also maps `ى` (alef maqsura) to `ی` — does the whisper version?), (b) `correct.py` uses `normalize_persian()` from its own import — confirm this is the same function or at least performs the same mappings, (c) no code path produces captions with mixed Arabic/Persian characters that would render inconsistently in the ASS/SRT output.

4. **Auto-correction similarity guardrail** — `correct.py:is_acceptable_replacement()` uses Jaccard bigram similarity with threshold 0.25 (configurable via preset `correction.similarity_threshold`). Verify: (a) when similarity is below threshold AND it's not a glossary fix, the confidence is capped at 0.5 (not rejected entirely), (b) the `_CHUNK_SIZE = 200` chunking in `_auto_correct_chunked()` correctly remaps chunk-local indices back to global indices (`item["index"] = int(item["index"]) + chunk_start`), (c) chunk boundaries don't split a sentence — check whether `_auto_correct_chunked` sends overlapping context or just hard-splits at word 200/400/etc., (d) the final validation in `_validate_corrections()` deduplicates by `seen` set so the same word index can't get two different corrections.

5. **Merge/split correction expansion** — `correct.py:_apply_merge_split()` handles `"split"` (one word → two) and `"merge"` (two words → one). Verify: (a) for a split, the time range is divided proportionally by character count — does it handle the case where `total_chars == 0` (returns None)? (b) for a merge, if `idx + 1 >= len(words)` it falls back to a simple replace — verify the fallback item has the correct format for `save_corrections()`, (c) `expand_corrections_for_save()` deduplicates by `seen` set — if a merge writes both `idx` and `idx+1`, and a separate correction also targets `idx+1`, the first one wins. Is this the right behavior?

6. **Glossary persistence atomicity** — `glossary.py:save_correction_to_glossary()` uses a write-to-tmp + rename pattern for atomicity. Verify: (a) `tmp.replace(path)` is atomic on the same filesystem (it should be since they're in the same directory), (b) the function adds the correct form to `vocabulary` list in addition to the `corrections` dict, (c) duplicate vocabulary entries are avoided (`if correct_norm not in vocab`), (d) `build_initial_prompt()` limits to 20 terms and 100 chars — verify the output stays under Whisper's initial_prompt length limits, (e) the glossary file uses `sort_keys=False` in yaml.dump so the order is stable across writes.

7. **Silence detection merge logic** — `silence.py:detect_pauses()` merges ffmpeg silencedetect ranges with Whisper word gap ranges. Verify: (a) the padding parameter is applied symmetrically (both sides of silence ranges are trimmed), (b) the returned `keep_ranges` and `remove_ranges` are non-overlapping and cover the full duration, (c) very short keep ranges (< some threshold) are merged into adjacent silence rather than creating micro-segments, (d) the function handles edge cases: no silence detected (entire file is speech), entire file is silence, or silence at the very start/end of the file.

8. **Signal measurement robustness** — `signals.py:measure_segment_signals()` measures LUFS loudness and speech rate per segment. Verify: (a) `_ffmpeg_loudness()` uses `ebur128` filter — confirm it correctly parses the ffmpeg stderr output for "I:" (integrated loudness), (b) if ffmpeg fails for a segment (e.g., segment too short for LUFS measurement — minimum is 400ms), the function returns a sensible default rather than crashing, (c) `_speech_rate()` divides word count by duration — does it guard against zero-duration segments?, (d) the signals are used by `planner.py` for effect selection — verify the signal dict keys match what `segment_analysis.py` expects.

---

## Part B — AI Brain: Edit Plan Generation

### Files to read

- `brain/planner.py` — LLM-based edit plan generator (system/user prompt builders, generate_plan, transitions, effects, cover/poster)
- `brain/segment_analysis.py` — segment role/energy analysis
- `brain/effect_score.py` — legacy effect scoring
- `brain/effect_score_v4.py` — V4 vision-aware effect scoring

### Items to verify/fix

9. **generate_plan retry loop** — `planner.py:generate_plan()` retries up to `max_retries` (default 3) on validation failure. Verify: (a) on retry, the previous validation errors are appended to the user prompt so the LLM can fix them, (b) the `total_usage` accumulates tokens across all attempts (not just the last one), (c) if all retries fail, the `ValueError` includes all the last errors (not just "Failed to generate"), (d) the `on_progress` callback is called with the attempt number so the UI can show "planning (attempt 2/3)".

10. **Segment clamping and output event trimming** — `_clamp_segments()` clamps segment.out to source duration, and `_clamp_output_events()` trims captions/broll/sfx to the output timeline. Verify: (a) `_clamp_segments` uses `probe_duration()` which calls ffprobe — if the source file doesn't exist, it returns early without error (correct), (b) `_clamp_output_events` calculates output duration by summing segment frames and subtracting transition overlap frames — verify the frame→seconds conversion uses the plan's FPS (not hardcoded 30), (c) captions with `start >= duration` are dropped entirely, but captions with `start < duration < end` have their end clamped — verify no zero-duration captions slip through, (d) music duck ranges are also clamped — verify the clamped duck list is written back to `plan_data["music"]["duck"]`.

11. **Transition suggestion engine** — `_suggest_transitions()` creates typed boundary transitions based on segment energy, user style preference, and locked manual choices. Verify: (a) locked transitions (from the UI) are always preserved with `source: "manual"` and `locked: True`, (b) the `TRANSITION_FORMAT_CAPS` dict limits frame counts per format (post: 8, story: 10, reel: 12) — verify these caps are applied to ALL transition sources (model, planner, and user style), (c) when `transition_style == "none"`, all transitions are hard cuts regardless of model suggestions, (d) the `max_overlap` calculation (`min(30, min(segment_frames) // 3)`) prevents transitions from consuming more than 1/3 of the shorter adjacent segment — verify this is correct for very short segments (< 6 frames).

12. **Transition overlap retiming** — `_retime_for_transition_overlaps()` maps concatenated output times onto the overlap timeline. Verify: (a) the `convert()` function correctly maps a time from legacy (no-overlap) timeline to the overlapping timeline, (b) it handles the boundary case where `value` falls exactly on a segment boundary (the loop breaks at `boundary - 1e-9`), (c) caption start/end, broll at/duration, sfx at, and music duck start/end are ALL retimed, (d) after retiming, no event has negative start times — the `max(0.0, ...)` clamp handles this.

13. **Visual effect pipeline** — The V2 effect pipeline: segment analysis → V4 scorer → critic pass → dislike enforcement → selected effect override. Verify: (a) `_apply_scored_effects()` extracts keyframes only for 3 segments (first, middle, last) — is this sufficient for long videos with many segments?, (b) the critic pass is skipped when `selection_locked` (My Effects explicit choice) or `no_zoom` rule is active — verify `no_zoom` detection checks both Persian "زوم نکن" and English "no zoom", (c) `_enforce_effect_dislikes()` replaces excluded effects with "steady__neutral" (or "slow_push__neutral" if steady is also excluded) — verify the fallback chain, (d) `_enforce_selected_effect()` overrides ALL segment effects and also neutralizes legacy zoom fields — verify `zoom: {"from": 1.0, "to": 1.0}` is set on every segment.

14. **Opening cover and poster selection** — `_apply_opening_cover()` picks the highest-scoring caption as the opening title; `_apply_poster()` picks the best hook caption for the poster image. Verify: (a) both functions score captions using segment shareability, role bonuses, and hook word detection — verify the Persian hook words list ("لازم نیست", "نمیخواد", etc.) is comprehensive, (b) the cover text is always an exact transcript caption (never LLM-generated), (c) the poster defaults to the cover caption unless another caption beats it by ≥10 points — verify this margin prevents unnecessary poster≠cover divergence, (d) if `preset.rafiei_style.opening_title` is False, cover is removed entirely — verify `plan_data.pop("cover", None)` doesn't crash when cover doesn't exist.

15. **Caption review warnings** — `_caption_review()` flags captions whose text doesn't match ASR words well (similarity < 0.68) or contains low-confidence words. Verify: (a) the `source_to_output_time` conversion is used correctly to map word timestamps to output timeline, (b) the similarity threshold 0.68 uses `SequenceMatcher` on normalized text — is this appropriate for Persian text where word order may differ from ASR?, (c) low-confidence words (prob < 0.6) that have been `reviewed` are NOT flagged — verify the `not word.get("reviewed")` check, (d) the warnings include `source_text` for UI display so the user can compare ASR vs caption text.

---

## Part C — Core Render Engine

### Files to read

- `engine/build_mlt.py` — MLT XML builder (segments, transitions, B-roll, captions, effects)
- `engine/render.py` — melt runner, loudnorm, poster export
- `engine/captions.py` — ASS + SRT caption generation with Persian font handling
- `engine/probe.py` — ffprobe wrappers (duration, dimensions, streams)
- `engine/effects_v4.py` — V4 effect catalog with MLT filter generation

### Items to verify/fix

16. **MLT two-track transition graph** — When the plan has boundary transitions, `build_mlt.py:build()` splits segments across two playlists (`v1a`, `v1b`) in alternating fashion and uses a tractor with `qtblend` transitions. Verify: (a) odd-indexed segments go to one lane, even to the other — the `index % 2` assignment is consistent between the playlist fill loop and the transition `a_track/b_track` assignment, (b) the audio mix transition for each boundary uses matching track indices, (c) blank lengths are inserted correctly when a lane has gaps (e.g., segments 0, 2, 4 on lane A with gaps where segments 1, 3 would be), (d) the `starts` list (output frame positions) correctly accounts for transition overlap subtraction — verify `cursor -= transition_by_pair.get(...)` uses the right pair key.

17. **MLT caption subtitle filters** — `build_mlt.py` generates one MLT `subtitle` filter per caption style (normal, emphasis, cta, cover). Verify: (a) each filter references the correct SRT file path (`srt_paths.get(name)`), (b) the cover title split logic (`_split_cover_title`) creates separate `captions.cover_primary.srt` and `captions.cover_accent.srt` files with correct timing, (c) the font family name is resolved through `render_font_family()` — verify Ray font mappings (e.g., "RAY-EXTRABLACK" → "Ray ExtraBlack"), (d) for Persian content, `_plan_is_persian()` correctly detects Persian characters in captions and switches to `persian_font` from the preset, (e) the `font_library.family_for_plan()` and `stage_for_job()` calls correctly resolve custom font IDs to font family names and staged font files.

18. **SRT timing precision and overlap prevention** — `captions.py:build_srts()` shortens each cue's end time by 1 frame (`1/fps`) to prevent back-to-back cues from painting on the same frame. Verify: (a) the frame subtraction `end = max(c.start + 1e-3, c.end - frame)` doesn't produce negative durations when a cue is shorter than one frame, (b) captions that overlap with the cover title are correctly handled — cues fully within the cover window are skipped, cues partially overlapping have their start clamped to `cover.end`, (c) the `srt_time()` function correctly formats times with comma-separated milliseconds (SRT standard: `00:01:23,456`), (d) negative time values are clamped to 0.

19. **ASS colour format conversion** — `captions.py:ass_colour()` converts `#RRGGBB` or `#RRGGBBAA` to ASS `&HAABBGGRR` format; `mlt_colour()` converts to MLT's `0xRRGGBBAA`. Verify: (a) the byte order reversal is correct (ASS is BGR+alpha, MLT is RGB+alpha), (b) the default alpha values are correct: ASS alpha 00 = opaque, MLT alpha ff = opaque (opposite conventions), (c) invalid hex strings (wrong length, non-hex chars) raise `ValueError` with a useful message, (d) the `style_geometry()` function calculates subtitle positioning correctly — margin_bottom is measured from the BOTTOM of the canvas, not the top.

20. **Melt runner and macOS font loading** — `render.py:render()` runs melt to convert MLT XML → MP4. Verify: (a) `melt_bin()` finds `melt` or `melt-7` on PATH — verify it doesn't silently fall back to a wrong binary, (b) `_macos_font_loader()` compiles a CoreText dylib from `macos_font_loader.c` using clang — verify the compiled `.dylib` is cached (not recompiled every render), (c) `_melt_env()` sets `DYLD_INSERT_LIBRARIES` on macOS and `FONTCONFIG_FILE` on Linux — verify both paths resolve correctly and the environment variables are passed to the melt subprocess, (d) the CRF parameter (quality) differs for preview vs final render — verify the default values (preview CRF vs final CRF), (e) the optional loudnorm second pass is correctly wired — it should run ffmpeg on the melt output to normalize audio levels.

21. **Poster export** — `render.py:export_poster()` extracts a single frame as JPEG. Verify: (a) the frame time comes from `plan.poster.frame_time` — verify this time is on the OUTPUT timeline (not source), (b) the ffmpeg command uses `-ss` before `-i` for fast seeking — verify the seek target is correct, (c) the output filename convention is consistent with what Render.tsx expects (`*_poster.jpg`), (d) if the render output doesn't exist yet, poster export should fail gracefully rather than crash.

22. **ffprobe wrapper edge cases** — `probe.py` provides `probe_duration`, `video_dimensions`, `has_audio`, and `cover_scale`. Verify: (a) `probe_duration` parses JSON output — if ffprobe returns no duration (e.g., a pipe input or corrupt file), `float(...)` will raise — is this handled?, (b) `cover_scale()` computes zoom to fill canvas without black bars — verify the aspect ratio comparison (`abs(src_aspect - canvas_aspect) < 0.01`) is a reasonable epsilon, (c) `video_dimensions()` returns (width, height) — verify the stream parsing doesn't crash on files with no video stream (the `video_stream()` function raises `ValueError`), (d) `has_audio()` iterates all streams — verify it returns False (not raises) for video-only files.

---

## Part D — Job Management and Background Workers

### Files to read

- `app/jobs.py` — job lifecycle, background generate and render workers
- `app/main.py` — FastAPI endpoints (relevant sections for generate, render, transcript)

### Items to verify/fix

23. **Generate worker pipeline ordering** — `jobs.py:_run_generate()` runs the full pipeline: transcribe → auto-correct → silence detect → plan → validate. Verify: (a) if `use_saved_transcript` is True, transcription is skipped and the existing transcript is loaded from disk — verify it falls back to re-transcribing if no saved transcript exists, (b) auto-correction runs AFTER transcription and BEFORE plan generation — the corrected transcript is what gets passed to `generate_plan()`, (c) high-confidence corrections (≥ 0.85) are auto-applied via `save_corrections()` before plan generation, while lower-confidence ones are saved as suggestions for UI review, (d) the glossary is loaded once at the start and passed to both `auto_correct()` and `transcribe()` (for initial_prompt seeding).

24. **Generate worker state machine** — `jobs.py` tracks generation status through stages: `queued` → `transcribing` → `correcting` → `detecting_silence` → `planning` → `done`/`error`. Verify: (a) every stage transition updates the job's `generate_state` so the UI can poll it, (b) if an exception occurs at any stage, the state is set to `error` with the exception message, (c) the generate worker runs in a background thread — verify the thread lock prevents two generate workers from running simultaneously on the same job, (d) the `transcribe_only` mode (from the UI's "Re-transcribe only" button) correctly stops after transcription without generating a plan, and updates status to `done` (not `error`).

25. **Render worker and version management** — `jobs.py:start_render()` runs build_mlt → melt render → poster export in a background thread. Verify: (a) the render output filename includes a version suffix (so previous renders aren't overwritten), (b) the `RenderState` tracks progress percentage — verify melt's stdout/stderr is parsed for progress (melt outputs frame counts), (c) after a successful render, `export_poster()` is called — verify it doesn't crash if the plan has no poster field, (d) the render worker correctly distinguishes preview (540×960, higher CRF) from final render (1080×1920, lower CRF), (e) if melt returns a non-zero exit code, the error message includes melt's stderr output for debugging.

26. **Job rescan and recovery** — `jobs.py:rescan()` rebuilds the in-memory job registry from disk and recovers stale states. Verify: (a) jobs left in `running` state (from a previous server crash) are reset to `queued` or `error`, (b) the rescan correctly reads `plan.json`, `transcript.json`, and render outputs from the job directory, (c) job directories without a valid `meta.json` are skipped (not crash the rescan), (d) the rescan is called once at server startup — verify it doesn't interfere with jobs that are genuinely running (race condition if the server restarts while a render is in progress).

27. **Save plan validation and change detection** — `jobs.py:save_plan()` validates and persists plan.json with change detection. Verify: (a) the plan is validated using `schema.py:validate_plan()` before saving — invalid plans are rejected with specific error messages, (b) change detection compares the new plan against the saved one — verify it correctly detects changes in segments, captions, effects, and transitions, (c) after saving, the Premiere link hash chain is invalidated if plan-dependent artifacts changed, (d) the saved plan.json is pretty-printed (`indent=2, ensure_ascii=False`) so it's human-readable and Persian text isn't escaped.

---

## Part E — Schema Validation

### Files to read

- `engine/schema.py` — Pydantic models and validate_plan()

### Items to verify/fix

28. **EditPlan schema completeness** — `schema.py` defines Pydantic models for the entire plan structure. Verify: (a) all fields referenced by `build_mlt.py` exist in the schema (source, segments, captions, broll, sfx, music, canvas, visual_effects, transitions, cover, poster, export), (b) the `Segment` model has `in_` and `out` fields (note: `in` is a Python keyword, so Pydantic uses `in_` with alias) — verify serialization uses "in"/"out" in JSON, not "in_"/"out", (c) the `BoundaryTransition` model includes all transition types (hard_cut, crossfade, directional, zoom) with their specific fields (direction, intensity, zoom_mode, zoom_scale), (d) the `Canvas` model includes `caption_font` and `caption_font_id` fields that the font library system depends on.

29. **validate_plan media and timing checks** — `validate_plan()` performs structural validation. Verify: (a) segment `in` must be < `out` (no zero-duration or reversed segments), (b) segment IDs must be unique, (c) visual effect segment_ids must reference existing segments, (d) transition from/to segment_ids must reference adjacent segments, (e) caption start must be < end and within the output timeline duration, (f) the `check_media` flag controls whether file existence is verified — verify `generate_plan()` calls with `check_media=False` (files may not exist during planning), (g) frame caps per output_kind are enforced for transitions.

---

## Part F — Web UI

### Files to read

- `web/src/NewReel.tsx` — job creation page
- `web/src/PlanReview.tsx` — plan editor with visual editor, transcript, corrections
- `web/src/Render.tsx` — render progress and playback page
- `web/src/api.ts` — API client

### Items to verify/fix

30. **NewReel job creation flow** — `NewReel.tsx` handles video upload and plan generation. Verify: (a) the video file type check accepts `.mp4` and `.mov` (and any `video/*` MIME type), (b) the "Generate Edit Plan" button passes all UI parameters to the API: `style`, `instruction`, `whisper_model`, `language`, `asr_engine`, `transcription_hint`, `caption_font`, `caption_font_id`, `style_id`, `style_version`, `output_kind`, `transition_style`, `transition_request`, (c) the generation status poller (`setInterval(tick, 1500)`) cleans up on component unmount (the `useEffect` returns a cleanup function), (d) when generation completes (`status === "done"`), the user is navigated to the plan review page — verify the `nav()` call uses the correct path, (e) the "Create (with manual plan)" button allows uploading a pre-made plan.json — verify validation errors are shown.

31. **PlanReview visual editor** — `PlanReview.tsx` is a complex 843-line component with transcript editing, correction review, visual plan editing, and Premiere integration. Verify: (a) the `VisualEditor` subcomponent renders segments with their effects, captions with style badges, transitions with type selectors, B-roll, and SFX — verify all `onUpdate` callbacks produce valid plan JSON, (b) the `TranscriptView` subcomponent marks removed words (not in any segment's time range) with `tw-removed` class and low-confidence words with `tw-low` — verify the removed-word detection correctly maps word timestamps to segment boundaries, (c) the `ReviewCorrectionsPanel` shows auto-applied corrections (green) and pending suggestions (yellow) — verify the "Accept all high-confidence" button only accepts corrections with confidence ≥ 0.85, (d) the transition editor allows changing type, duration_frames, direction, and intensity — verify `updateTransition()` correctly shifts all downstream events (captions, broll, sfx, music duck) when overlap frames change.

32. **PlanReview save and regenerate flow** — Verify: (a) `save()` calls `api.putPlan()` and shows validation errors if the plan is invalid, (b) `doRender()` saves the plan first, THEN starts the render — if save fails, render does not start, (c) `regenerateFromTranscript()` saves the current plan, then calls `generatePlan` with `use_saved_transcript: true` — this preserves the user's transcript corrections, (d) `retranscribeOnly()` calls `generatePlan` with `transcribe_only: true` — this creates a new transcript candidate without touching the existing plan, (e) the plan validation debounce (`setTimeout(async () => {...}, 400)`) fires correctly and cleans up on rapid edits.

33. **PlanReview Premiere compatibility section** — The plan review page includes a detailed Premiere compatibility report. Verify: (a) the report shows transition-by-transition capability classification (exact_editable, editable_fallback, rendered_only), (b) unverified items in the current package are highlighted with error styling, (c) the download buttons (ZIP, XML, SRT) all call `preparePremiereDownload()` which saves the plan first, (d) the compatibility report refreshes after plan save (`api.premiereReport(id).then(setPremiereManifest)`), (e) when the plan has unsaved changes, a stale warning is shown: "Compatibility package is stale. Save the current Edit Plan before downloading."

34. **Render page polling and display** — `Render.tsx` polls render status every 1 second. Verify: (a) the poller interval (1000ms) cleans up on component unmount, (b) the progress bar width is set from `s.progress` percentage, (c) when finished, the video element uses `api.exportUrl(id, s.output)` for src and the poster uses `_poster.jpg` suffix — verify these URL patterns match the backend's static file serving, (d) previous versions are listed below the current export, (e) the `PremiereCard` component is rendered with a key that includes status and output — verify this forces re-mount when the render finishes (so Premiere link status refreshes).

---

## Part G — Cross-Cutting Integration Checks

### Items to verify

35. **End-to-end data flow: transcript → plan → MLT → render** — Trace the complete data flow for a Persian video: (a) `transcribe()` produces a transcript dict with `words` (each having `w`, `start`, `end`, `prob`), `sentences`, `language`, `file_hash`, (b) `auto_correct()` produces corrections that `save_corrections()` applies to modify word text, (c) `detect_pauses()` produces `keep_ranges` and `remove_ranges` from the transcript, (d) `generate_plan()` receives transcript + ranges and produces a plan dict matching the `EditPlan` schema, (e) `build()` in `build_mlt.py` converts the plan into a `.mlt` XML file + `.ass` + `.srt` files, (f) `render()` runs melt on the `.mlt` file to produce an MP4. Verify that at no point in this chain does a field name mismatch, a missing key, or a type incompatibility cause a silent failure.

36. **Timeline coordinate systems** — AI Render uses two timeline coordinate systems: source time (raw video position) and output time (after segment cuts and transition overlaps). Verify: (a) segment `in`/`out` are always in SOURCE time, (b) caption `start`/`end` are in OUTPUT time (after `_retime_for_transition_overlaps`), (c) `source_to_output_time()` and `output_to_source_time()` in `planner.py` correctly convert between the two, (d) the UI's `outputToRaw()` function in `Timeline.tsx` matches the Python conversion logic, (e) the transcript word timestamps are in SOURCE time and the visual editor's removed-word detection uses source time comparison against segment boundaries.

37. **Cost tracking accuracy** — Multiple LLM calls accumulate cost: `chat_json()` in planning, `chat_vision()` in effect scoring, `chat_json()` in correction, `chat_json()` in segment analysis. Verify: (a) `LLMUsage` dataclass correctly accumulates `input_tokens`, `output_tokens`, `elapsed_sec` across all calls, (b) the `cost_estimate` property uses the `_PRICING` dict with correct per-model rates, (c) the total cost is reported to the UI via the generate status endpoint — verify `genStatus.cost_usd` in the UI matches the sum of all LLM calls, (d) ASR cost (`asr_cost_usd`) is tracked separately and displayed alongside LLM cost.

---

Run all tests. Report each item (1–37) as ✅ correct, 🔧 fixed (with what changed), or ⚠️ blocked (with why).
