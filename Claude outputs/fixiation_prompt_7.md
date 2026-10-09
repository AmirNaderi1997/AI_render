# Fixiation Prompt 7: Effects V4 Pipeline, Style/Font Libraries, and Premiere ↔ AI Render Integration Gaps

Read every file listed below, then **fix** anything broken and **verify** every claim. Run all tests to confirm green before and after any changes.

---

## Part A — Effects V4, Style Library, Font Library

### Files to read

**Effects engine:**
- `engine/effects_v4.py` — extended effect catalog + MLT filter generation
- `engine/effects.py` — legacy v3 catalog and family definitions
- `brain/effect_score_v4.py` — scoring/selection of effects per segment
- `brain/effect_score.py` — legacy scoring
- `brain/segment_analysis.py` — LLM-based segment role/energy classification

**Style library:**
- `engine/style_library.py` — draft/approve/fork/delete style profiles from snapshots/video
- `web/src/StyleLibrary.tsx` — Style Library UI component

**Font library:**
- `engine/font_library.py` — candidate/approved font pipeline, fontTools metadata
- `web/src/FontLibrary.tsx` — Font Library UI component

**My Effects UI:**
- `web/src/MyEffects.tsx` — per-user effect rules + Rafiei style selection

**API surface:**
- `app/main.py` — all `/effects`, `/style-library/*`, `/font-library/*`, `/my-effects`, `/rafiei-styles`, `/effect-feedback` endpoints

**Tests:**
- `tests/test_effects_v4.py`, `tests/test_v4_full_integration.py`, `tests/test_v4_simple.py`, `tests/test_v4_real_run.py`
- `tests/test_style_library.py`, `tests/test_font_library.py`
- `tests/test_rafiei_styles.py`

### Items to verify/fix

1. **Effects V4 catalog completeness** — every entry in `EXTENDED_EFFECTS` must have a working `_build_mlt_*` function that generates valid MLT XML filters. Confirm each effect type (`camera_shake`, `freeze_frame_zoom`, `speed_ramp`, `blur_in`, `blur_out`, `vignette`, `rgb_split`, `light_leak`, `text_pop`, `emoji_pop`) produces well-formed filter XML. Confirm the legacy catalog (`EFFECT_CATALOG`) is merged correctly and every combined effect has a unique ID.

2. **Effect scoring pipeline** — `brain/effect_score_v4.py`'s `score_effects()` must correctly: (a) receive segment analysis output (role, energy, emotion), (b) match effects by `best_roles` and `mood`/`energy` compatibility, (c) respect user rules from My Effects (`presets/my_effects.yaml`), (d) return a ranked list per segment. Verify the fallback path when no segment analysis is available.

3. **Segment analysis → effect selection chain** — confirm that `brain/segment_analysis.py`'s `analyse_segments()` output schema (role, energy, emotion per segment) matches what `effect_score_v4.py` consumes. Verify the LLM prompt includes all `ROLES` and the JSON schema constraint.

4. **Style Library integrity** — verify the full lifecycle: `import_snapshots()` / `import_reference_video()` → draft creation with SHA-256 provenance → `approve_draft()` copies to profiles → `fork_profile()` creates a new version → `delete_draft()` / `delete_profile()` clean up files and index. Confirm `list_library()` returns a consistent view. Verify that the web UI (`StyleLibrary.tsx`) maps correctly to all API endpoints.

5. **Font Library integrity** — verify: `import_font()` extracts metadata via fontTools → candidate created → `approve_font()` copies to approved dir keyed by content hash → `import_image()` stores text-reference images → `delete_item()` removes files and index entries. Confirm the web UI (`FontLibrary.tsx`) maps to all API endpoints. Verify the approved font path is used by `engine/captions.py` during render.

6. **My Effects + Rafiei Styles API** — verify: `GET /my-effects` returns current rules from `presets/my_effects.yaml`, `PUT /my-effects` writes back, `GET /rafiei-styles` returns available styles, `POST /rafiei-styles/select` persists selection. Confirm the `MyEffects.tsx` UI correctly loads, displays, and saves both effect rules and style selections, including error handling for malformed YAML.

---

## Part B — Premiere ↔ AI Render Connection Issues

### Files to read

**Backend:**
- `app/premiere_desktop.py` — local macOS handoff: capability detection, `open_mode()` (5 modes), `link_project()`, `status()`, hash staleness tracking
- `app/premiere_bridge.py` — CEP bridge protocol: `create_session()`, `pair()`, `accept_receipt()`, `_classify_receipt()`, `_current_receipt()` reconnect logic, `status()`
- `engine/premiere.py` — FCP7 XML builder (`build_premiere()`), `_track()` transition boundaries, `_report()` manifest/compatibility report, native verification record writer

