# Rafiei AI Editor — Stage 1

Local AI video editor for vertical reels. Stage 1 has **no AI**: a hand-written JSON edit plan goes in, a rendered 1080×1920 MP4 and a Kdenlive-openable project come out, driven from a small local web UI.

## Install

### macOS

```bash
brew install ffmpeg mlt
# Kdenlive: download the .dmg from https://kdenlive.org
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd web && npm install && cd ..
```

### Linux (Debian/Ubuntu)

```bash
sudo apt install ffmpeg melt kdenlive fonts-dejavu
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd web && npm install && cd ..
```

Verify the tools:

```bash
melt --version && ffmpeg -version | head -1 && ffprobe -version | head -1
```

## Run

Backend (FastAPI, port 8000):

```bash
uvicorn app.main:app --reload --port 8000
```

Frontend (Vite, port 5173, proxies `/api` → 8000):

```bash
cd web && npm run dev
```

Open http://localhost:5173.

## CLI

```bash
# Generate synthetic test media (needs ffmpeg)
python samples/scripts/make_media.py

# Validate a plan
python -m engine validate samples/plans/full.json

# Build project.mlt + captions.ass (does not render)
python -m engine build samples/plans/full.json --out /tmp/rafiei_out

# Render to MP4 (final)
python -m engine render samples/plans/full.json

# Fast preview (540x960, veryfast)
python -m engine render samples/plans/full.json --preview
```

Render output goes to the `export.file` path in the plan (relative paths are resolved next to the plan file).

## Tests

```bash
pytest -q
```

Tests that need `melt` are skipped automatically if it is not on PATH. `ffmpeg` is required for the media-generation fixture.

## Repo layout

```
engine/    schema.py build_mlt.py captions.py render.py probe.py kdenlive.py __main__.py
app/       main.py (FastAPI) jobs.py
web/       React + Vite + TypeScript
samples/   plans/, scripts/make_media.py
tests/     pytest suite
presets/   rafiei_reel.yaml (caption + render style)
jobs/      runtime job folders (gitignored)
```

## Edit Plan v0.1

See [plan.md](plan.md) for the schema. Times in `segments` are on the **raw** timeline; caption / broll / sfx / music-duck times are on the **output** timeline (the concatenation of kept segments).

## Kdenlive

`POST /jobs/{id}/open-kdenlive` opens the generated `project.mlt` in Kdenlive.

- **macOS:** we call `open -a Kdenlive project.mlt` (the app bundle is auto-detected).
- **Linux:** we call `kdenlive project.mlt`.

Verified path: plain `.mlt` opens with V1 (kept segments), V2 (B-roll), A1 (music), A2 (SFX) all visible, captions rendered via `avfilter.subtitles`. If a session needs richer Kdenlive metadata (track colours, guide markers, etc.), extend `engine/kdenlive.py`.

## Done-when checklist

- `pytest` passes.
- From the UI: upload one raw video + hand-written plan, get a 1080×1920 MP4 with all 7 features (cut, pause removal, zoom, subtitles, music, SFX, B-roll).
- The same project opens in Kdenlive with all tracks visible.
