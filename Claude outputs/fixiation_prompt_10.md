# Fixiation Prompt 10: Premiere Pro Bridge — Caption Placement, Setup Automation, Receipt Accuracy, and Link Recovery

Read every file listed below, then **fix** anything broken and **verify** every claim. Run all tests to confirm green before and after any changes.

---

## Part A — Bridge Caption Placement (the #1 broken feature)

### Files to read

- `premiere-bridge/jsx/bridge.jsx` — lines 149–161: caption import + `createCaptionTrack` call
- `app/premiere_bridge.py` — lines 197–218: `create_session()` command builder, `requested_actions.place_captions`
- `app/premiere_bridge.py` — lines 100–130: `_classify_receipt()` caption requirements
- `tests/test_premiere_bridge.py` — lines 220–257: caption persistence and unobservable tests

### Items to verify/fix

1. **`createCaptionTrack` returns falsy in practice** — In `bridge.jsx` line 155, the call `sequences[0].createCaptionTrack(captionResult.item, 0)` is the only caption placement attempt. In the real receipt from job `7d8424669e18`, `captions.track_created: false` and `captions.placed: false`. The SRT gets imported to the bin (`captions.imported: true`) but never lands on the timeline. Investigate why `createCaptionTrack` fails:
   - (a) Does Premiere 25.3's ExtendScript actually support `Sequence.createCaptionTrack(ProjectItem, trackIndex)`? Check the Premiere ExtendScript API docs. If the method signature is wrong (e.g., it takes different parameters, or the SRT needs to be imported differently for captions), fix it.
   - (b) If `createCaptionTrack` is not available or unreliable in CEP, implement an alternative: use `app.project.importFiles` with `importAsNumberedStills=false` targeting the sequence directly, or use the Caption API (`sequence.captionTracks` / `addCaptionTrack`).
   - (c) Add a try/catch around the `createCaptionTrack` call in `bridge.jsx` so that if it throws, the error message is captured in `receipt.errors` instead of silently returning false.
   - (d) If no programmatic caption placement works in CEP, document this as a Premiere CEP limitation and change the bridge flow: after importing the SRT to the bin, add a `receipt.warnings` entry explaining that the user must drag the SRT onto the caption track manually. Update `_classify_receipt` to treat this as `partial` (not `failed`) when caption import succeeded but placement is a known CEP limitation.

2. **Caption placement error not reaching the receipt in some cases** — In `bridge.jsx` lines 155–157, when `createCaptionTrack` returns falsy, `receipt.errors.push("Premiere could not create the caption track.")` should fire. But if the real receipt had no such error string, that means either: (a) `place_captions` was `false` in the command (so it went to the `else` branch at line 159 and added a warning instead), or (b) `captionResult.item` was null (so the different error at line 153 fired). Check the actual receipt JSON at `jobs/7d8424669e18/premiere_bridge_receipt.json` and trace which branch executed. If `place_captions` was unexpectedly `false`, trace back to `create_session()` in `premiere_bridge.py` lines 213–218 to see if a stale previous receipt suppressed it.

3. **`place_captions` logic in `create_session` is too conservative** — In `premiere_bridge.py` lines 213–218, `place_captions` is set to `False` when a previous receipt had `track_created=True AND placed=True`, OR when `caption_state_unobservable` is true (previous warning contained "cannot inspect existing caption tracks"). This means after ONE failed attempt that produces a warning about unobservable captions, all future reconnects will skip placement entirely. Fix: only suppress `place_captions` when the previous receipt's caption placement was actually successful (`track_created=True AND placed=True`), never when it was unobservable. The `caption_state_unobservable` check should only suppress placement when combined with `verify_saved_captions` confirming the captions ARE actually in the project file.

---

## Part B — First-Time Setup Reduction (6 manual steps → fewer)

### Files to read

- `app/premiere_desktop.py` — lines 195–245: `open_mode()` for `editable_plan` and `plan_and_render` when `project_state != 'linked_current'`
- `web/src/PremiereCard.tsx` — lines 67–71: `not_linked` setup instructions, lines 85–94: button states
- `app/premiere_desktop.py` — lines 248–270: `link_project()` exact filename requirement

### Items to verify/fix

4. **Auto-detect `.prproj` files for linking** — Currently `link_project()` requires the user to manually click "Link clean Premiere project" after saving with the exact filename `ai-render-{job_id}-clean.prproj`. Add an auto-detection step: in `status()`, scan `job.dir` for files matching `ai-render-{job.id}*.prproj` (excluding symlinks). If exactly one match exists and it's `ai-render-{job_id}-clean.prproj`, include `"auto_linkable": true, "auto_linkable_project": filename` in the status response. The UI can then show a one-click "Link detected project" button instead of requiring the user to know the exact filename.

