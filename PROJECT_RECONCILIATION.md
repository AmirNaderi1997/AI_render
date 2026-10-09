# AI Render — Project Reconciliation Report
**Date**: 2026-10-06

---

## 1. Architecture Overview

The project follows a three-stage architecture as defined in `plan.md` and `stages.md`:

| Stage | Purpose | Status |
|-------|---------|--------|
| Stage 0 | Environment setup | ✅ Complete |
| Stage 1 | JSON Edit Plan → MLT → MP4 + UI | ✅ Complete |
| Stage 2 | AI Brain: raw video → Edit Plan | ✅ Complete |
| Stage 3 | Premiere Pro interchange + bridge | ✅ Complete (with 2 minor bugs now fixed) |
| Stage 4 | Auto QC (AI reviews own output) | ❌ Not started |
| Stage 5 | Personal style learning | ❌ Not started |

---

## 2. Module Map: Original vs Codex-Added

### Core (Original — committed in Stage 1)

These modules were part of the original `b0fe426` commit ("Complete Stage 1"):

| Module | Lines | Purpose |
|--------|-------|---------|
| `engine/schema.py` | 351 | Edit Plan Pydantic models (Canvas, Segment, Zoom, Caption, Cover, Broll, Music, Sfx, Export, EditPlan) |
| `engine/build_mlt.py` | ~400 | MLT XML project builder — cuts, zooms, transitions, B-roll, music ducking, SFX |
| `engine/captions.py` | ~300 | ASS + SRT caption generation, font family resolution, style geometry |
| `engine/render.py` | ~250 | melt runner with progress streaming, poster export, macOS CoreText font loader |
| `app/main.py` | 800 | FastAPI backend — job CRUD, render, generate, Premiere routes |
| `app/jobs.py` | 532 | In-memory job registry, background render worker, generate pipeline orchestration |
| `web/src/NewReel.tsx` | 322 | Upload raw video + plan JSON |
| `web/src/Render.tsx` | 93 | Render button, progress bar, MP4 playback |
| `web/src/PlanReview.tsx` | 863 | Plan editor, transcript viewer, timeline, visual effects UI |
| `web/src/api.ts` | 305 | TypeScript API client |
| `web/src/main.tsx` | 93 | React router setup |
| `web/src/Timeline.tsx` | 97 | Visual timeline component |
| `presets/rafiei_reel.yaml` | — | Default style preset |

### Brain Modules (Codex-added — Stage 2, commits `4c28059` through `9ae4519`)

| Module | Lines | Added by | Purpose |
|--------|-------|----------|---------|
| `brain/transcribe.py` | 353 | Codex | faster-whisper word-level transcription, settings-aware caching |
| `brain/transcribe_elevenlabs.py` | 183 | Codex | ElevenLabs Scribe v2 alternative ASR |
| `brain/correct.py` | 591 | Codex | Auto transcript correction — context-aware LLM, similarity guardrail, merge/split |
| `brain/planner.py` | 966 | Codex | LLM-based edit plan generator — drop retakes, choose zooms, write captions, propose B-roll |
| `brain/llm.py` | 410 | Codex | LLM provider abstraction (OpenAI-compatible, jarvis.you, vision) |
| `brain/silence.py` | 134 | Codex | Pause/silence detection with symmetric padding |
| `brain/glossary.py` | 81 | Codex | Persistent correction glossary |
| `brain/segment_analysis.py` | 204 | Codex | Segment role/energy/emotion classification |
| `brain/signals.py` | 88 | Codex | Audio signal measurement (loudness, speech rate) per segment |
| `brain/effect_score.py` | 373 | Codex | Effect scorer — role→family affinity matrix, variety constraints |
| `brain/effect_score_v4.py` | 470 | Codex | Vision-aware V4 effect scorer with keyframes + user rules |

### Effects V4 System (Codex-added — commits `e571592` through `07b7b76`)

| Module | Lines | Purpose |
|--------|-------|---------|
| `engine/effects.py` | ~250 | 100 bounded presets (10 motions × 10 lights), legacy effect catalog |
| `engine/effects_v4.py` | ~550 | Extended catalog: camera shake, freeze frame, speed ramp, blur, vignette, RGB split, text pop, emoji pop |
| `web/src/MyEffects.tsx` | 366 | Custom effects presets UI |
| `presets/my_effects.yaml` | — | User-defined effect rules and favorites |

### Premiere Integration (Codex-added — Stage 3)

| Module | Lines | Purpose |
|--------|-------|---------|
| `engine/premiere.py` | ~500 | FCP7 XML generation, SRT captions, compatibility manifest, native verification records |
| `app/premiere_bridge.py` | 453 | Bridge protocol — sessions, pairing, receipt validation, hash-bound identity |
| `app/premiere_desktop.py` | 345 | macOS handoff — project linking, status, hash tracking |
| `web/src/PremiereCard.tsx` | 169 | React UI for Premiere integration |
| `premiere-bridge/jsx/bridge.jsx` | ~340 | ExtendScript inside Premiere — sequence/render/caption import |
| `premiere-bridge/js/panel.js` | ~200 | CEP panel polling + pairing |
| `premiere-bridge/index.html` | ~100 | CEP panel dark UI |
| `premiere-bridge/CSXS/manifest.xml` | — | Extension manifest (Premiere 25.0–25.5) |

### Other Codex-Added Modules

| Module | Lines | Purpose |
|--------|-------|---------|
| `engine/style_library.py` | 321 | Visual style profiles with provenance tracking |
| `engine/kdenlive.py` | ~180 | Kdenlive project export from MLT graph (Stage 1 addition, now secondary to Premiere) |
| `engine/font_library.py` | — | Font management for caption rendering |
| `web/src/FontLibrary.tsx` | 149 | Font browser UI |
| `web/src/StyleLibrary.tsx` | 178 | Style profile management UI |
| `tools/critic_vision_pass.py` | — | Vision model QC pass tool |
| `tools/generate_showcase_reel.py` | — | Showcase reel generator |
| `tools/build_rebuilt_stories.py` | — | Story rebuilding tool |
| `tools/split_collage.py` | — | Collage splitter tool |

