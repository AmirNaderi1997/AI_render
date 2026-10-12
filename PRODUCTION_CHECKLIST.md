# Production readiness checklist — 2026-10-09

## 2026-10-12 release delta

The global portrait-render quality change adds a selected poster hook throughout vertical exports, turns on audio normalization for API, CLI, and UI renders by default, normalizes the optional post-render music mix, and persists stream/loudness/peak checks in job status. It adds no migration. Local media inspection found −15.4 LUFS on a short render and −15.2 LUFS after a test music mix against a −14 LUFS preset target. An authenticated local browser render of clean talking-head source produced a 26.13-second 1080×1920/30 fps export at −14.6 LUFS and −1.4 dBFS true peak with no technical QC warnings; its frames showed the hook and changing captions. A later preview also completed with no technical QC warnings at 540×960 and −14.6 LUFS. The final smaller-caption and enlarged-hook preset was checked in a fresh MLT frame but is not in that full export. The macOS screen locked before final browser status inspection. App and Celery worker images were rebuilt and recreated after the preview; local readiness passed for database, Redis, Celery, disk, and ffmpeg. VPS release status remains pending.

The new export path embeds each selected poster as the MP4 opening frame and attached cover art. Hermes reads Instagram App ID, App Secret, Access Token, and User ID only from each user's encrypted UI settings. Local focused API/render tests and the frontend build passed; a real provider login, QuickTime playback, authenticated deployed browser flow, and VPS verification remain open. Rebuild app, worker, Hermes, and frontend images, and re-render older MP4s that need the poster. Existing Hermes users must save all four credential fields again. No database migration is needed for this change.

### Local container update, 2026-10-12

Revision `74a633e` was fast-forwarded to the clean local `main` checkout and deployed to the existing `ai_render` Compose project. App, worker, Hermes, frontend, and nginx images built; app, worker, and Hermes were recreated without replacing PostgreSQL or Redis volumes. The app, worker, Hermes, nginx, database, Redis, and beat reported healthy. `GET /healthz` and `/api/health/ready` returned HTTP 200; readiness checks for database, Redis, Celery, disk, and FFmpeg passed. The live app container produced the rated caption «سرمایه اولیه اصولا نمی‌خواد» from local fallback and Content Creator sample plans. The refreshed authenticated local browser displayed that saved poster text for job `1d4e7a5585de`. A newly generated end-to-end plan and downloaded MP4 were not inspected after this deployment. None of this verifies the VPS release gates below.

Later on 2026-10-12, a newly generated local job `f02d4ccd2b4c` selected «سرمایه اولیه اصولاً نمی‌خواد» through the rating system. Its full render completed and the browser-downloaded `v1.mp4` matched the server export SHA-256. The first decoded MP4 frame visibly carried that title, and FFprobe reported H.264 video, AAC audio, and attached MJPEG artwork. The authenticated browser showed the paused MP4 frame at 0:00 with no separate HTML poster image. The revised frontend bundle was built and deployed, with 15 Render tests passing. Native QuickTime and VPS-domain playback remain unverified.

## Decision

**Not ready to deploy yet.** This audit made the production path fail closed, but the local deployment inputs are incomplete: `ALLOWED_HOSTS` and `HERMES_TOKEN_KEY` are absent from the current `.env`, and `certs/fullchain.pem` and `certs/privkey.pem` are absent. No VPS, public TLS, PostgreSQL, Redis, provider, browser, or live Celery acceptance was performed. Do not treat a successful build or SQLite migration check as a live deployment check.

The working tree already contained many unrelated changes. The audit did not reset or commit them. Run `./scripts/deploy.sh` only on the intended VPS after reviewing and supplying the missing inputs. It uses `docker-compose.yml` explicitly so the local `docker-compose.override.yml` does not publish the database port.

## Findings and changes

1. **Environment and secrets — PARTIAL.** `.env` and `.jwt_secret` are ignored and absent from tracked files; `git log --all -- .env .jwt_secret` returned no history. A bounded scan of tracked text at HEAD found placeholder examples and test tokens, no confirmed live key. This is not a full secret scan of all Git history or untracked files. `.env.example` now documents required and optional runtime keys, including production host/CORS and Hermes encryption. `scripts/deploy.sh` checks required keys without printing values. **Action:** supply a unique 32+ character `JWT_SECRET`, a separate stable 32+ character `HERMES_TOKEN_KEY`, URL-safe `POSTGRES_PASSWORD`, and exact `ALLOWED_HOSTS`. Do not commit `.env`. Rotate any key if it was ever disclosed outside this audit.

2. **Compose lifecycle and resources — CONFIGURED, runtime unverified.** `docker-compose.yml` now has restart policies for long-lived services, health checks for nginx, app, Hermes, worker, beat, PostgreSQL and Redis, and CPU, memory and PID limits. `frontend` is a one-shot copier, so `restart: "no"` and an exited-zero state are expected. `POSTGRES_PASSWORD` has no default. `docker compose config --quiet` passed with an audit-only placeholder override. **Action:** inspect `docker compose -f docker-compose.yml ps` and resource pressure under real render load. The worker's Celery ping and beat PID checks need live validation.

