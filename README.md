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

## AI plan and transcript review

New AI plans use Edit Plan v0.2. `visual_effects` assigns one catalog preset to a
segment by ID. The catalog has 100 presets (ten bounded framing motions times ten
light treatments); `/effects` lists them. Old plans without `visual_effects` still
use their per-segment `zoom`. The Plan Review page lets you change a segment's
effect. Automatic choices stay centered unless shot framing has been reviewed.

New Persian jobs default to the local faster-whisper `medium` model and explicit
`fa`. New Reel also accepts speech terms and an alternate model/language. A raw
transcript candidate is cached by video hash, model, language, decoding settings,
and speech terms. In Plan Review, select a word to correct its text or timing,
save those corrections, then regenerate the plan from the reviewed transcript.
"Re-transcribe only" creates another candidate without calling the plan model or
changing the existing plan. Raw ASR candidates and corrections are kept separately
under the job directory. Low-confidence words and captions that need audio review
are flagged; final render asks for confirmation that marked captions were checked.

ASR confidence is not proof of the spoken wording. Review disputed words against
the source audio, especially before final export.

## Kdenlive

`POST /jobs/{id}/open-kdenlive` builds and opens a companion `project.kdenlive`
from `project.mlt`. The sample project can be regenerated with:

```bash
python -m engine build samples/plans/full.json
python -c "from engine.kdenlive import build_kdenlive; build_kdenlive('samples/plans/project.mlt')"
```

The Kdenlive project contains four editable tracks: V1 raw cuts and zoom, V2
B-roll, A1 music with volume keyframes, and A2 SFX. The rendered MP4 has
captions; the Kdenlive project leaves caption ASS/SRT sidecars for manual
import because a native subtitle lane has not been verified. See
[the format notes](docs/kdenlive-format.md) and [source fixtures](samples/reference/README.md).

## Done-when checklist

- `pytest` passes.
- From the UI: upload one raw video + hand-written plan, get a 1080×1920 MP4 with all 7 features (cut, pause removal, zoom, subtitles, music, SFX, B-roll).
- The same project opens in Kdenlive with all tracks visible.
