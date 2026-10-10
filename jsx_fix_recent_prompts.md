# Recent prompts from "Bridge JSX error handling fixes"

Source: https://claude.ai/chat/47aafbca-4b26-837f-bb6e-5a7ac87a890f
Order: oldest to newest. Long pasted reports are shortened; the first line of each is kept.

## 1. P1/P2 frontend scan fix report (pasted)
Implemented P1 and P2 frontend scan fixes. P3 not changed.
- Memory-only access token in web/src/auth.ts (getToken, setToken, clearToken).
- HttpOnly refresh cookie ai_render_refresh_token on signup/login; refresh and logout accept it.
- Shared 401 handler in web/src/api.ts and web/src/services/hermesApi.js.
- Error boundary in web/src/main.tsx; job cache in web/src/JobCache.tsx; Jobs view lazy-loaded.
- Terminal-state polling shutdown in Render.tsx and QCReview.tsx.
- Build passes; tests/test_auth.py: 18 passed, 3 failed (password-reset expectations, SMTP 503).

## 2. Prompt request: full backend live integration test suite
Run a full live integration suite against http://localhost:8000 with no mocks. Sections: auth, jobs and ownership, plan and storyboard, render, QC, Premiere ZIP export, content creator, Hermes, Celery/Redis, Nginx/infrastructure, edge cases. Python with httpx, saved as tests/test_integration_live.py. Print a summary table and failure details.

## 3. Integration runner report (pasted)
Created tests/test_integration_live.py. Live run found:
- Signup returns 200, expected 201; no ai_render_refresh_token Set-Cookie.
- Cookie-only refresh and logout return 422.
- Second user gets 200 on GET /jobs/{id}, expected 403.
- Plan generation stuck at "running whisper".
- Nginx down: missing /etc/nginx/tls/fullchain.pem.

## 4. Premiere status report (pasted)
Premiere card now shows "Premiere Pro not detected — XML/ZIP export still works" instead of "Unavailable". Frontend builds. Pre-existing failures: NameError 'jobstore' at app/premiere_bridge.py:305 (50 bridge test failures). Nothing committed.

## 5. Docker rebuild result (pasted)
Ran docker compose down, build app celery-worker, up -d. All services healthy. edge-tts synthesis not tested.

## 6. Instagram reel prompt request
"please give me very excellent building instagram reels from content generator"
Claude replied with a Persian reel prompt: "5 simple habits that change your life", motivational tone, one scene per tip, Persian female voiceover, warm colors, follow call-to-action at the end.

## 7. Remaining-problems request with music upload report (pasted)
"give me prompt to fix remain problems" plus a report: music upload 500 caused by unvalidated energy (must be 1-5), orphaned file on disk, and GET /library crashing from a bad sidecar. Fixes applied in app/routers/music.py and engine/library.py; tests/test_library.py and tests/test_music.py: 40 passed. Venv mismatch noted: .venv/bin/python 3.12 vs uvicorn 3.14.
Requested Codex prompt for: Library.tsx energy clamp; QC reset in app/jobs.py start_render and QCReview.tsx applyFixes; brain/qc_review.py adjust_music_volume only when plan.music.

## 8. Venv question
"what about this = Your .venv is mixed: .venv/bin/python is 3.12, but .venv/bin/uvicorn points at 3.14 ... give me also a prompt to fix it"
Claude gave a one-line rebuild: rm -rf .venv && python3.14 -m venv .venv && pip install -r requirements.txt.

## 9. Claude Code terminal version request
"i want implement fixiation prompt at claude code so customise it for claude code at terminal."
Claude gave a terminal prompt to fix: Library.tsx energy clamp (min 1, max 5); app/jobs.py job.qc = QCState() before RenderState; brain/qc_review.py adjust_music_volume only when plan.music. Then npm run build and docker compose rebuild.

## 10. Not recovered
The tenth-most-recent prompt could not be confirmed from the loaded page. Earlier "Load earlier messages" sections were not fully expanded.