---

## 3. Merge Consistency Check

### ✅ No Issues Found

- **Schema imports**: All modules import from `engine.schema` consistently. The `Plan = EditPlan` alias at line 273 provides backward compatibility for modules that use the `Plan` name (`build_mlt.py`, `captions.py`).
- **Python syntax**: All `.py` files parse without errors.
- **Version field**: `EditPlan.version` defaults to `"0.1"`, planner sets it to `"0.2"` on new plans. No code branches on this value — it's purely informational.
- **Effect system**: V4 effects extend the V3 catalog cleanly. `VisualEffect.type` validator checks V4 first, falls back to V3 `canonical_effect()`.
- **Persian normalization**: Consistent `normalize_persian()` in both `transcribe.py` and `correct.py`.
- **Premiere bridge protocol**: Backend Pydantic models match JSX receipt structure exactly. `StrictStr` + `min_length=1` on `active_path` matches the JSX `"none"` default.

### ⚠️ Minor Observations (Not Bugs)

1. **Kdenlive code still present**: `engine/kdenlive.py` and `test_kdenlive.py` remain in the repo even though `stages.md` and `plan.md` now say "Premiere Pro is the editable project target." This is harmless — Kdenlive export works as a fallback and the code is not dead (it's still importable and tested). No action needed unless you want to trim it.

2. **Five root-level .md report files**: `AUDIT_REPORT.md`, `PREMIERE_BRIDGE_FIX_SUMMARY.md`, `PREMIERE_BRIDGE_SETUP.md`, `PREMIERE_PAIRING_DEBUG.md`, `QUICK_START.md` — these are Codex-generated documentation artifacts. They are accurate and useful for onboarding but could be moved to `docs/` for cleaner root layout.

3. **`stages.md` still mentions Kdenlive as alternative**: Line in Stage 0 says "Premiere Pro (optional: Kdenlive as alternative)" and Stage 1 says "same project opens in Premiere Pro (or Kdenlive as alternative)." This is technically still true since the Kdenlive exporter works, so no update strictly needed.

---

## 4. Bugs Fixed in This Session

### Bug #1: Dead localStorage write in PremiereCard.tsx
**File**: `web/src/PremiereCard.tsx`  
**What**: `localStorage.setItem("airender_port", backendPort)` wrote the backend port to the web UI's browser localStorage. The CEP panel inside Premiere runs in a completely separate CEF browser instance with its own origin — it can never read this value. The CEP panel already reads its port from its own `index.html` input field.  
**Fix**: Removed the dead code and replaced with a comment explaining why the port is not stored here.

### Bug #2: importOne error details silently swallowed in bridge.jsx
**File**: `premiere-bridge/jsx/bridge.jsx`  
**What**: When `app.project.importFiles` throws inside `importOne()`, the function returns `{error: String(e)}`. But the callers for render reference (line ~276) and captions (line ~300) only checked `!renderResult.item` / `!captionResult.item` and pushed generic messages like "Could not import rendered reference." without the underlying exception detail.  
**Fix**: Both callers now check `result.error` and append `" Reason: " + result.error` to the error message, so users see the actual Premiere error in the bridge receipt and in the CEP panel banner.

---

## 5. Test Coverage Summary

The project has 26 test files covering:

| Area | Test Files | Coverage |
|------|-----------|----------|
| Schema & validation | `test_schema.py` | Edit Plan validation, segment ordering, zoom bounds |
| Brain pipeline | `test_brain.py`, `test_correct.py`, `test_transcribe.py`, `test_elevenlabs.py` | Transcription, correction, planner |
| Effects | `test_effects_v4.py`, `test_v4_full_integration.py`, `test_v4_real_run.py`, `test_v4_simple.py` | V4 catalog, integration, real-run |
| Render engine | `test_render.py`, `test_captions.py`, `test_916_framing.py` | MLT build, caption output, portrait framing |
| Premiere | `test_premiere.py`, `test_premiere_bridge.py`, `test_premiere_desktop.py` | XML gen, bridge protocol (20+ tests), desktop handoff |
| Other | `test_font_library.py`, `test_style_library.py`, `test_rafiei_styles.py`, `test_model_config.py`, `test_plan_only.py`, `test_registry_rescan.py`, `test_smarter_brain.py`, `test_vision_render.py` | Fonts, styles, models, registry |

---

## 6. Current Project Status

**What works end-to-end:**
- Upload raw video → AI generates Edit Plan (Stage 2) → render MP4 (Stage 1) → export Premiere FCP7 XML + SRT + ZIP → bridge into Premiere Pro with automated sequence/render/caption import (Stage 3)
- 100 visual effects (V3) + extended V4 effects with vision-aware selection
- Persian (Farsi) and English support throughout transcription, correction, and captions
- ElevenLabs and faster-whisper as interchangeable ASR engines
- Style profiles with provenance tracking
- Custom "My Effects" presets with rules and favorites

**What's not started:**
- Stage 4 (Auto QC) — AI reviews rendered output and suggests fixes
- Stage 5 (Personal style learning) — learn from user's reference reels
- Stage 3 (Auto Assets) from `stages.md` — automated B-roll/music/SFX selection from indexed library

**Recommendation:** No files need updating based on the current progress. The codebase is internally consistent, the schema is stable, all modules integrate cleanly, and the two minor bugs are now fixed. The five root-level `.md` files could optionally be moved to `docs/` for tidiness.
