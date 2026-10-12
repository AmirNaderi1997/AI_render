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

## 2026-10-12: Global portrait render quality baseline

- Goal: new portrait videos inherit the reference reel's readable persistent hook, stable short captions, and clear speech level. The supplied 48.13-second reference is 1080×1920 at 30 fps and measured −14.3 LUFS with −0.8 dBFS true peak; a prior project export measured −20.4 LUFS.
- Affected layers: shared poster planning/schema, MLT caption composition and preset, FFmpeg render and CLI defaults, post-render music mix, persisted job status, render and plan UI, app and Celery worker images, and frontend bundle. No database migration; existing job records accept the additive QC fields.
- Acceptance: inspect a fresh full-size MLT/FFmpeg output and its standalone poster; verify an opted-out plan omits the hook; check FFprobe dimensions, frame rate and duration plus EBU R128 loudness and true peak; pass focused render/music tests and frontend build; inspect the changed UI in a local browser after Compose rebuild.
- Local evidence: a six-second full-size render of the supplied reference as source produced a visible white/yellow persistent hook and a separate poster without the new hook doubled. It measured −15.4 LUFS and −2.9 dBFS true peak after normalization; a post-render music mix measured −15.2 LUFS and −3.1 dBFS true peak. The source already had burned captions, so this is a compositing and audio check. A separate authenticated local browser render of clean talking-head source produced a 26.13-second 1080×1920/30 fps export at −14.6 LUFS and −1.4 dBFS true peak with no technical QC warnings. Its inspected frames showed the persistent hook and changing speech captions. A preview also completed at 540×960 with −14.6 LUFS and no technical QC warnings. The later smaller-caption and enlarged-hook preset was inspected in a fresh MLT frame but is not represented in the full export. Local app and worker images were rebuilt and recreated; readiness passed for database, Redis, Celery, disk, and ffmpeg.
- Deployment impact: rebuild app, Celery worker, and frontend locally; re-render older exports to gain the new on-video hook or normalization. Preserve pinned styles and the editor's hook and normalization opt-outs. VPS deployment still requires the gates in `GuideLine.md`.

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
- Local deployment evidence: the clean `main` checkout was fast-forwarded to `74a633e` on 2026-10-12. The `ai_render` Compose project rebuilt app, worker, Hermes, frontend, and nginx images; app, worker, and Hermes containers were recreated. The running app container returned «سرمایه اولیه اصولا نمی‌خواد» with rating version 2 from both local fallback and Content Creator sample plans. Public `/healthz` and `/api/health/ready` returned HTTP 200; readiness passed database, Redis, Celery, disk, and FFmpeg. The refreshed logged-in browser showed the existing job's rated poster text and a valid plan.
- 2026-10-12 follow-up: a newly generated local job `f02d4ccd2b4c` rated caption 12 as «سرمایه اولیه اصولاً نمی‌خواد». Its full 1080x1920 render completed; the downloaded `v1.mp4` matched the server file by SHA-256, and its decoded first frame visibly contained that sentence. FFprobe found the H.264 video, AAC audio, and attached MJPEG artwork. The refreshed authenticated browser showed the title in the paused video at 0:00 with no HTML `poster` image attribute. The Render page now uses the MP4 opening frame for preplay, and Plan Review labels the rated sentence as the preplay video title. `web/src/Render.test.tsx` passed (15 tests), and the frontend production build passed before deployment of the updated bundle.
- Deployment impact: no migration. Existing saved plans are not automatically rewritten; the render path refreshes posters with an older rating version. This local browser and MP4 verification does not establish VPS readiness or native QuickTime playback.

Do not infer deployment readiness from the presence of these documents or from a local build. Update this table only with dated, specific evidence.