3. **Python image — CONFIGURED, local build passed.** `Dockerfile` now uses a builder virtual environment copied into a runtime stage. `requirements-prod.txt` excludes the test-only `pytest` and `aiosqlite` packages; `jsonlines` remains because the effects engine imports it at runtime. Build tools are absent from the runtime stage. **Risk:** dependency versions still use lower bounds rather than an immutable lock, so a future rebuild may resolve different packages. Pin/lock before a reproducible release.

4. **CORS and security headers — CONFIGURED, browser unverified.** `app/main.py` keeps localhost CORS only in development; production accepts only exact HTTPS origins from `CORS_ORIGINS`, or no cross-origin requests for the same-origin nginx deployment. It checks exact `ALLOWED_HOSTS`. `hermes/main.py` disables development CORS in production. nginx and FastAPI set frame, MIME and referrer headers; nginx also sets a Permissions Policy. Interactive API docs are disabled in production. **Action:** check browser requests and response headers on the final domain. A Content Security Policy was not added because the built frontend and third-party flows need a separate compatibility review.

5. **Migrations — CODE CURRENT, live database unverified.** Existing revision `b7755915bc7e` covered the core tables but omitted Hermes tables that were created at startup. Revision `d57cf7a0bea7` now creates those six tables and adopts any already-existing Hermes tables without dropping their data; `alembic/env.py` registers Hermes metadata. This adoption migration is forward-only: roll back with a verified database backup. Production startup now checks connectivity without `create_all`. Isolated SQLite migrations and `alembic check` passed both with fresh and pre-existing Hermes tables at head `d57cf7a0bea7`. `scripts/deploy.sh` runs a baseline check, upgrade, and schema check before starting services; the baseline check refuses unstamped existing core tables. **Action:** back up the VPS PostgreSQL database, run the migration there, confirm `alembic current` reports the head, and verify Hermes data survives. Existing unstamped tables require manual schema reconciliation. SQLite is not PostgreSQL proof.

## Rollback procedure

1. Select the previous known-good commit and check out its SHA: `git checkout <sha>`.
2. Rebuild the application images from that checkout: `docker compose -f docker-compose.yml -f docker-compose.production.yml build`.
3. If the deployed database migration is incompatible with the previous code, first take and verify a PostgreSQL backup. Inspect the specific migration's downgrade for data loss and confirm the previous application schema is compatible. Only then reverse one revision on the intended database with `docker compose -f docker-compose.yml -f docker-compose.production.yml run --rm app alembic downgrade -1`. Do not downgrade when the prior code remains compatible with the newer schema. Never run a downgrade against the live database without this backup and migration-specific review.

6. **Public endpoint rate limits — CONFIGURED at nginx, live unverified.** nginx limits `/api/auth/` by client IP and all other `/api/` routes, including Hermes, with HTTP 429 on excess. The application services are not published directly in base Compose. **Action:** exercise rate limits from a real client IP. If a CDN or load balancer is added, configure trusted real-IP handling before relying on per-IP limits. Brute-force and account-level controls remain a separate future hardening item.

7. **Structured, sensitive-data-safe logging — PARTIAL.** nginx access logs are JSON and omit query strings, headers, referrers, user agents and client IPs. The main API emits JSON request events with method, path, status and duration. Celery task wrapper and initialization logs no longer include exception text, and dead-letter records contain only task/job IDs and exception type. **Residual risk:** other app, engine, brain, Hermes, Gunicorn, and Celery internal logs still use mixed formats and may include provider or file-path details. A full log-redaction review and runtime log sample are required before claiming sensitive-data-safe logging across the stack.

8. **Client errors — CONFIGURED for 5xx, runtime unverified.** The main FastAPI handler replaces explicit HTTP 5xx detail with a generic message. Starlette's default non-debug 500 path remains in use for uncaught errors. Known upload, style analysis, and native-app 5xx exception strings are therefore hidden from clients. Hermes also maps explicit 5xx responses to a generic code. Production password reset is disabled with 503 because no email delivery path was found; `_dev_token` is never returned there. **Residual blocker:** users cannot self-serve a reset on the VPS until delivery is implemented and tested.

9. **Static compression and caching — CONFIGURED, live unverified.** nginx enables gzip for text, CSS, JavaScript, JSON, XML and SVG; Vite `/assets/` receives a one-year immutable cache, while `index.html` receives `no-store`. **Action:** use `curl -I -H 'Accept-Encoding: gzip'` against actual assets and confirm `Content-Encoding` and `Cache-Control` after the frontend bundle is copied.

10. **HTTPS/TLS — CONFIGURED, CERTIFICATES MISSING.** nginx listens on 443 with TLS 1.2/1.3 and redirects HTTP to HTTPS. The deployment script requires certificate and key files and verifies HTTPS against the configured hostname. nginx syntax passed in its Docker image with a temporary test certificate. **Action:** install a trusted certificate at `certs/fullchain.pem` and its private key at `certs/privkey.pem` with restrictive permissions; set DNS and `ALLOWED_HOSTS`; verify renewal, external chain, redirect and expiry on the VPS. The production certificate was not created or tested here. HSTS should be considered only after the final HTTPS path is stable.

