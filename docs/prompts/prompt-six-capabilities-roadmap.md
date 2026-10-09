# AI_render: six-capability implementation roadmap and agent prompts

Planning document, 2026-10-03. This document authorizes no implementation or paid provider call by itself. Run the prompts **one at a time**, in order, and accept each stage before starting the next. Each prompt is designed to be pasted into a coding agent working in this repository.

## Current project fit

The existing authority is the Edit Plan JSON: `engine/schema.py` validates it, `brain/planner.py` generates it, `engine/build_mlt.py` renders it, and the web app reviews it. `presets/rafiei_reel.yaml` supplies a style. The current plan already has one `music` track with ducking and a caption font choice; these are starting points for stages 1 and 4. `docs/stages.md` describes the original MVP and later style learning. These six stages extend that roadmap; they do not declare the earlier stages complete. Existing effects and transitions need rendered verification before reuse.

### Rules shared by all six stages

1. Inspect `git status`, relevant code, tests, and the latest handoff before edits. Preserve unrelated modified files, jobs, media, and secrets. Never reset, stash, broad-clean, or commit with `git add -A`.
2. Extend the single Edit Plan → MLT/Kdenlive → MP4 path. Add versioned optional fields and migrations only where needed. Old plans must still validate and render. Do not create a second production renderer or a second style authority.
3. Save imported/generated assets in a managed library with stable IDs, source/provenance, content hash, review state, and usage references. Saving a candidate is distinct from approving it. User choices in My Effects and manually selected fonts/styles/music override AI selection.
4. Make preview, plan review, final render, and Kdenlive export agree. Show skipped/unsupported actions visibly; fail validation for unknown required types. Source timeline and output timeline must remain explicit.
5. For each stage, use a fresh job and keep its original input, candidate plan, approved plan, render, project file, and evidence. Run focused tests and a real media acceptance path through the app API/UI. Record model/provider, settings, cost when applicable, and actual output evidence. A mock, configuration, old job, or schema assertion is not a completed stage.
6. Respect font and media licenses, provider terms, and user-supplied rights. Keep credentials out of plans, logs, and committed files. Ask before a paid call if the user has not already authorized it.

## Stage 1 — Learn, save, and use fonts

**User flow.** Add a Font Library with three inputs: pasted/copied text, a text image, or a `.ttf`/`.otf` font file. For pasted text, the user supplies a name of the font or a reference screenshot when exact identity matters; text alone has no visual font information. For images, detect text and estimate candidate families, then ask the user to confirm; do not claim exact identification from pixels. A font file can be inspected for actual family/style metadata, glyph coverage, license information when present, and renderability. Save an approved font entry, show Persian/English samples, and let the user choose it for captions, covers, and posts.

**Implementation order.** Library schema and upload/validation → extraction and candidates → preview/approval UI → plan reference and renderer → Kdenlive portability. Prefer a saved font ID plus resolved font family/file over a free-form display name. Test Unicode Persian shaping, RTL, mixed Latin, digits, weights, fallback glyphs, and missing-font behavior. Do not synthesize a replacement font from a text image in this stage.

**Done when.** Each input route returns a reviewable candidate; an approved file font survives restart; the selected font is visibly used in preview and final MP4; the plan and Kdenlive project retain the intended selection; a legacy plan still renders. For an image-only reference, the UI labels uncertain matches as approximate.

### Paste prompt 1

> Implement Stage 1 from `docs/prompts/prompt-six-capabilities-roadmap.md`. First inspect the dirty worktree and the existing caption font path in `engine/schema.py`, `engine/captions.py`, `engine/build_mlt.py`, `app/main.py`, `web/src/NewReel.tsx`, and `web/src/PlanReview.tsx`. Build the Font Library and the three import paths specified in Stage 1. Preserve the current caption font behavior and My Effects precedence. Keep candidate detection separate from user approval; do not imply that pasted characters identify a font. Add only focused tests, then prove one approved Persian-capable font on a fresh app job with plan, rendered frames, MP4, and Kdenlive export. Report exact paths and any limitation. Do not start Stage 2.

## Stage 2 — Learn, save, and use visual styles

