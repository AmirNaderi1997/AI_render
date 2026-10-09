# Stage 1 prompt — paste into your coding agent (Claude Code / GPT)

Run Claude Code from the project folder: `cd ~/Documents/AI_render && claude`, then paste everything below the line.

---

You are building Stage 1 of "Rafiei AI Editor", a local AI video editor for vertical reels.
The project folder is `~/Documents/AI_render` (work only inside it). Read these 5 files first:
- `~/Documents/AI_render/plan.md`
- `~/Documents/AI_render/docs/skills.md`
- `~/Documents/AI_render/docs/stages.md`
- `~/Documents/AI_render/proof/build_mlt.py`
- `~/Documents/AI_render/proof/plan.json`

Stage 1 has NO AI: a hand-written JSON
edit plan goes in, a rendered MP4 and a Kdenlive-openable project come out, driven from a small local web UI.

## Stack (fixed, do not substitute)
- Python 3.11+, FastAPI, Pydantic v2
- MLT (`melt` CLI) for timeline + render, FFmpeg/ffprobe for probing, libass (via MLT `avfilter.subtitles`) for captions
- Frontend: React + Vite + TypeScript (keep it simple, no UI framework required)
- Runs on macOS (`brew install ffmpeg mlt`) and Linux. No Premiere, no After Effects, no cloud services.

## Starting point
`proof/build_mlt.py` + `proof/plan.json` already work end to end (tested with melt 7.22): cuts, affine
punch-in zoom, ASS captions, B-roll on V2, music with volume ducking, SFX, H.264/AAC export.
Refactor it into a proper package; keep its MLT approach. Known gotchas:
- Declare every `<producer>` outside `<playlist>` elements, or MLT treats it as a playlist item.
- Convert seconds to frames with `round(sec * fps)`; entry `out` is inclusive (`out = in + n - 1`).
- Audio tracks need `mix` transitions with `sum=1` and `always_active=1`; video overlay uses the `affine` transition.
- Captions: generate ASS with PlayResX/PlayResY = canvas size, apply `avfilter.subtitles` on the tractor.
- Resolve all media paths to absolute paths in the generated MLT.

## Deliverables
1. Repo layout:
   ```
   engine/   schema.py  build_mlt.py  captions.py  render.py  probe.py  kdenlive.py  __main__.py
   app/      main.py (FastAPI)  jobs.py
   web/      React app
   samples/  plans for each feature + a script that generates synthetic test media with ffmpeg
   tests/
   jobs/     (runtime, gitignored)
   ```
2. `engine/schema.py`: Pydantic model for Edit Plan v0.1 exactly as in plan.md (canvas, source, segments with
   zoom, captions with style normal|emphasis|cta, broll, music with duck ranges, sfx, export). Validate:
   in < out, times >= 0, zoom 1.0 to 1.5, files exist, segments inside source duration (via ffprobe),
   captions/broll/sfx inside output duration. Return readable errors (field path + reason).
3. `engine/build_mlt.py`: plan -> `project.mlt` + `captions.ass`. Tracks: V1 kept segments (affine zoom
   keyframes, 6-frame punch-in or slow zoom over the whole segment), V2 B-roll, A1 music (volume `level`
   keyframes in dB for ducking, 0.8 s fade out), A2 SFX. Caption styles come from `presets/rafiei_reel.yaml`
   (font, size, colours, outline, bottom margin) so they are not hard-coded.
4. `engine/render.py`: final render (`melt project.mlt -consumer avformat:out.mp4 vcodec=libx264 crf=20
   preset=medium acodec=aac ab=192k`) and a fast preview (540x960, veryfast). Parse melt progress
   (`-progress`) into a 0-100 percentage. Optional loudness pass `ffmpeg -af loudnorm=I=-14:TP=-1.5`.
5. `engine/kdenlive.py`: produce a file Kdenlive can open for manual editing. First try opening the plain
   `.mlt`; if Kdenlive needs its own metadata, generate a `.kdenlive` file. Document what you verified.
6. CLI: `python -m engine validate plan.json`, `python -m engine build plan.json`, `python -m engine render plan.json [--preview]`.
7. FastAPI: `POST /jobs` (upload raw video + optional plan.json), `GET /jobs/{id}`, `PUT /jobs/{id}/plan`
   (validates), `POST /jobs/{id}/render?preview=bool`, `GET /jobs/{id}/render/status`,
   `GET /jobs/{id}/exports/{file}`, `POST /jobs/{id}/open-kdenlive` (launches Kdenlive locally with the project).
   Renders run in a background worker; one job folder per job under `jobs/<id>/`.
8. Web UI with three screens:
   - **New Reel**: drag-and-drop raw video, paste or upload plan.json, style dropdown (only "Rafiei Reel Style" for now), Create.
   - **Plan Review**: video player of the raw clip; JSON editor with live validation errors; read-only
     timeline with coloured lanes (Segments kept/removed, Zoom, Captions, B-roll, Music, SFX), clicking an item
     seeks the player; buttons Preview, Render, Open in Kdenlive, Download plan.json.
   - **Render**: progress bar, MP4 player for the result, download, list of previous versions (v1, v2...).
9. Tests (pytest): generate synthetic media with ffmpeg (testsrc2 + tone with silent gaps, a B-roll clip,
   music, a whoosh), then for each feature render a sample plan and assert with ffprobe: 1080x1920, 30 fps,
   duration = sum of segments (+-1 frame), audio stream present and same length as video. Add a schema test
   for each validation rule.
10. README: install steps for macOS and Linux, how to run backend + frontend, how to run tests.

## Done when
- `pytest` passes.
- Using the UI only, I upload one of my real raw videos with a hand-written plan and get a 1080x1920 MP4 with
  all 7 features: cut, pause removal, zoom, subtitles, music, SFX, B-roll.
- The same project opens in Kdenlive with all tracks visible.

## Rules
- Do not add AI, Whisper or LLM calls yet (that is Stage 2). Keep the code ready for it: the plan is the only contract.
- Keep it small and readable; no extra services, databases or Docker.
- When done, report: what works, what you verified and how, anything not verified, and exact commands to run.