5. **Steps list already exists but UI rendering can improve** — `open_mode()` already returns a `steps` array (line 203–208 of `premiere_desktop.py`). `PremiereCard.tsx` line 96 renders it as `<ol>`. Verify: (a) the steps text is clear and actionable (not a wall of text), (b) each step has enough context (file names are bold or code-formatted), (c) the steps list appears immediately when `project_state === "not_linked"` (lines 67–71 already show static instructions). Currently there are TWO sets of instructions — static ones at lines 67–71 and dynamic ones from `open_mode` response at line 96. Consolidate: remove the static instructions block at lines 67–71 and rely only on the `steps` array from the backend response, OR make the static block match the backend exactly so there's no inconsistency.

6. **`open_mode` returns both `message` AND `steps` but UI shows only one** — `PremiereCard.tsx` line 97: `{message && !steps && <p ...>{message}</p>}` — the message is hidden when steps are present. But the `message` from `open_mode` contains important context (like the exact save-as filename). Fix: show both — the steps as a numbered list AND the message as a summary paragraph below.

---

## Part C — Receipt Classification Accuracy

### Files to read

- `app/premiere_bridge.py` — lines 100–130: `_classify_receipt()`
- `app/premiere_bridge.py` — lines 75–97: `verify_saved_captions()`
- `tests/test_premiere_bridge.py` — lines 177–199: parametrized required observations test, lines 260–268: render reference on timeline test

### Items to verify/fix

7. **"completed" requires all 8 observations true** — `_classify_receipt` checks 8 `required` fields (lines 105–113). If ANY is false and there are no warnings, state is `"failed"`. If there are warnings, state is `"partial"`. Verify this is correct behavior: a receipt with `captions.placed: false` and zero warnings should be `"failed"`, not `"partial"`. The test at line 189–199 confirms each false observation → `"failed"`. This is correct. But verify: when `persisted=True` (caption persistence verified from saved project), `captions.track_created` and `captions.placed` are overridden to `True` at lines 111–112. This means if `verify_saved_captions` returns `verified=True`, the receipt can be `"completed"` even though the bridge never actually placed captions. Verify this is the intended behavior and document it clearly.

8. **`verify_saved_captions` regex parsing is fragile** — At line 81, `re.findall(r"<CaptionDataClipTrack[ >]", xml)` parses the .prproj XML (which may be gzipped) with regex. This could false-positive on comments or attribute values containing that string. It also counts `CaptionDataClipTrackItem` occurrences and compares to SRT cue count. Verify: (a) the regex matches the actual Premiere 25.3 prproj XML structure, (b) the SRT cue splitting at line 79 (`re.split(r"\n\s*\n", ...)`) correctly handles Windows line endings (`\r\n`), (c) add a test that creates a realistic gzipped prproj with caption data and verifies the count.

9. **`render_reference.placed_on_editable_timeline` invariant** — At line 115, `invariant_failure = observed.render_reference.placed_on_editable_timeline is not False`. This means if the render IS on the timeline, the receipt is `"failed"`. This is by design (the render is reference-only, should NOT be on the edit timeline). But in `bridge.jsx` lines 144–147, the check just observes whether the render media appears on the timeline — it doesn't prevent it. If a user manually dragged the render onto the timeline before running the bridge, the receipt would fail. Add a warning in this case explaining WHY it failed ("Remove the rendered reference from the editable timeline — it is a visual reference only, not an edit source").

---

## Part D — Link Flow Robustness

### Files to read

- `app/premiere_desktop.py` — lines 135–155: `read_link()` allowed filenames
- `app/premiere_desktop.py` — lines 155–185: `status()` project state detection
- `app/premiere_desktop.py` — lines 185–245: `open_mode()` stale link handling
- `web/src/PremiereCard.tsx` — lines 72–76: `linked_outdated` display

### Items to verify/fix

10. **`read_link()` accepts two filenames but `link_project()` only accepts one** — In `read_link()` (line 143–144), `allowed` includes both `ai-render-{job.id}.prproj` and `ai-render-{job.id}-clean.prproj`. But `link_project()` (line 260) only accepts `*-clean.prproj`. This means: if a user somehow created a link record pointing to `ai-render-{job.id}.prproj` (without `-clean`), `read_link()` would find it valid but `link_project()` would refuse to relink it. Either remove the non-clean filename from `read_link()`'s `allowed` set, or accept both in `link_project()`. The cleaner fix is to remove `ai-render-{job.id}.prproj` from `read_link()` so only `-clean` projects are ever valid links.

11. **Stale link recovery requires too many manual steps** — When `project_state === "linked_outdated"`, `open_mode('plan_and_render')` returns `refresh_required` and reveals files in Finder (line 225). The user must then: (a) open Premiere, (b) re-import changed files, (c) save the project, (d) come back and relink. Consider adding a bridge-driven update flow: when the link is stale, allow `create_session()` to proceed anyway (currently it checks `project_state == "linked_current"` at `_linked_project()` line 234 of `premiere_bridge.py`). The bridge could then re-import the updated XML/SRT/render into the existing project, replacing the old versions. This would make stale recovery a one-click operation instead of 4 manual steps.

