# Hermes Agent

Hermes is a separate FastAPI service for Instagram professional accounts. Install
the root `requirements.txt`, set the main project's `.env`, then run from the
project root:

```sh
DATABASE_URL= REDIS_URL= python -m uvicorn hermes.main:app --port 8001
python -m pytest hermes/tests/ -v
```

The blank overrides select local JSON storage and polling when the shared
`.env` contains Docker hostnames for PostgreSQL and Redis.

For live Instagram Login, each user enters App ID, App Secret, Access Token,
and Instagram User ID in the Hermes settings UI. Only `INSTAGRAM_REDIRECT_URI`
belongs in the server environment. The redirect URI must
match `/api/hermes/auth/callback` and the URI registered with Meta. Hermes
uses the main app's `JWT_SECRET` and user store. Set `HERMES_TOKEN_KEY` to a
stable, separate secret before storing live Instagram tokens; changing it
later makes existing tokens unreadable. Hermes accepts the same access JWTs
as the main app. The OAuth callback uses a single-use, ten-minute state
issued by the authenticated `/connect` route because a browser redirect
cannot carry the API Authorization header.

Without `DATABASE_URL`, records live in `jobs/hermes/data.json`. With it,
Hermes creates its own tables in the shared PostgreSQL database; the
existing `users` table must already exist. Without `REDIS_URL`, the service
polls due posts every 30 seconds in its local process. With Redis, run the
Hermes Celery worker and beat process using
`hermes.services.scheduler_service.celery_app` for scheduled posting. Docker
integration is a later step.

`POST /api/hermes/posts/media` stores a file locally. Instagram publishing
requires a public HTTPS media URL. Set `HERMES_PUBLIC_MEDIA_BASE_URL` only
when a separate public media server exposes the saved media directory under
`/<user_id>/<media_id>`; otherwise the upload response has `media_url: null`.
The API itself requires authentication and does not expose local uploads.

Analytics responses return `null` for metrics Instagram does not make
available for a given account or media type. Results are cached in storage
for one hour. Advice uses the main app's `LLM_PROVIDER`, `LLM_MODEL`, and
provider credentials through `brain.llm.chat_json`.
