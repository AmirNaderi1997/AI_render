# Effect variety and Persian transcript accuracy

Observed on 2026-10-01 for job `9624f5ffa3ae`. The sections below record the original handoff and the implementation completed afterward.

## Implementation status (2026-10-01)

- Implemented a versioned `visual_effects` contract with 100 named presets, schema validation, MLT render support, Kdenlive export, planner instructions, a deterministic fallback rhythm, an `/effects` catalog, and a per-segment editor picker. The 100 presets are combinations of ten framing motions and ten light treatments. They are not 100 unrelated filter algorithms.
- Implemented settings-aware ASR candidate caching, a local Persian `medium` default, optional speech-term hints, raw candidate archives, per-candidate word and time corrections, low-confidence highlighting, re-transcription without a plan-model call, and regeneration from the reviewed transcript.
- Generated plans now mark captions whose text, timing, or source-word confidence needs review. The Plan Review UI shows those warnings and requires an audio-review acknowledgement before final render.
- Verification: focused Python tests and the frontend build pass. A short `punch__pulse_start` clip rendered and exported to Kdenlive; its affine and brightness filters are present in the project. An offline medium-model candidate for this job had 18/107 words below 0.60 confidence, compared with 32/114 in the stored transcript. Several Persian words were still wrong, so the current job's plan and render were left untouched.
- Remaining proof: listen through the source and manually establish the exact disputed wording; review a newly generated full reel in the browser and in Kdenlive. The medium-model confidence comparison is not an accuracy score.

## Current evidence

- The preview render completed and the plan is valid. Its 11 kept segments all have `zoom` from `1.0` to either `1.08` or `1.15`; the visual pattern repeats throughout the reel.
- `engine/schema.py` gives each segment only a `zoom` field. `brain/planner.py` asks for slow zoom or punch-in, and `engine/build_mlt.py` emits an affine zoom on every segment. There is no general visual-effect contract or review control in the UI.
- `brain/transcribe.py` produces word timestamps with faster-whisper. `app/jobs.py` defaults to `WHISPER_MODEL=small`; this job did not record the model actually used. For this Persian recording the stored transcript has 114 words, 32 with probability below 0.60, and visible mistakes such as `مخصول`, `ایرای`, and `سرمایی`. The planner improves some caption spelling, but captions such as `ولی خدمات نمی‌دونم` need to be checked against the audio before treating them as quotations.
- Transcript caching uses only the input file hash. Changing model, language, or decoding settings does not invalidate an existing transcript for the same video.
- The existing stage plan limits the MVP to cut, pause removal, zoom, subtitles, music, SFX, and B-roll. Extend the existing edit plan and renderer. Preserve the current seven features and the ability to open the project in Kdenlive.

## Work order

### 1. Establish a checked transcript for this clip

1. Preserve `transcript.json`, `plan.json`, and the current preview as baseline artifacts. Do not overwrite them while testing.
2. Listen to the original audio around 25-60 seconds and create a manually checked Persian reference for the kept speech, including ambiguous words and timestamps. Mark uncertain audio as uncertain; do not infer words from context alone.
3. Re-run transcription as a separate candidate with a stronger Persian-capable model and explicit `language=fa`. Record model name, decoding/VAD settings, audio hash, and runtime. Compare it against the checked reference, including omitted words, substitutions, and timestamp drift. The current small-model result remains available for comparison.
4. Change the cache key to include audio/file hash, model, language, and decoding/VAD settings. Keep the raw ASR output immutable and store reviewed corrections separately with provenance.
5. Add a transcript-review UI: edit word text, split/merge words, flag uncertainty, seek to source time, and save corrections. Corrected words must drive pause detection and plan generation. Regeneration must not silently discard user corrections.
6. Generate captions from corrected words and mapped output times. Let the LLM choose grouping and emphasis, but require every quoted caption to be supported by a contiguous span of kept speech. Flag paraphrases for review instead of presenting them as verbatim captions.

Acceptance: the checked words for this job are present in the transcript and captions; a reviewer can trace each caption to kept source audio; changing ASR settings causes a fresh candidate; corrected words survive regeneration; word and caption times remain aligned after cuts. Record the remaining uncertain spans explicitly.

### 2. Add visual variety through a bounded effect contract

1. Keep the existing `zoom` plans readable. Introduce a versioned optional `visual_effects` list with typed effects, source/output timeline rules, bounds, and overlap validation. Unknown effect types must fail validation instead of disappearing at render time.
2. Start with effects the current MLT/Kdenlive path can verify: a steady shot (`none`), a held punch-in, a slow push/pull, and a position-aware pan/reframe using affine keyframes. Add a brief cut accent only after confirming its MLT render and Kdenlive editability with a prototype. Avoid speed changes or freeze frames in this pass because they change output time and caption mapping.
3. Make the planner choose from the supported set based on speech emphasis, shot composition, and cut rhythm. Do not require an effect on every segment. Cap consecutive repeats and enforce a minimum quiet interval between accents. Preserve faces and caption safe zones when reframing; if framing analysis is unavailable, use centered framing and avoid speculative pans.
4. Display each chosen effect, duration, and parameters on the timeline and in the visual editor. Provide `none` and manual override. The UI must show when an effect was skipped because it could not be rendered.
5. Add a small reference set of approved reels or annotated shots before tuning the effect selection rules. The goal is to match the chosen style, not to add effects at random.

Acceptance: an unchanged v0.1 plan renders as before; the new plan validates and round-trips through JSON/UI/MLT/Kdenlive; a sample clip visibly demonstrates steady, held punch, and one pan/reframe without cropping the speaker or captions; the planner does not produce the current alternating 1.08/1.15 pattern on every segment. Compare preview frames and the Kdenlive timeline, not just the JSON.

### 3. Integrate and review

1. Rebuild this job from its checked transcript into a new plan and new preview version, leaving `v1_preview.mp4` available.
2. Review the rendered captions against source audio at each cut and inspect frames around every effect transition. Check Persian shaping, caption safe zones, audio continuity, and whether B-roll and SFX correspond to actual available assets.
3. Run the existing test suite plus focused tests for cache invalidation, correction persistence, source-to-output caption mapping, effect bounds, legacy plans, and MLT/Kdenlive export. Record pass/fail and any unsupported effect explicitly.

## Rollback and limits

- A new plan/effect version is additive. The existing `zoom` field and renderer remain the fallback until the new path passes render and Kdenlive checks.
- Do not auto-replace the user's current plan or render. Save comparisons as new candidates/versions.
- A stronger ASR model improves the candidate transcript but does not prove it is correct. The checked reference and audible source remain the authority for disputed words.
- Do not call a paid transcription or LLM provider solely to execute this plan without the user's authorization; local model experiments can be run independently.
