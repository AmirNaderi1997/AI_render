# Fixiation Prompt 8: Premiere Pro Direct-Open Flow — Runtime Restoration, Kdenlive Demotion, and Bridge Automation Gaps

Read every file listed below, then **fix** anything broken and **verify** every claim. Run all tests to confirm green before and after any changes.

---

## Part A — Runtime & Environment Restoration

### Files to read

- `.venv/pyvenv.cfg` — current venv config (points to removed Python 3.14)
- `requirements.txt` — project dependencies
- `README.md` — setup instructions mentioning `brew install ffmpeg mlt`
- `docs/stages.md` — stage 0 setup instructions
- `docs/prompt-stage1.md` — mentions `brew install ffmpeg mlt`

### Items to verify/fix

1. **Broken Python venv** — `.venv/pyvenv.cfg` points to `/opt/homebrew/opt/python@3.14/bin/python3.14` which no longer exists on the system. Only `/usr/bin/python3` (3.10.12) remains. Every script in `.venv/bin/` has a dead shebang. Fix: delete the broken `.venv` and recreate it with the available Python (`python3 -m venv .venv`), then `pip install -r requirements.txt`. If Python 3.10 causes compatibility issues with any dependency (check `requires-python` in each package), document the minimum Python version needed and add it to `requirements.txt` or `pyproject.toml`. The project docs say "Python 3.11+"; if 3.10 is too old, document that and add a version check to `app/main.py` startup.

2. **melt (MLT framework) not installed** — `which melt` returns nothing. The render engine (`engine/render.py`) calls `melt` to convert MLT XML → MP4. Without it, no render can complete, which means no final render exists for the Premiere `rendered_video` or `plan_and_render` open modes. Fix: install `mlt` via Homebrew (`brew install mlt`) or, if Homebrew itself needs reinstalling, document that. After installing, verify `melt --version` works and that `engine/render.py`'s subprocess call matches the installed binary name and path.

3. **Homebrew health** — `/opt/homebrew/bin/` appears empty or missing common tools. Verify Homebrew is functional (`brew --version`, `brew doctor`). If Homebrew needs reinstallation, document the steps but do not reinstall without user confirmation. If Homebrew is working but python@3.14 was simply uninstalled, that's fine — just confirm the venv rebuild in item 1 uses whatever Python IS available.

4. **Startup smoke test** — after fixing items 1–3, verify the backend actually starts: `cd /path/to/AI_render && source .venv/bin/activate && uvicorn app.main:app --host 127.0.0.1 --port 8000`. Confirm: (a) the server starts without import errors, (b) `GET /jobs` returns a valid response (it should list existing jobs including `7d8424669e18`), (c) `GET /jobs/7d8424669e18/premiere/status` returns a valid status object. If any import fails due to missing system libraries (e.g., `faster-whisper` needs specific native libs), document the fix.

---

## Part B — Kdenlive Demotion: Premiere Is Primary

### Files to read

- `engine/kdenlive.py` — Kdenlive project writer
- `app/main.py` — the `/jobs/{job_id}/open-kdenlive` endpoint (lines ~671–680)
- `web/src/api.ts` — `openKdenlive()` method (line ~273)
- `web/src/Render.tsx` — render page (check for Kdenlive buttons)
- `web/src/PlanReview.tsx` — plan review page (check for Kdenlive buttons)
- `web/src/PremiereCard.tsx` — Premiere UI card
- `docs/stages.md` — stage 0 mentions "نصب Kdenlive از kdenlive.org"

### Items to verify/fix

5. **Remove Kdenlive from the UI** — the user stated "core render app is Premiere Pro not Kdenlive." The `api.ts` still has `openKdenlive()` (line 273) and `app/main.py` still has `POST /jobs/{job_id}/open-kdenlive` (line 671). Verify whether any frontend component actually renders a "Open in Kdenlive" button. If so, remove it. The backend endpoint and `engine/kdenlive.py` can remain as fallback infrastructure, but the UI should present **only** Premiere Pro as the editor integration. Add a comment to the Kdenlive endpoint: `# Legacy fallback — UI uses Premiere; kept for CLI/API compatibility`.

6. **Docs and setup instructions** — `docs/stages.md` lists "نصب Kdenlive از kdenlive.org" as a setup step. Update all documentation to reflect that Premiere Pro is the primary editor. Kdenlive can be mentioned as an optional/legacy alternative, not a required install. `README.md` says `brew install ffmpeg mlt` — mlt is still needed for rendering, so that stays; just ensure Premiere is mentioned as the editing target.

---

## Part C — Premiere Direct-Open: Automation Gaps

### Files to read

- `app/premiere_desktop.py` — `open_mode()` (all 5 modes), `status()`, `link_project()`
- `app/premiere_bridge.py` — `create_session()`, `pair()`, `accept_receipt()`, `execute()` command builder
- `premiere-bridge/jsx/bridge.jsx` — ExtendScript: `importOne()`, `findSequences()`, caption/render placement
- `premiere-bridge/js/panel.js` — CEP panel: pair → execute → receipt flow
- `web/src/PremiereCard.tsx` — UI that drives the open/bridge/link flow
- `jobs/7d8424669e18/premiere_bridge_receipt.json` — real receipt showing what DID and DIDN'T work