**User flow.** A user imports still snapshots, a reference video, or a style file. The app extracts a **draft style profile**: palette, typography clues, framing, caption layout, cut cadence, transitions, grain/texture, overlays, and audio mood. A still cannot prove timing or motion; the UI marks those fields unknown. A video can provide observed timing and motion. A style file must be schema validated and shown for review. The user edits and approves a named, versioned style in the Style Library; applying it to a new job pins that version.

**Implementation order.** Define a versioned style profile that extends existing preset fields → secure import and analysis → side-by-side reference/preview UI → user approval and immutable versioning → planner/render integration. Keep `presets/rafiei_reel.yaml` and My Effects as authorities until an approved style is explicitly selected. Do not infer invisible settings, spoken text, or a font identity from video pixels. Store source frame/time evidence for each inferred property.

**Done when.** A still-only profile has no invented motion values; a video profile shows sampled evidence; an imported style file round-trips; selection survives restart and regeneration; manual My Effects selections still win; one fresh render demonstrates the approved style with matching plan and Kdenlive project.

### Paste prompt 2

> Implement Stage 2 from `docs/prompts/prompt-six-capabilities-roadmap.md` after Stage 1 acceptance. Inspect the existing preset loader, planner, My Effects override, effect schema, and UI before coding. Add a reviewable Style Library for snapshots, reference videos, and validated style files, with versioned profiles and evidence for inferred values. Preserve `rafiei_reel` as the default and manual selections as hard overrides. Prove a saved style on a fresh generated plan and full render; inspect representative frames, timing, and Kdenlive export. Report what the reference did not reveal. Do not start Stage 3.

## Stage 3 — Improve transitions

**User flow.** Transitions become explicit, editable items between adjacent output segments: hard cut by default, plus a small verified set such as crossfade and directional/zoom transitions. The UI previews the exact boundary and exposes duration, direction, and intensity. AI may suggest a transition from shot context, but manual choice locks it. A transition must not cover a face or caption unexpectedly, flash black, break audio, or shift duration without corresponding plan/timeline mapping.

**Implementation order.** Audit current effect/transition behavior in MLT output → define a typed boundary transition with frame-based timing and overlap rules → render one transition at a time → map duration and caption/SFX timing → add boundary editor and planner selection. Keep quiet hard cuts available. If a proposed MLT effect cannot round-trip to Kdenlive, either use a verified equivalent or label export limits and do not call it complete.

**Done when.** Real rendered frames before/at/after each boundary match the plan; output duration differs from the planned duration by no more than one frame; audio has no click/dropout; every supported transition opens correctly in Kdenlive; legacy plans still use their current cuts.

### Paste prompt 3

> Implement Stage 3 from `docs/prompts/prompt-six-capabilities-roadmap.md` after Stage 2 acceptance. Inspect `engine/effects_v4.py`, `engine/build_mlt.py`, `engine/kdenlive.py`, plan validation, and current effect previews. Prototype and verify a small transition set in the actual MLT render before expanding the planner. Add explicit boundary timing and an editable UI control with manual lock. Render fresh short and full jobs, inspect boundary frames/audio, compare ffprobe duration with the plan within one frame, and open the project in Kdenlive. Report any unsupported transition plainly. Do not start Stage 4.

## Stage 4 — Load and mix music with video

**User flow.** Upload/select a licensed music file; audition it against the source; choose start offset, trim/loop, fades, gain, and speech ducking in Plan Review. Preserve source speech and existing SFX. Show a simple mix preview and audio meters. Start with one music bed because the plan already supports one; add multiple beds only if a real use case and renderer proof justify it.

**Implementation order.** Audit the existing `Music` schema, automatic asset selection, MLT mix, and output timeline bounds → managed music library and UI controls → deterministic gain/fades/ducking → clipping and loudness checks → export verification. Manual music choice must persist across plan regeneration. Do not silently select copyrighted tracks or replace a user's chosen file.

**Done when.** A selected track survives save/regenerate/restart; preview and final MP4 contain the same intended mix; voice remains intelligible; music start/end/fades align within one frame; no unintended silence, clipping, or output overrun; Kdenlive shows editable audio tracks.

### Paste prompt 4