12. **`_linked_project()` in `premiere_bridge.py` blocks bridge for stale links** — At line 234, `_linked_project()` raises HTTP 409 if `project_state != "linked_current"`. This means the bridge cannot be used to UPDATE a stale project — only to set up a current one. This is the root cause of the manual recovery flow. Fix: add a `force_refresh` parameter to `create_session()` that skips the staleness check and builds a command that re-imports all artifacts (setting all `import_*` actions to `True` regardless of previous receipt).

13. **`changed_hashes` display in PremiereCard is too technical** — At line 74, `PremiereCard.tsx` shows raw SHA-256 hash comparisons: `"linked abc123... → current def456..."`. Users cannot interpret hash diffs. Change the display to show WHICH artifacts changed in plain language: "Edit plan changed", "Captions updated", "New render available" — derived from which hash keys differ (`plan_sha256` → "Edit plan", `xml_sha256` → "Premiere XML", `srt_sha256` → "Captions", `render_sha256` → "Rendered video").

---

## Part E — CEP Panel Hardening

### Files to read

- `premiere-bridge/js/panel.js` — full file (70 lines)
- `premiere-bridge/CSXS/manifest.xml` — extension manifest

### Items to verify/fix

14. **Hardcoded API URL `http://127.0.0.1:8000`** — `panel.js` line 3 hardcodes the backend URL. If the user runs the backend on a different port, the CEP panel silently fails. Fix: check if the port can be configurable via a text field in the panel UI, or read it from a config file in the extension directory, or at minimum add a comment documenting how to change it.

15. **No timeout on XHR requests** — `panel.js` uses raw XMLHttpRequest with no timeout. If the backend is down or slow, the panel hangs indefinitely with "Pairing with AI Render…" or "Paired. Applying the AI Render job inside Premiere…" and the button stays disabled. Fix: add `xhr.timeout = 30000` (30 seconds) and `xhr.ontimeout` handler that re-enables the button and shows a timeout error.

16. **No execution progress feedback** — After pairing, the panel shows "Paired. Applying the AI Render job inside Premiere…" and waits for the entire `bridge.execute()` to finish. For large projects with many segments, this could take seconds. Add intermediate status updates: "Importing sequence…", "Importing render reference…", "Placing captions…", "Saving project…". This requires splitting `bridge.execute` in `bridge.jsx` into steps with callbacks, or at minimum showing elapsed time.

17. **Panel doesn't show receipt details on completion** — At line 62–65, the panel shows `accepted.state` and either errors or warnings or a generic success message. It doesn't show what was actually imported/placed. Add receipt summary: "Sequence: imported ✓, Render: imported ✓, Captions: placed ✗ (manual placement needed)".

---

## Part F — FCP7 XML and SRT Quality

### Files to read

- `engine/premiere.py` — lines 247–260: `_transition_effect()` (all transitions → Cross Dissolve)
- `engine/premiere.py` — lines 284–291: `_write_srt()` caption SRT generation
- `engine/premiere.py` — lines 399–637: `_report()` compatibility report generation

### Items to verify/fix

18. **All non-cut transitions become Cross Dissolve** — `_transition_effect()` hardcodes Cross Dissolve for all transition types. This is documented in the report but limits editability. Verify: (a) the compatibility report at lines 422–430 correctly classifies `directional` as `editable_fallback` and `zoom` as `unverified`, (b) the report `warnings` list includes a clear message about this fallback, (c) the `PlanReview.tsx` compatibility display (if it exists) shows this information to the user BEFORE they open in Premiere.

19. **SRT caption timing uses output time but bridge imports against sequence** — `_write_srt()` writes captions with output-time coordinates (after cuts and transition overlaps). When this SRT is imported as a caption track on the XML sequence, the timings should align because the XML sequence also uses output time. Verify: (a) caption start/end in the SRT match the output timeline positions in the XML sequence, (b) transition overlap retiming doesn't create misalignment between caption timing and clip timing, (c) if there ARE misalignments, document them in the compatibility report.

20. **SRT has no RTL/Persian handling** — `_write_srt()` writes raw `caption.text` with no RTL markers or Unicode bidirectional overrides. For Persian text, Premiere's SRT import may display text with incorrect directionality. Check if adding Unicode RLM (Right-to-Left Mark, U+200F) or RLE/PDF markers improves display in Premiere's caption panel.

---

## Part G — PremiereCard UI Polish

### Files to read

- `web/src/PremiereCard.tsx` — full file
- `web/src/api.ts` — lines 21–40: `PremiereStatus` interface, lines 273–297: Premiere API methods