### Items to verify/fix

7. **"Open directly in Premiere" requires too many manual steps** — When a job has no linked `.prproj` yet, `open_mode('editable_plan')` returns `setup_required` with a message telling the user to manually: (a) create a new Premiere project, (b) import the XML, (c) import the render MP4, (d) import the SRT as captions, (e) save with exact filename `ai-render-{job_id}-clean.prproj`, (f) come back and click Link. This is 6 manual steps before the bridge can even start. Verify: (a) the `setup_required` message text is clear and accurate (it currently mentions all required files), (b) the `PremiereCard.tsx` renders this message and guides the user step-by-step (not just dumps a paragraph), (c) consider adding a numbered step list in the response JSON (e.g., `steps: [...]`) so the UI can render a checklist.

8. **Bridge does NOT place captions or render reference** — the real receipt from job `7d8424669e18` shows `captions.placed: false`, `captions.track_created: false`, and `render_reference.placed_on_editable_timeline: false`. The bridge successfully imports these files into the project bin but does NOT place them on the timeline. This means even after the bridge completes, the user still has to manually drag captions onto a caption track and place the render reference on the timeline. Investigate `premiere-bridge/jsx/bridge.jsx` — does the `execute()` command include `place_captions` and `place_render_reference` actions? If these actions exist but fail silently in ExtendScript, add error reporting. If they don't exist yet, document this as a known gap and add a TODO in the bridge receipt classifier to distinguish "imported but not placed" from "fully placed."

9. **Bridge receipt classification accuracy** — `premiere_bridge.py`'s `_classify_receipt()` determines whether the bridge result is `completed`, `partial`, or `failed`. With captions not placed and render not placed on timeline, the receipt should classify as `partial` — NOT `completed`. Verify: (a) what does `_classify_receipt()` consider "completed"? Is it just imports, or does it require placement? (b) If it considers imports-only as "completed," fix the classification: `completed` should mean all requested actions succeeded including placement. (c) Update the test `test_premiere_bridge.py` to cover the "imported but not placed" scenario as `partial`.

10. **Link flow requires exact filename but UI doesn't explain how to save** — `link_project()` requires the filename to be exactly `ai-render-{job_id}-clean.prproj`. The `open_mode()` message tells the user this, but: (a) verify the `PremiereCard.tsx` shows the exact expected filename prominently (not buried in a paragraph), (b) verify `link_project()` returns a helpful error if the filename is wrong (currently returns 422 with the expected name — confirm the UI displays this), (c) consider auto-detecting `.prproj` files in the job directory and suggesting a link if one matches the pattern, rather than requiring the user to come back and click Link.

11. **One-click Premiere open for linked projects** — when a project IS already linked and current (`project_state === 'linked_current'`), `open_mode('editable_plan')` should open Premiere with one click and no manual steps. Verify this golden path: (a) `_run('-b', cap['bundle_id'], str(linked))` correctly sends the project to Premiere via `open -b`, (b) the response status is `launch_requested` (not `setup_required`), (c) `PremiereCard.tsx` shows success feedback immediately (not the setup checklist), (d) if Premiere is not installed (`cap['available'] == False`), the error message is clear and suggests downloading the XML instead.

12. **Stale link detection and recovery** — when the plan or captions change after linking (e.g., user edits subtitles in Plan Review), the link becomes stale. Verify: (a) `status()` correctly detects staleness by comparing current hashes to the link's stored hashes, (b) the `changed_hashes` field in the status response correctly identifies WHICH artifact changed (plan vs. xml vs. srt vs. render), (c) `PremiereCard.tsx` shows a clear "Your Premiere project is outdated" warning with the specific changed items, (d) the `refresh_required` flow in `open_mode('plan_and_render')` reveals the updated files in Finder WITHOUT opening Premiere (so the user can manually re-import), (e) after the user updates and saves in Premiere, re-linking via `link_project()` succeeds and clears the stale state.

---

## Part D — End-to-End Verification

### Items to verify

13. **Full approve → Premiere chain test** — with the backend running (after Part A fixes), execute the complete flow for job `7d8424669e18`: (a) `GET /jobs/7d8424669e18/premiere/status` returns a valid state, (b) if the link is current, `POST /jobs/7d8424669e18/premiere/open` with `mode: "editable_plan"` returns `launch_requested`, (c) if the link is stale, it returns the correct `refresh_required` or `setup_required` state. Don't actually open Premiere (the test environment may not have it), but verify all the server-side logic executes without error.

14. **PremiereCard.tsx state machine correctness** — the UI card has multiple states: no capability, not linked, linked current, linked stale, bridge waiting, bridge paired, bridge completed/partial/failed. Walk through each state in `PremiereCard.tsx` and verify: (a) every state shows the correct buttons (Open, Connect, Link, Download), (b) disabled states are correct (e.g., "Connect inside Premiere" requires linked + final render), (c) polling starts/stops at the right moments (only during `waiting_for_premiere` and `paired`), (d) error messages from the backend are displayed to the user, not swallowed.

---

Run all tests. Report each item (1–14) as ✅ correct, 🔧 fixed (with what changed), or ⚠️ blocked (with why).
