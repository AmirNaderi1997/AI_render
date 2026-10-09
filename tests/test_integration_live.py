#!/usr/bin/env python3
"""Live, destructive integration smoke test for a running AI Render stack.

This deliberately uses no ASGI transport, mocks, fixtures, or test database.  It
creates two timestamped users and one short job in the services configured at
LIVE_BASE_URL (default: the directly exposed FastAPI backend on port 8000).

Run: python tests/test_integration_live.py
Optional: LIVE_BASE_URL=https://localhost python tests/test_integration_live.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


BACKEND = os.environ.get("LIVE_BASE_URL", "http://localhost:8000").rstrip("/")
NGINX = os.environ.get("NGINX_BASE_URL", "http://localhost").rstrip("/")
VERIFY_TLS = os.environ.get("LIVE_VERIFY_TLS", "0") == "1"
VIDEO = Path("/tmp/test_input.mp4")


@dataclass
class Failure:
    section: str
    endpoint: str
    expected: str
    actual: str
    status: str
    body: str


@dataclass
class Group:
    name: str
    run: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class LiveSuite:
    def __init__(self) -> None:
        self.groups: dict[str, Group] = {}
        self.failures: list[Failure] = []
        self.job_id: str | None = None
        self.token: str | None = None
        self.user2_token: str | None = None
        self.client = httpx.Client(base_url=BACKEND, timeout=30, follow_redirects=False)

    def group(self, name: str) -> Group:
        return self.groups.setdefault(name, Group(name))

    @staticmethod
    def snippet(response: httpx.Response | None) -> str:
        if response is None:
            return "no response"
        text = response.text.replace("\n", " ").strip()
        return text[:600] or "<empty>"

    def check(self, section: str, label: str, response: httpx.Response | None,
              ok: bool, expected: str, actual: str | None = None) -> bool:
        g = self.group(section)
        g.run += 1
        if ok:
            g.passed += 1
            print(f"PASS [{section}] {label}")
            return True
        g.failed += 1
        self.failures.append(Failure(section, label, expected, actual or "assertion failed",
                                     str(response.status_code) if response else "NO_RESPONSE",
                                     self.snippet(response)))
        print(f"FAIL [{section}] {label}: expected {expected}; actual {actual or 'assertion failed'}")
        return False

    def skip(self, section: str, label: str, why: str) -> None:
        g = self.group(section)
        g.skipped += 1
        print(f"SKIP [{section}] {label}: {why}")

    def request(self, method: str, path: str, *, token: str | None = None, **kwargs: Any) -> httpx.Response | None:
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            return self.client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            print(f"HTTP ERROR {method} {BACKEND}{path}: {exc}")
            return None

    @staticmethod
    def token_from(r: httpx.Response | None) -> str | None:
        if not r:
            return None
        try:
            body = r.json()
        except ValueError:
            return None
        return body.get("access_token") or body.get("token")

    def auth(self) -> None:
        section = "1. AUTH"
        unique = uuid.uuid4().hex[:12]
        email, password = f"live-{unique}@example.test", "LiveTest!9Password"
        r = self.request("POST", "/auth/signup", json={"email": email, "name": "Live Integration", "password": password})
        self.check(section, "POST /api/auth/signup (backend /auth/signup)", r,
                   bool(r and r.status_code == 201 and self.token_from(r) and "ai_render_refresh_token=" in r.headers.get("set-cookie", "") and "HttpOnly" in r.headers.get("set-cookie", "") and "SameSite=lax" in r.headers.get("set-cookie", "")),
                   "201, access token, HttpOnly ai_render_refresh_token cookie",
                   f"status={r.status_code if r else 'no response'}, token={bool(self.token_from(r)) if r else False}, set-cookie={r.headers.get('set-cookie', '')[:180] if r else ''}")
        self.token = self.token_from(r)

        r = self.request("POST", "/auth/login", json={"email": email, "password": password})
        self.check(section, "POST /api/auth/login (backend /auth/login)", r,
                   bool(r and r.status_code == 200 and self.token_from(r) and "ai_render_refresh_token=" in r.headers.get("set-cookie", "")),
                   "200, access and refresh tokens", f"status={r.status_code if r else 'no response'}")
        self.token = self.token_from(r) or self.token

        # Exercise the cookie-only flow; do not send an empty JSON body because
        # some deployed FastAPI versions model this endpoint as a scalar body.
        r = self.request("POST", "/auth/refresh")
        refreshed = self.token_from(r)
        self.check(section, "POST /api/auth/refresh (backend /auth/refresh)", r,
                   bool(r and r.status_code == 200 and refreshed), "200 with new access token", f"status={r.status_code if r else 'no response'}")
        self.token = refreshed or self.token

        r = self.request("GET", "/auth/me", token=self.token)
        self.check(section, "GET /api/auth/me (backend /auth/me)", r,
                   bool(r and r.status_code == 200 and r.json().get("email") == email), "200 profile for created user", f"status={r.status_code if r else 'no response'}")
        r = self.request("GET", "/auth/me", token="expired.invalid.token")
        self.check(section, "GET /api/auth/me invalid token", r, bool(r and r.status_code == 401), "401", f"status={r.status_code if r else 'no response'}")
        r = self.request("POST", "/auth/forgot-password", json={"email": email})
        self.check(section, "POST /api/auth/forgot-password", r, bool(r and r.status_code in (200, 503)), "200 or 503 when SMTP is absent", f"status={r.status_code if r else 'no response'}")
        r = self.request("POST", "/auth/logout")
        self.check(section, "POST /api/auth/logout", r,
                   bool(r and r.status_code == 200 and "ai_render_refresh_token=" in r.headers.get("set-cookie", "")),
                   "200 and cleared refresh cookie", f"status={r.status_code if r else 'no response'}, set-cookie={r.headers.get('set-cookie', '')[:180] if r else ''}")
        # Login again: logout intentionally clears the cookie used for later sections.
        r = self.request("POST", "/auth/login", json={"email": email, "password": password})
        self.token = self.token_from(r)

    def jobs_crud(self) -> None:
        section = "2. JOBS CRUD + OWNERSHIP"
        if not self.token:
            self.skip(section, "all", "authentication did not yield an access token")
            return
        r = self.request("POST", "/jobs", token=self.token, files={"video": (VIDEO.name, VIDEO.read_bytes(), "video/mp4")})
        data = r.json() if r and r.headers.get("content-type", "").startswith("application/json") else {}
        self.job_id = data.get("job", {}).get("id")
        self.check(section, "POST /api/jobs/upload (backend POST /jobs)", r, bool(r and r.status_code == 201 and self.job_id),
                   "201 with job_id", f"status={r.status_code if r else 'no response'}, job_id={self.job_id}")
        r = self.request("GET", "/jobs", token=self.token)
        self.check(section, "GET /api/jobs", r, bool(r and r.status_code == 200 and any(x.get("id") == self.job_id for x in r.json())),
                   "200 and created job in list", f"status={r.status_code if r else 'no response'}")
        if not self.job_id:
            return
        r = self.request("GET", f"/jobs/{self.job_id}", token=self.token)
        self.check(section, f"GET /api/jobs/{self.job_id}", r, bool(r and r.status_code == 200 and r.json().get("id") == self.job_id),
                   "200 with correct job", f"status={r.status_code if r else 'no response'}")
        unique = uuid.uuid4().hex[:12]
        r = self.request("POST", "/auth/signup", json={"email": f"owner-{unique}@example.test", "name": "Other User", "password": "LiveTest!9Password"})
        self.user2_token = self.token_from(r)
        r = self.request("GET", f"/jobs/{self.job_id}", token=self.user2_token)
        self.check(section, "other user GET job", r, bool(r and r.status_code == 403), "403 ownership denial", f"status={r.status_code if r else 'no response'}")
        r = self.request("PUT", f"/jobs/{self.job_id}/plan", token=self.user2_token, json={"plan": {}})
        self.check(section, "other user PUT job plan", r, bool(r and r.status_code == 403), "403 ownership denial", f"status={r.status_code if r else 'no response'}")

    def plan_and_render(self) -> None:
        section = "3. PLAN + STORYBOARD"
        if not self.job_id or not self.token:
            self.skip(section, "all", "no owned uploaded job")
            return
        r = self.request("POST", f"/jobs/{self.job_id}/generate-plan", token=self.token, json={"asr_engine": "local", "language": "en"})
        self.check(section, "POST /api/jobs/{job_id}/plan (backend generate-plan)", r, bool(r and r.status_code in (200, 202)), "200/202 plan generation accepted", f"status={r.status_code if r else 'no response'}")
        deadline, status = time.monotonic() + 60, "unknown"
        while time.monotonic() < deadline:
            r = self.request("GET", f"/jobs/{self.job_id}/generate-plan/status", token=self.token)
            if not r or r.status_code != 200:
                break
            status = r.json().get("status", "unknown")
            if status in ("done", "error"):
                break
            time.sleep(5)
        r = self.request("GET", f"/jobs/{self.job_id}", token=self.token)
        plan = (r.json().get("plan") if r and r.status_code == 200 else None) or {}
        scenes = plan.get("scenes", plan.get("segments", []))
        self.check(section, "poll generated plan", r, status == "done" and bool(scenes), "ready plan with scenes/segments", f"generation status={status}, scenes={len(scenes)}")
        # The persisted edit-plan contract calls these segments, not scenes. Put a known renderable plan so
        # render/QC/Premiere test the live worker even if speech/LLM generation cannot complete locally.
        manual = {"version": "0.1", "style": "rafiei_reel", "canvas": {"width": 320, "height": 240, "fps": 25},
                  "source": f"raw/{VIDEO.name}", "segments": [{"id": "s1", "in": 0, "out": 1.8}],
                  "captions": [], "export": {"file": "live-integration.mp4"}}
        r = self.request("PUT", f"/jobs/{self.job_id}/plan", token=self.token, json={"plan": manual})
        self.check(section, "POST modifications equivalent (backend PUT /plan)", r, bool(r and r.status_code == 200 and r.json().get("ok")),
                   "200 and persisted plan update", f"status={r.status_code if r else 'no response'}")

        section = "4. RENDER"
        started = time.monotonic()
        r = self.request("POST", f"/jobs/{self.job_id}/render", token=self.token)
        self.check(section, "POST /api/jobs/{job_id}/render", r, bool(r and r.status_code == 202), "202 render accepted", f"status={r.status_code if r else 'no response'}")
        deadline, render_status, render_data = time.monotonic() + 300, "unknown", {}
        while time.monotonic() < deadline:
            r = self.request("GET", f"/jobs/{self.job_id}/render/status", token=self.token)
            if not r or r.status_code != 200:
                break
            render_data = r.json(); render_status = render_data.get("status", "unknown")
            if render_status in ("done", "completed", "error", "failed"):
                break
            time.sleep(5)
        elapsed = round(time.monotonic() - started, 1)
        self.check(section, "poll render status", r, render_status in ("done", "completed"), "completed within 300 seconds", f"status={render_status}, elapsed={elapsed}s")
        output = render_data.get("output")
        if render_status in ("done", "completed") and output:
            r = self.request("GET", f"/jobs/{self.job_id}/exports/{Path(output).name}", token=self.token)
            self.check(section, "GET render download (backend exports/{file})", r, bool(r and r.status_code == 200 and "video" in r.headers.get("content-type", "")),
                       "200 video content", f"status={r.status_code if r else 'no response'}, content-type={r.headers.get('content-type') if r else ''}")
        else:
            self.skip(section, "render download", "render did not complete with an output path")

    def qc_premiere_content(self) -> None:
        if not self.job_id or not self.token:
            self.skip("5. QC", "all", "no owned uploaded job"); self.skip("6. PREMIERE EXPORT", "all", "no owned uploaded job"); self.skip("7. CONTENT CREATOR", "all", "no token"); return
        section = "5. QC"
        r = self.request("POST", f"/jobs/{self.job_id}/qc/run", token=self.token)
        self.check(section, "POST /api/jobs/{job_id}/qc (backend qc/run)", r, bool(r and r.status_code in (200, 202)), "QC accepted", f"status={r.status_code if r else 'no response'}")
        deadline, qc = time.monotonic() + 60, {}
        while time.monotonic() < deadline:
            r = self.request("GET", f"/jobs/{self.job_id}/qc/status", token=self.token)
            if not r or r.status_code != 200: break
            qc = r.json()
            if qc.get("status") in ("done", "completed", "error", "failed"): break
            time.sleep(5)
        self.check(section, "poll QC status", r, qc.get("status") in ("done", "completed"), "QC complete with scores/issues", f"status={qc.get('status')}, issues={qc.get('issues')}")

        section = "6. PREMIERE EXPORT"
        r = self.request("GET", f"/jobs/{self.job_id}/premiere", token=self.token)
        valid_zip = bool(r and r.status_code == 200 and r.content[:2] == b"PK")
        self.check(section, "GET /api/jobs/{job_id}/premiere", r, valid_zip, "200 ZIP", f"status={r.status_code if r else 'no response'}, content-type={r.headers.get('content-type') if r else ''}")
        if valid_zip and r:
            archive = Path("/tmp/live-premiere.zip"); archive.write_bytes(r.content)
            with zipfile.ZipFile(archive) as z:
                names = z.namelist(); xmls = [n for n in names if n.lower().endswith(".xml")]
                xml = z.read(xmls[0]).decode("utf-8", "replace") if xmls else ""
            self.check(section, "ZIP XML and relative paths", r, bool(xmls) and "/app/" not in xml and "file://" not in xml,
                       "XML exists with no /app/ absolute paths", f"xml_files={xmls}, absolute_app_path={'/app/' in xml}")
        else: self.skip(section, "ZIP XML validation", "Premiere ZIP unavailable")

        section = "7. CONTENT CREATOR"
        r = self.request("POST", "/content/create", token=self.token, json={"prompt": "Test video about clouds, 15 seconds", "provider": "local_fixture"})
        body = r.json() if r and r.headers.get("content-type", "").startswith("application/json") else {}
        self.check(section, "POST /api/content/create", r, bool(r and r.status_code in (200, 202)), "200/202 content creation", f"status={r.status_code if r else 'no response'}")
        self.check(section, "content storyboard/media result", r, bool(body.get("storyboard") or body.get("scenes") or body.get("job_id")),
                   "storyboard/scenes/job_id returned", f"keys={sorted(body)}")

    def hermes(self) -> None:
        section = "8. HERMES"
        # Hermes is a separate service behind Nginx. It cannot be reached on backend port 8000 directly.
        r = self.request("GET", "/api/hermes/health", token=self.token)
        self.check(section, "GET /api/hermes/health", r, bool(r and r.status_code == 200), "200 from Hermes", f"status={r.status_code if r else 'no response'}")
        r = self.request("POST", "/api/hermes/auth/status", token=self.token)
        self.check(section, "POST /api/hermes/auth/status", r, bool(r and r.status_code < 500), "auth state response, not crash", f"status={r.status_code if r else 'no response'}")
        r = self.request("GET", "/api/hermes/posts", token=self.token)
        self.check(section, "GET /api/hermes/posts", r, bool(r and r.status_code == 200), "200 list", f"status={r.status_code if r else 'no response'}")
        self.skip(section, "POST draft and media URL", "requires a real Hermes Instagram account; the test must not forge one or publish")

    def infra_and_edges(self) -> None:
        section = "9. CELERY + REDIS"
        r = self.request("GET", "/health", token=self.token)
        self.check(section, "GET /api/health (backend /health)", r, bool(r and r.status_code == 200), "health response including worker status", f"status={r.status_code if r else 'no response'}, body={self.snippet(r)}")
        # Worker and Beat are verified from their live Compose health states, without injecting a fake task.
        try:
            out = subprocess.run(["docker", "compose", "ps", "--format", "json"], cwd=Path(__file__).parents[1], text=True, capture_output=True, check=True).stdout
            services = [json.loads(x) for x in out.splitlines() if x.strip()]
            state = {x.get("Service"): x.get("Health") or x.get("State") for x in services}
            ok = all(state.get(name) == "healthy" for name in ("redis", "celery-worker", "celery-beat"))
            self.check(section, "Compose Redis/Celery worker/Beat health", None, ok, "all healthy", f"states={state}")
        except Exception as exc: self.check(section, "Compose Redis/Celery worker/Beat health", None, False, "docker compose ps succeeds", repr(exc))

        section = "10. NGINX + INFRASTRUCTURE"
        proxy = httpx.Client(base_url=NGINX, timeout=10, verify=VERIFY_TLS, follow_redirects=False)
        for label, path, expect in (("frontend", "/", "200 frontend"), ("API proxy", "/api/health", "200 backend proxy"), ("healthz", "/healthz", "200"), ("Hermes media", "/media/hermes/", "location response")):
            try: nr = proxy.get(path)
            except httpx.HTTPError: nr = None
            self.check(section, f"GET {path} ({label})", nr, bool(nr and (nr.status_code == 200 or (path == "/media/hermes/" and nr.status_code in (403, 404)))), expect, f"status={nr.status_code if nr else 'no response'}")
        try: nr = proxy.options("/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
        except httpx.HTTPError: nr = None
        self.check(section, "OPTIONS /api/health CORS", nr, bool(nr and nr.status_code < 500 and "access-control-allow-origin" in nr.headers), "CORS headers", f"status={nr.status_code if nr else 'no response'}, headers={dict(nr.headers) if nr else {}}")
        proxy.close()

        section = "11. EDGE CASES"
        r = self.request("POST", "/jobs", token=self.token, files={"video": ("invalid.mp4", b"not a video", "video/mp4")})
        self.check(section, "invalid .txt renamed .mp4", r, bool(r and r.status_code in (400, 415, 422)), "validation error, never 500", f"status={r.status_code if r else 'no response'}")
        r = self.request("POST", "/jobs", token=self.token, content=b"{broken", headers={"content-type": "application/json"})
        self.check(section, "malformed JSON upload", r, bool(r and r.status_code == 422), "422", f"status={r.status_code if r else 'no response'}")
        r = self.request("GET", "/jobs")
        self.check(section, "missing auth protected endpoint", r, bool(r and r.status_code == 401), "401", f"status={r.status_code if r else 'no response'}")
        r = self.request("POST", "/content/create", token=self.token, json={"prompt": "x" * 100_000, "provider": "local_fixture"})
        self.check(section, "extremely long content prompt", r, bool(r and r.status_code < 500), "non-500 response", f"status={r.status_code if r else 'no response'}")
        r = self.request("GET", "/nonexistent", token=self.token)
        self.check(section, "GET /api/nonexistent", r, bool(r and r.status_code == 404), "404", f"status={r.status_code if r else 'no response'}")

    def summary(self) -> int:
        print("\nSUMMARY")
        print("Section name | Tests run | Passed | Failed | Skipped")
        totals = [0, 0, 0, 0]
        for g in self.groups.values():
            print(f"{g.name} | {g.run} | {g.passed} | {g.failed} | {g.skipped}")
            totals = [a + b for a, b in zip(totals, [g.run, g.passed, g.failed, g.skipped])]
        print(f"TOTAL | {totals[0]} | {totals[1]} | {totals[2]} | {totals[3]}")
        if self.failures:
            print("\nFAILURES")
            for x in self.failures:
                print(f"[{x.section}] endpoint={x.endpoint}\n  expected: {x.expected}\n  actual: {x.actual}\n  status: {x.status}\n  body: {x.body}")
        return 1 if self.failures else 0


def main() -> int:
    result = subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=320x240:d=2", "-c:v", "libx264", "-t", "2", str(VIDEO)], text=True, capture_output=True)
    if result.returncode:
        print(result.stderr, file=sys.stderr); return 2
    suite = LiveSuite()
    try:
        suite.auth(); suite.jobs_crud(); suite.plan_and_render(); suite.qc_premiere_content(); suite.hermes(); suite.infra_and_edges()
        return suite.summary()
    finally:
        suite.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