### Items to verify/fix

21. **Button labels are confusing** — The card has 7 buttons (lines 86–94). "Open editable plan in Premiere" vs "Open linked project (handoff only)" vs "Open linked Premiere project" vs "Set up Premiere project manually" — users cannot tell the difference. Simplify: (a) merge "Open editable plan" and "Open linked project" into one primary button whose label changes based on state, (b) make "Connect inside Premiere" the prominent action when a linked current project exists, (c) use tooltips or small descriptions under each button explaining what it does.

22. **"Connect inside Premiere" requires linked + final render** — Button at line 86 is disabled unless `project_state === "linked_current"` AND `final_render === "final"`. But the bridge session (`create_session`) also requires these. Verify the button's disabled logic exactly mirrors `create_session()`'s preconditions. If they diverge, the user could click the button and get an error that the button should have prevented.

23. **Bridge polling stops on wrong states** — At lines 13–16, polling runs only when `state.bridge.state` is `"waiting_for_premiere"` or `"paired"`. But `state.bridge` comes from `premiere_bridge.status()`, which returns `state: "not_connected"` when no active session exists. After `connectBridge()` creates a session, the component calls `refresh()` but the bridge state might not immediately update. Verify: is there a race where the polling doesn't start because the state hasn't changed yet? Add a fallback: if `pairingCode` is set (line 81), keep polling regardless of bridge state.

24. **No link between PremiereCard and PlanReview compatibility section** — `PlanReview.tsx` has a "Premiere compatibility report" section that shows transition/effect/caption verification details. But `PremiereCard.tsx` (used in `Render.tsx`) doesn't link to it or show a summary. Add a link or summary in PremiereCard showing "X of Y transitions editable, captions: sidecar (manual import)" so the user knows what to expect before connecting.

---

## Part H — Test Coverage for Bridge Automation

### Files to read

- `tests/test_premiere_bridge.py` — full file
- `tests/test_premiere_desktop.py` — full file
- `tests/test_premiere.py` — verify what's covered

### Items to verify/fix

25. **Add test for caption placement failure → `partial` classification** — Currently `test_warning_can_classify_unobservable_reconnect_as_partial` tests the case where captions are unobservable. Add a test where `place_captions` was `True` in the command, `captions.imported` is `True`, but `captions.track_created` is `False` and `captions.placed` is `False`, with an error message "Premiere could not create the caption track." — verify this classifies as `"failed"` (not `"partial"`), since there are errors.

26. **Add test for stale link blocking bridge session** — Test that `create_session()` raises HTTP 409 when the linked project is stale (`project_state == "linked_outdated"`). Then test that after relinking (calling `link_project` again after the user re-saves), `create_session()` succeeds.

27. **Add test for `place_captions` suppression after unobservable warning** — Create a scenario: first bridge session produces a receipt with `captions.track_created: false, placed: false` and warning "CEP cannot inspect existing caption tracks". Then create a second session and verify whether `place_captions` is correctly set. Current code at line 216 would set it to `False` (suppressed) — verify this is the desired behavior and add a test either way.

28. **Add test for `verify_saved_captions` with realistic gzipped prproj** — Create a test that writes a gzipped XML file containing realistic `<CaptionDataClipTrack>` and `<CaptionDataClipTrackItem>` elements matching the SRT cue count, and verify `verify_saved_captions` returns `verified: True`. Also test the mismatch case (wrong item count).

---

## Part I — Cross-Cutting Integration

### Items to verify/fix

29. **Bridge session TTL vs real-world Premiere execution time** — `SESSION_TTL_SECONDS = 10 * 60` (10 minutes) in `premiere_bridge.py` line 15. After the user copies the pairing code, they must switch to Premiere, open the extension panel, enter the code, and wait for execution. For a complex project this could take several minutes. Verify 10 minutes is sufficient. Consider extending to 15 or 20 minutes, or making it configurable.

30. **CORS allows `null` origin** — `test_premiere_bridge.py` line 361 verifies that origin `"null"` is allowed. CEP panels send `Origin: null` because they run from local files. But `null` origin also comes from sandboxed iframes and certain redirect scenarios. Verify this doesn't open a CSRF vector: the `require_loopback_peer()` check in `premiere_bridge.py` line 301 restricts to localhost peers, which mitigates most CSRF, but verify the combination of `null` origin + localhost peer is safe.

31. **End-to-end flow has no single-command test** — There is no test that simulates the complete flow: create job → generate plan → render → build premiere package → link project → create bridge session → pair → execute → accept receipt → verify status. Add an integration test (can mock the ExtendScript execution) that exercises this entire chain and verifies the final state is `"completed"`.

---

Run all tests. Report each item (1–31) as ✅ correct, 🔧 fixed (with what changed), or ⚠️ blocked (with why).
