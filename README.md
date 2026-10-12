# Rafiei AI Editor — Stages 1–3

Local video editor for vertical reels. **Stage 1** renders a hand-written JSON
Edit Plan to 1080×1920 MP4. **Stage 2** adds AI plan generation, transcription,
corrections, and the visual-effect catalog. **Stage 3** adds explicit,
frame-accurate boundary transitions and an editable Premiere Pro interchange
package. The plan JSON stays the only contract.

## Install

### macOS

```bash
brew install ffmpeg mlt
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd web && npm install && cd ..
```

### Linux (Debian/Ubuntu)

```bash
sudo apt install ffmpeg melt fonts-dejavu
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
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
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

Tests that need `melt` are skipped automatically if it is not on PATH (the run then reports skips). `ffmpeg`/`ffprobe` are required for the media-generation fixture. Every plan in `samples/plans/*.json` is rendered and checked with ffprobe (1080×1920, 30 fps, duration, audio).

## Repo layout

Planning and VPS handoff use [SKILLS.md](SKILLS.md), [Prompts/README.md](Prompts/README.md), [RoadMap.md](RoadMap.md), and [GuideLine.md](GuideLine.md). Both deployment scripts check that these files are present before starting.

```
engine/    schema.py build_mlt.py captions.py render.py probe.py premiere.py
           effects.py (100-preset catalog) effects_v4.py (V4 effects, My Effects) __main__.py
brain/     Stage 2: transcription, planner, corrections, glossary
app/       main.py (FastAPI) jobs.py
web/       React + Vite + TypeScript
samples/   plans/ (one plan per feature + full), scripts/make_media.py, reference/
tests/     pytest suite
presets/   rafiei_reel.yaml (caption + render style), my_effects.yaml
docs/      stages.md skills.md prompt-stage1.md premiere-format.md and reports
jobs/      runtime job folders (gitignored)
```

## Edit Plan

See [plan.md](plan.md) for the original architecture and
[the Premiere/transition contract](docs/premiere-format.md) for Stage 3. Times in
`segments` are on the **raw** timeline; captions, B-roll, SFX, and music-duck
times are on the overlap-aware **output** timeline.

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

## Premiere Pro

Every preview/final render creates `project_premiere.zip`. Plan Review can also
build and download the current saved plan on demand. The bundle contains an
FCP7 XML interchange sequence for Premiere import, an editable SRT sidecar, and
`premiere_transition_report.json`, which now contains the complete compatibility
manifest. AI Render does not export a native `.prproj`; import the XML in
Premiere and save the resulting project there. Plan Review offers distinct ZIP,
XML, SRT, and report links.

For true in-Premiere control, the authenticated bridge in `premiere-bridge/`
supports Premiere 25.0–25.5 through CEP/ExtendScript. After linking the exact
clean `.prproj`, **Connect inside Premiere** issues a ten-minute, one-use pairing
code. The panel verifies the active project, finds or imports the sequence,
opens it in the Timeline, imports the rendered reference, creates the caption
track, saves, and returns a structured complete/partial/failed receipt. The
macOS Open/Reveal actions remain clearly labeled file-handoff fallbacks. See
[the desktop integration notes](docs/premiere-desktop-integration.md).

Import `project_premiere.xml` into Premiere, then import
`premiere_captions.srt` separately as the caption track. Crossfades transfer as
Cross Dissolve and audio Cross Fade (+3dB). Directional transitions are editable
Cross Dissolve fallbacks. Boundary zoom renders through MLT; the XML currently
proposes a Cross Dissolve mapping, but that zoom mapping remains `unverified`
until native import, save, and reopen inspection. Segment visual effects remain
in the rendered MP4. The manifest and Plan Review identify these mappings and
the MP4 remains visually authoritative for every fallback or rendered-only
feature. See
[the format notes](docs/premiere-format.md).

## Done-when checklist

- `pytest` passes.
- From the UI: upload one raw video + hand-written plan, get a 1080×1920 MP4 with all 7 features (cut, pause removal, zoom, subtitles, music, SFX, B-roll).
- The Premiere XML package has the same frame duration as the Edit Plan and
  reports every transition mapping or limitation.
