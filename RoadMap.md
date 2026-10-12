# AI Render roadmap and VPS release gates

The feature history is in [docs/stages.md](docs/stages.md) and [plan.md](plan.md). The infrastructure outline is [docs/VPS_PRODUCTION_PLAN.md](docs/VPS_PRODUCTION_PLAN.md). Reconcile those plans with the current code and [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md) before treating any stage as complete.

## Planning and building sequence

1. State the user outcome, affected layers, dependencies, and acceptance evidence. Use the template in [Prompts/README.md](Prompts/README.md).
2. Build the smallest complete cross-layer change. Update the relevant API, UI, storage, worker, and Compose pieces when the feature needs them.
3. Verify with focused tests, build/config checks, and a real browser or media workflow for user-visible behavior. Record exact results and limitations in the scoped plan or task report.
4. Update the release evidence and unresolved items in [PRODUCTION_CHECKLIST.md](PRODUCTION_CHECKLIST.md). Only then prepare a VPS handoff under [GuideLine.md](GuideLine.md).

## VPS gate status

| Gate | Required evidence | Current status |
| --- | --- | --- |
| Release scope | Named revision, changed components, migrations, owner, rollback target | Needs review for each release |
| Configuration and TLS | VPS `.env`, DNS, trusted certificate, exact hosts, no secrets in Git | Not proven on VPS in this repository |
| Data safety | Restorable PostgreSQL backup, migration review, storage durability | Not proven on VPS in this repository |
| Runtime | Compose services, DB/Redis/worker readiness, HTTPS, logs | Not proven on VPS in this repository |
| User acceptance | Real login, upload, render, export, Hermes flow as applicable in browser | Not proven on VPS in this repository |
| Hermes credential entry | Users enter App ID, App Secret, Access Token, and Instagram User ID in Hermes; no Instagram credential environment fallback | Implemented in source on 2026-10-12; local API tests passed; VPS/browser acceptance pending |

## 2026-10-12: Self-contained video poster and Hermes credential entry

- Goal: downloaded MP4s show the chosen poster before playback; each user enters all Instagram credentials in Hermes settings rather than server environment variables.
- Affected layers: MLT/FFmpeg export and job worker; Hermes API, encrypted settings storage, and frontend form; `.env` and VPS guidance. The existing sidecar JPEG remains for job thumbnails and HTML video poster display, while the MP4 carries its own opening frame and attached cover art.
- Acceptance evidence: focused Hermes tests, real FFmpeg frame/stream test, offline API-to-render test, frontend build, and Render page tests passed locally on 2026-10-12. No live Instagram provider or VPS browser workflow was exercised.
- Deployment impact: no schema migration; rebuild app, worker, Hermes, and frontend images. Existing MP4 exports require re-rendering to gain embedded posters. Keep `HERMES_TOKEN_KEY` stable for encrypted data; `INSTAGRAM_REDIRECT_URI` remains server configuration. Users with earlier saved Hermes settings must re-enter all four fields, including App ID.
- Remaining gate: verify downloaded MP4 in QuickTime and a second player, and verify Hermes settings in an authenticated browser against the deployed stack before announcing release readiness.

## 2026-10-12: Rate poster titles for every generated plan

- Goal: new uploaded-video plans and Content Creator reel, story, and post plans choose their poster title from available captions with the same rating system. The caption text is preserved, including the example selection «سرمایه اولیه اصولا نمی‌خواد».
- Affected layers: hosted and local fallback planning, Content Creator plan assembly, and poster metadata consumed by the existing render/export path. No API, database schema, frontend, or Compose contract changes.
- Acceptance evidence: focused brain, provider, and Content Creator run passed locally (97 tests, 15 unrelated media tests deselected); `scripts/check_vps_handoff.py` passed. The logged-in local browser showed job `1d4e7a5585de` with poster text «سرمایه اولیه اصولا نمی‌خواد», score 72, and matching caption 12. The broader Content Creator/transcription run had FFmpeg and transcription fixture failures in this checkout; it does not establish a full-suite pass.
- Deployment impact: rebuild app and worker images to use the planner change. Existing saved plans are not automatically rewritten; the render path refreshes posters with an older rating version. A fresh generated plan, render, downloaded MP4, and browser preview on the target stack remain to be checked before VPS handoff.

Do not infer deployment readiness from the presence of these documents or from a local build. Update this table only with dated, specific evidence.