11. **Celery retries and dead letters — CONFIGURED, runtime unverified.** Task wrappers retry transient errors twice with exponential delays and skip retry for known non-retryable input/file errors. Terminal task failures write minimal records under the shared `/app/jobs/dead_letters/` volume; late acknowledgement and worker-loss rejection are configured. **Action:** run a controlled failed task against live Redis/worker, verify retries, one terminal record, job status and operator alerting. A file record is durable triage data, not a monitored dead-letter queue; add alerting and a replay procedure before relying on unattended processing. Worker loss can still cause repeated delivery and requires a live fault test.

### Evidence anchors

- Environment: `.env.example:41-81`, `.gitignore:24`, `.gitignore:31`, `.gitignore:36`, `scripts/deploy.sh:4-33`.
- Compose: `docker-compose.yml:4-26`, `docker-compose.yml:40-60`, `docker-compose.yml:86-115`, `docker-compose.yml:152-180`.
- Image: `Dockerfile:1-18`, `requirements-prod.txt:1-28`.
- CORS and headers: `app/main.py:55-102`, `hermes/main.py:39-68`, `nginx/nginx.conf:49-52`.
- Migrations: `alembic/env.py:11-22`, `alembic/versions/d57cf7a0bea7_add_hermes_tables.py:20-112`, `scripts/check_migration_baseline.py:1-29`.
- Rate limits: `nginx/nginx.conf:25-27`, `nginx/nginx.conf:77-110`.
- Logs: `nginx/nginx.conf:10-11`, `app/main.py:94-110`, `app/tasks.py:14-27`.
- Client errors: `app/main.py:83-91`, `hermes/main.py:48-55`, `app/auth_routes.py:91-98`.
- Assets: `nginx/nginx.conf:20-23`, `nginx/nginx.conf:54-69`.
- TLS: `nginx/nginx.conf:32-47`, `docker-compose.yml:5-13`, `scripts/deploy.sh:8-13`.
- Celery: `app/tasks.py:14-27`, `app/tasks.py:52-70`, `app/celery_app.py:27-39`.

## Release gates

- Populate `.env` on the VPS with production values. Current local `.env` has `POSTGRES_PASSWORD` and `JWT_SECRET` set, but lacks `ALLOWED_HOSTS` and `HERMES_TOKEN_KEY`; values were not displayed or copied.
- Install a valid certificate and key under `certs/`, and verify renewal and DNS.
- Pin/lock production dependencies for reproducible image rebuilds.
- Back up PostgreSQL, run `./scripts/deploy.sh`, and inspect migration output and service health. Do not run the script against an existing database without a restorable backup.
- Validate browser login, upload, render, Hermes flows, asset caching, rate limiting, worker retries/dead letters, and logs on the real domain.
- Implement and test production password-reset delivery, or explicitly disable and document that feature before public launch.

## Health and logs

- `GET /health` is the app liveness endpoint. It performs no dependency calls and is the app container healthcheck target.
- `GET /api/health/ready` checks PostgreSQL, Redis, a cached Celery worker ping, free space on the jobs/assets filesystems (minimum `HEALTH_MIN_DISK_FREE_GB`, default 2), and ffmpeg. PostgreSQL or Redis failure returns 503; other failures return 200 with `degraded: true`. The response contains only pass/fail status and timings.
- `GET /healthz` is nginx's public health endpoint and proxies the app's cheap `/health` liveness response; its Docker healthcheck command is unchanged.
- Trace a request across nginx, app, Hermes, and worker logs with `docker compose logs nginx app hermes celery-worker | grep '<request_id>'`. Send `X-Request-ID` to retain a caller-generated ID, or copy the generated ID from the response header.

## Local verification performed

- `docker compose config --quiet` with an audit-only password placeholder: passed.
- `docker compose build nginx`: passed. `nginx -t` in that image with a temporary test certificate and local upstream names: passed.
- `DATABASE_URL='' REDIS_URL='' .venv/bin/python -m pytest -q tests/test_auth.py tests/test_job_concurrency.py hermes/tests/test_database.py hermes/tests/test_auth.py`: 25 passed (local fallback mode only).
- Isolated SQLite `alembic upgrade head`, `alembic check`, `alembic current`: passed at `d57cf7a0bea7`, both with fresh and pre-existing Hermes tables.
- `bash -n scripts/deploy.sh`, Python compile, and `git diff --check`: passed.
- Local nginx container with a disposable certificate: HTTP redirect, HTTPS security headers, HTML no-store, immutable compressed asset all passed.
- Migration baseline check accepted an empty SQLite database and rejected unstamped existing core tables.
- `docker compose -f docker-compose.yml build nginx app frontend`: each image built locally; no production stack was started. The app image imported both FastAPI services and `jsonlines`, and did not contain `pytest` or `aiosqlite`.
- `npm --prefix web run build`: passed; Vite reported a dynamic/static import warning for `web/src/api.ts` but emitted the production bundle.
- A production-mode FastAPI probe with a temporary test secret and host checked exact host enforcement, denied cross-origin response, security headers, and inaccessible docs without starting the database.