> Implement Stage 4 from `docs/prompts/prompt-six-capabilities-roadmap.md` after Stage 3 acceptance. Extend the existing `music` plan and A1 mixer rather than adding a parallel audio pipeline. Add upload/library selection and Plan Review controls for offset, trim/loop where safe, gain, fades, and ducking. Keep the user-selected track locked across AI regeneration. Test an actual video with speech, music, and SFX via a fresh app job; listen to critical ranges, inspect waveform/loudness/clipping, verify duration and Kdenlive editability. Report exact evidence. Do not start Stage 5.

## Stage 5 — Prompt to Instagram Reel, post, or Story

**User flow.** A user enters a prompt, chooses Reel, post, or Story, aspect ratio/length where relevant, language, brand style, and an image/video generation provider or footage API. The app creates a **reviewable storyboard** with copy, scene timing, source/generation method, media candidates, and estimated cost before any paid generation. The user approves candidates, edits exact text, and renders through the existing path. For a static post, the plan may have one still frame and duration for export; a Story may be static or motion; a Reel has timed video. AI-generated imagery should leave text blank where precise Persian copy will be typeset deterministically.

**Implementation order.** Define content-type presets and storyboard/candidate records → provider-neutral adapter with explicit capabilities and cost reporting → asset generation/import with provenance and retry/idempotency → human review → conversion into the existing edit plan → media QC and export. First prove a local/no-cost fixture end to end; then connect one explicitly chosen provider. Handle provider failure, moderation, timeouts, and format mismatch as visible job states. Keep API keys server-side. For generated video/stills, explicitly model source duration and frame rate; do not pass a made-up raw video through the current upload endpoint.

**Done when.** One fresh example of each format exports at intended dimensions and duration, with exact approved Persian copy, safe zones, licensed/traceable assets, cost record, and Kdenlive project where applicable. An actual configured provider path is separately proven; fixture success alone is labeled partial.

### Paste prompt 5

> Implement Stage 5 from `docs/prompts/prompt-six-capabilities-roadmap.md` after Stage 4 acceptance. Begin by proposing a narrow extension that lets prompt-created still/video assets enter the existing Edit Plan renderer. Build storyboard review, format presets, candidate provenance, and a provider-neutral adapter. Ask for provider credentials or paid-call authorization only when needed for a real call; complete local fixture work first. Use approved exact Persian text with deterministic typesetting. Prove Reel, post, and Story exports from fresh jobs; then prove one real provider path if authorized, recording cost, failures, media metadata, frames, and final artifacts. Report fixture and provider evidence separately. Do not start Stage 6.

## Stage 6 — Remove background noise from video audio

**User flow.** After upload, show a short A/B sample of original and cleaned speech, with strength control and bypass. Save the original audio immutably and render from a derived cleaned asset when approved. Preserve speech timbre and synchronization. Distinguish broadband noise removal from source separation: overlapping voices/music may not be removable cleanly and must not be promised as such.

**Implementation order.** Analyze noise/sample ranges and baseline speech quality → local deterministic denoise first → optional provider/AI enhancement only with cost and privacy review → derived asset metadata in plan/job → final mix integration → A/B QC. Denoise the source speech before music/SFX mixing; never denoise the final mixed master as the primary path. Handle silent audio, clipped recordings, mono/stereo, and variable sample rates.

**Done when.** On a fresh noisy source, the user can compare original/cleaned at matched loudness; speech remains synchronized within one frame; cleaned speech is audibly improved without obvious artifacts; final MP4 and Kdenlive project use the approved take; bypass restores original audio; old plans behave identically.

### Paste prompt 6

> Implement Stage 6 from `docs/prompts/prompt-six-capabilities-roadmap.md` after Stage 5 acceptance. Inspect the current source-audio, A1 music, A2 SFX, render, and Kdenlive paths. Add reversible pre-mix speech denoise with an A/B review and a user-controlled strength/bypass. Keep originals immutable and record the chosen derived asset in the job/plan. Use local processing first; request authorization before any paid or external audio service. Verify a fresh noisy video by listening at matched loudness, checking sync, speech quality, final mix, plan duration, and Kdenlive export. Report residual noise and artifacts honestly.

## Stage gate and handoff format

After each stage, produce a short handoff with: changed files, schema change and backward compatibility, user flow, fresh job ID and input hash, plan and asset IDs, preview/final MP4 and Kdenlive paths, media measurements, screenshots or frames, focused test results, provider/model/cost when used, known limitations, and a clear **accepted / partial / blocked / failed** status. Do not advance solely because tests or a development build pass.
