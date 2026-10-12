# AI Render — VPS Production Deployment Plan

## Architecture Overview

```
VPS (e.g. 8-core, 32GB RAM, 500GB SSD)
├── Part A: AI Render Application Server
│   ├── Nginx (reverse proxy + SSL + static files)
│   ├── FastAPI backend (Gunicorn + Uvicorn workers)
│   ├── React frontend (built static files)
│   ├── PostgreSQL (replaces JSON file storage)
│   ├── Redis (job queue, caching, session store)
│   ├── Celery workers (background jobs: render, AI, denoise)
│   └── ffmpeg/melt (rendering)
│
└── Part B: Hermes Agent (Instagram Automation)
    ├── FastAPI service (port 8001)
    ├── Instagram Graph API integration
    ├── Scheduler (APScheduler / Celery Beat)
    ├── Analytics collector & advisor
    └── Bridge to Part A (Content Creator API)
```

Both parts share PostgreSQL and Redis but run as separate services.

---

## DEPLOYMENT STAGES

### Stage D0 — VPS Setup & Infrastructure
- Ubuntu 24.04 LTS, Docker + Docker Compose
- Nginx with Let's Encrypt SSL (certbot)
- PostgreSQL 16, Redis 7
- Firewall (UFW): only 80, 443, 22 open
- Non-root deploy user, SSH key auth
- Separate Docker networks: `app-net` (Part A), `hermes-net` (Part B), `shared-net` (DB/Redis)

### Stage D1 — Part A: AI Render Production Deploy
- Dockerize backend (Python 3.12, ffmpeg, melt in container)
- Dockerize frontend (Node build → Nginx static serve)
- Migrate from JSON files to PostgreSQL (users, jobs, styles, feedback)
- Celery + Redis for background jobs (render, generate-plan, QC, denoise, content-create)
- Gunicorn with 4 Uvicorn workers
- Environment variables via .env file
- Health checks, logging (structured JSON), log rotation
- File storage: local volume mount or S3-compatible (MinIO)
- Backup: daily pg_dump + job files rsync

### Stage D2 — Part B: Hermes Agent Core
- Instagram Graph API setup (Facebook Developer App, Business Account)
- Hermes FastAPI service with its own auth (API key from Part A)
- Post scheduling: create → queue → publish at optimal time
- Content pipeline: Hermes calls Part A's Content Creator API to generate content
- Media upload to Instagram via Graph API
- Account connection flow (OAuth2 for Instagram Business)

### Stage D3 — Part B: Analytics & Insights
- Collect: followers, reach, impressions, engagement, likes, comments, saves, shares
- Per-post analytics: track every published post/reel/story performance
- Historical data storage in PostgreSQL
- Advisor engine: analyze patterns → suggest best posting times, content types, hashtags
- Dashboard API for frontend

### Stage D4 — Part B: Smart Scheduling & Auto-Management
- Auto-reply to comments (templated, AI-powered)
- Story scheduling with countdown/polls
- Hashtag research and suggestion
- Competitor analysis (public profiles)
- Content calendar view

### Stage D5 — Unified Dashboard
- Single frontend combining AI Render + Hermes
- Instagram account overview, analytics charts
- Content calendar with drag-and-drop scheduling
- Performance reports (weekly/monthly)
- AI advisor chat: "What should I post next?"

---

## ENVIRONMENT VARIABLES (.env)

```env
# Part A — AI Render
DOMAIN=airender.yourdomain.com
JWT_SECRET=<random-64-chars>
DATABASE_URL=postgresql://airender:pass@db:5432/airender
REDIS_URL=redis://redis:6379/0
LLM_PROVIDER=jarvis
LLM_MODEL=CLAUDE_SONNET_5_5
JARVIS_API_KEY=...
ELEVENLABS_API_KEY=...
WHISPER_MODEL=large-v3
CELERY_BROKER_URL=redis://redis:6379/1
FILE_STORAGE_PATH=/data/jobs
ALLOWED_ORIGINS=https://airender.yourdomain.com

# Part B — Hermes Agent
HERMES_PORT=8001
HERMES_API_KEY=<internal-service-key>
# Instagram credentials are entered per user in the Hermes UI, not here.
INSTAGRAM_REDIRECT_URI=https://example.com/api/hermes/auth/callback
HERMES_DATABASE_URL=postgresql://hermes:pass@db:5432/hermes
HERMES_REDIS_URL=redis://redis:6379/2
AIRENDER_API_URL=http://app:8000
AIRENDER_SERVICE_KEY=<service-to-service-auth>
```

---

## DOCKER COMPOSE STRUCTURE

```
docker-compose.yml
├── services:
│   ├── nginx          (ports 80, 443)
│   ├── app            (Part A backend, port 8000 internal)
│   ├── celery-worker  (Part A background jobs)
│   ├── celery-beat    (Part A periodic tasks)
│   ├── hermes         (Part B backend, port 8001 internal)
│   ├── hermes-worker  (Part B scheduler/collector)
│   ├── db             (PostgreSQL)
│   ├── redis          (Redis)
│   └── frontend       (built React, served by nginx)
```