**Web UI:**
- `web/src/PremiereCard.tsx` — Premiere integration card: 5 open modes, bridge connect, link, download actions, polling, staleness display
- `web/src/api.ts` — `PremiereStatus` interface, all `premiere*` API methods

**CEP panel:**
- `premiere-bridge/index.html` — CEP ExtendScript host panel

**Tests:**
- `tests/test_premiere.py` — XML generation, transition mapping, manifest, verification state
- `tests/test_premiere_bridge.py` — bridge protocol, receipt validation, session lifecycle
- `tests/test_premiere_desktop.py` — desktop handoff modes, link lifecycle, hash staleness

### Items to verify/fix

7. **Desktop ↔ Bridge state inconsistency** — `premiere_desktop.status()` and `premiere_bridge.status()` both report the integration state but are called separately from different API endpoints (`/premiere/status` vs. bridge polling). Verify that: (a) `PremiereCard.tsx` merges both status responses correctly (the `bridge` field inside `PremiereStatus` comes from the bridge status endpoint), (b) there's no race condition where the bridge reports `completed` but the desktop status still says `not_linked` because `link_project()` hasn't been called, (c) the UI disables the "Connect inside Premiere" button correctly — it requires `project_state === "linked_current"` AND `final_render === "final"`, meaning you can never bridge-connect without first manually linking a `.prproj`.

8. **Bridge session expiry vs. UI polling** — bridge sessions expire after `SESSION_TTL_SECONDS` (10 min). Verify: (a) `_purge_expired()` is called on every session/pair/receipt/status operation so stale sessions can't be used, (b) `PremiereCard.tsx` stops polling when the bridge state is `completed`/`partial`/`failed`/`stale` (currently it only polls on `waiting_for_premiere` and `paired`), (c) an expired session returns a clear error (not a generic 500), (d) the pairing code display is cleared after expiry or final receipt.

9. **Receipt hash binding enforcement** — `accept_receipt()` validates that `receipt.artifact_identity` matches the command's `artifact_identity`. Verify: (a) if the user re-renders or re-plans between `create_session()` and the receipt, the receipt is correctly rejected with 409 because the hashes no longer match the session's command, (b) the `_current_receipt()` reconnect logic correctly skips importing items already in the receipt (sequence, render reference, captions) by checking the `requested_actions` flags, (c) the test `test_premiere_bridge.py` covers the hash-mismatch rejection path.

10. **Premiere XML ↔ plan.json drift** — `premiere_desktop.current_identity()` regenerates the Premiere package (`build_premiere()`) and compares plan/xml/srt hashes. Verify: (a) when a user edits captions in Plan Review and saves, the SRT hash changes and `status()` reports `editable_plan: "stale"` until regeneration, (b) `link_project()` always calls `current_identity(regenerate=True)` so it binds the link to the latest artifacts, (c) the `changed_hashes` field in the status response correctly identifies WHICH artifacts changed (plan vs. xml vs. srt vs. render), not just that something changed.

11. **`open_mode()` edge cases** — the 5 modes (`editable_plan`, `rendered_video`, `plan_and_render`, `saved_project`, `reveal`) have complex branching. Verify: (a) `plan_and_render` with `linked_outdated` state returns `refresh_required` and does NOT open Premiere (only reveals in Finder), (b) `rendered_video` with a linked_current project opens the `.prproj`, NOT the bare MP4 — it tells the user to find the render inside the project's AI Render bin, (c) `saved_project` without a link returns 404 (not a confusing fallback), (d) `confirm_preview` is required before sending a preview-only render to Premiere, (e) the `require_local()` guard blocks all modes when the request doesn't come from localhost.

12. **Premiere native verification gap** — `docs/premiere-format.md` lists several items as `unverified`: boundary zoom import, Persian SRT import/save/reopen, effect mappings, fresh-job sequences, relink workflow. Verify: (a) the manifest (`_report()`) correctly classifies these as `unverified` in both `capability_classification` and `current_artifact_verification`, (b) the `overall_result` stays `awaiting_current_artifact_verification` until ALL required observations are present, (c) `PremiereCard.tsx` displays warnings from the manifest to the user before download, (d) the native verification record writer (`write_native_verification_record()`) validates the operator observations schema and rejects incomplete records.

---

Run all tests. Report each item (1–12) as ✅ correct or 🔧 fixed (with what changed).
