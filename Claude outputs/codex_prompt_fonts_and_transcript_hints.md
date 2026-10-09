# Codex Prompt — Font Selector + AI Voice Hint Points Feature

## Context

This is the **AI_render** project (Rafiei AI Editor). It is a FastAPI + React/TypeScript app for AI-assisted video editing with:
- **Backend**: `app/main.py` (FastAPI), `engine/captions.py`, `engine/schema.py`, `brain/transcribe.py`
- **Frontend**: `web/src/` (React + TypeScript, Vite)
- **Preset system**: `presets/rafiei_reel.yaml` — defines `captions.persian_font`, `captions.fonts_dir`, etc.
- **Fonts live in**: `presets/fonts/` (currently only `Vazirmatn-Regular.ttf`)

---

## Task 1 — Add New Persian Fonts to the Font Selector

### New font files to install
Copy the following font files into `presets/fonts/`:
- `IRAN_Kharazmi/` (extract from zip, place the TTF/OTF inside `presets/fonts/IRAN_Kharazmi/`)
- `maneli/` (extract from zip, place the TTF/OTF inside `presets/fonts/maneli/`)
- `RAY-BLACK.TTF`, `RAY-BOLD.TTF`, `RAY-EXTRABLACK.TTF`, `RAY-EXTRABOLD.TTF`, `RAY-LIGHT.TTF`, `RAY-MEDIUM.TTF`, `RAY.TTF` — place directly in `presets/fonts/`

### Backend changes

#### 1. `app/main.py` — Add a `/fonts` endpoint
```python
@app.get("/fonts")
def list_fonts():
    """Return available font names from presets/fonts/."""
    from engine.captions import fonts_dir, load_style
    style = load_style("rafiei_reel")
    d = fonts_dir(style)
    if not d or not d.is_dir():
        return {"fonts": ["Vazirmatn"]}
    fonts = set()
    for f in d.rglob("*"):
        if f.suffix.lower() in (".ttf", ".otf"):
            # Use stem as display name; strip weight suffixes for RAY family
            fonts.add(f.stem)
    return {"fonts": sorted(fonts)}
```

#### 2. `engine/schema.py` — Add `caption_font` optional field to the plan canvas or caption style
In the `Canvas` or the preset's caption base, allow an optional `caption_font: str` field. If set, it overrides `persian_font` and `base.font` for the entire render.

#### 3. `engine/captions.py` — Respect `caption_font` from the plan
In `build_ass()` and the MLT subtitle path, check if `plan.canvas.caption_font` (or a new top-level plan field) is set and use it as the font name instead of the preset default.

```python
# In build_ass(), after computing `base`:
if hasattr(plan, 'caption_font') and plan.caption_font:
    base = {**base, "font": plan.caption_font}
elif _plan_is_persian(plan) and "persian_font" in cap:
    base = {**base, "font": cap["persian_font"]}
```

#### 4. `app/main.py` — Accept `caption_font` in `GenerateBody` and pass it through
```python
class GenerateBody(BaseModel):
    ...
    caption_font: Optional[str] = None
```
Pass `caption_font` to the plan generator / job store so it is saved in `plan.json`.

### Frontend changes (`web/src/`)

#### 1. `api.ts` — Add `listFonts()` method
```typescript
async listFonts(): Promise<{ fonts: string[] }> {
  return j(await fetch(`${BASE}/fonts`));
},
```
Also add `caption_font?: string` to the `generatePlan` opts interface.

#### 2. `NewReel.tsx` — Add font dropdown in the Style card
- On mount, call `api.listFonts()` and store the result in state.
- Add a `<select>` for `captionFont` below the transcription settings (step 2 card).
- Include a "Default (preset)" option as the first item.
- Pass `caption_font: captionFont || undefined` in the `onGenerate` call to `api.generatePlan()`.

```tsx
const [captionFont, setCaptionFont] = React.useState("");
const [availableFonts, setAvailableFonts] = React.useState<string[]>([]);

React.useEffect(() => {
  api.listFonts().then(r => setAvailableFonts(r.fonts)).catch(() => {});
}, []);

// In JSX, inside the Style card:
<label>Caption font:
  <select value={captionFont} onChange={e => setCaptionFont(e.target.value)}>
    <option value="">Default (preset)</option>
    {availableFonts.map(f => <option key={f} value={f}>{f}</option>)}
  </select>
</label>
```

#### 3. `PlanReview.tsx` — Show current font and allow changing it per-job
- In the plan editor section, add a font selector that reads `plan.canvas.caption_font` and allows changing it.
- On change, call `api.putPlan()` with the updated plan (set `plan.canvas.caption_font = newFont`).

---

## Task 2 — AI Voice Hint Points: Show Transcript Before Video Playback

### Goal
After the AI transcribes the audio, extract **key content moments** (hint points) from the transcript using an LLM call, then display the full transcript text to the user **before** they play the video — so they can review what was said before watching.

### Backend changes

#### 1. `brain/hint_points.py` — NEW FILE
Create a new module that:
1. Takes the transcript (list of `{w, start, end}` words and `sentences`)
2. Calls the LLM (reuse `brain/llm.py` pattern) with a prompt asking it to identify key moments
3. Returns a list of hint points: `[{"time": float, "label": str, "importance": "high"|"medium"}]`

```python
"""Extract hint points (key moments) from a transcript using the LLM."""
from __future__ import annotations
from typing import Optional
from .llm import call_llm   # reuse existing LLM wrapper

SYSTEM_PROMPT = """
You are an AI video editor assistant. Given a speech transcript, identify the most important
moments (hint points): key claims, turning points, emotional peaks, calls to action, or topic shifts.

Return JSON: {"hint_points": [{"time": <seconds float>, "label": "<short Persian label>", "importance": "high"|"medium"}]}

Rules:
- Label must be in the same language as the transcript (Persian or English).
- Maximum 8 hint points.
- Only mark genuinely important moments, not every sentence.
- time must match a word start time from the transcript.
"""

def extract_hint_points(transcript: dict, language: str = "fa") -> list[dict]:
    sentences = transcript.get("sentences", [])
    words = transcript.get("words", [])
    if not sentences and not words:
        return []
    
    # Build a compact text representation with timestamps
    lines = []
    for s in sentences:
        lines.append(f"[{s['start']:.1f}s] {s['text']}")
    text_with_times = "\n".join(lines) if lines else "\n".join(
        f"[{w['start']:.1f}s] {w['w']}" for w in words[::3]  # sample every 3rd word
    )
    
    user_msg = f"Transcript:\n{text_with_times}\n\nExtract hint points."
    
    try:
        result = call_llm(system=SYSTEM_PROMPT, user=user_msg, expect_json=True)
        return result.get("hint_points", [])
    except Exception:
        return []
```

#### 2. `app/main.py` — Add `/jobs/{job_id}/hint-points` endpoint
```python
@app.get("/jobs/{job_id}/hint-points")
def get_hint_points(job_id: str):
    """Return AI-extracted hint points from the transcript."""
    job = jobstore.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    p = job.dir / "hint_points.json"
    if p.exists():
        return json.loads(p.read_text())
    # Generate on demand if transcript exists
    transcript_path = job.dir / "transcript.json"
    if not transcript_path.exists():
        raise HTTPException(404, "transcript not ready yet")
    from brain.hint_points import extract_hint_points
    from brain.transcribe import effective_transcript
    transcript = effective_transcript(job.dir)
    points = extract_hint_points(transcript.__dict__ if hasattr(transcript, '__dict__') else dict(transcript))
    result = {"hint_points": points}
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
```

Also: in `jobs.py` / the generate pipeline — after transcription completes and before the full plan generation, automatically extract hint points and save to `hint_points.json` in the job dir.

#### 3. `app/main.py` — Include `hint_points` flag in `GET /jobs/{job_id}` response
```python
hint_points_path = job.dir / "hint_points.json"
if hint_points_path.exists():
    d["has_hint_points"] = True
```

### Frontend changes (`web/src/`)

#### 1. `api.ts` — Add types and method
```typescript
export interface HintPoint {
  time: number;
  label: string;
  importance: "high" | "medium";
}

export interface HintPoints {
  hint_points: HintPoint[];
}

// In api object:
async getHintPoints(id: string): Promise<HintPoints> {
  return j(await fetch(`${BASE}/jobs/${id}/hint-points`));
},
```

#### 2. `PlanReview.tsx` — Show transcript summary panel BEFORE the video player

At the top of the job review page (before the `<video>` element), add a **"Transcript Overview"** panel that:

1. Fetches hint points when `job.has_hint_points` is true (or `job.has_transcript` is true — fetch on demand).
2. Shows the full transcript text as readable Persian/English paragraphs (from `transcript.sentences`).
3. Overlays the hint points as labeled markers on a horizontal timeline bar.
4. Lets the user click a hint point to seek the video to that time.

```tsx
// New component: TranscriptPreviewPanel
function TranscriptPreviewPanel({ jobId, transcript, hintPoints, onSeek }: {
  jobId: string;
  transcript: Transcript | null;
  hintPoints: HintPoint[];
  onSeek: (t: number) => void;
}) {
  const duration = transcript ? transcript.duration : 0;

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h2>📄 Transcript Overview</h2>
      {/* Full text */}
      {transcript && (
        <p dir="auto" style={{ lineHeight: 1.8, fontSize: 15, marginBottom: 12 }}>
          {transcript.sentences.map((s, i) => (
            <span
              key={i}
              style={{ cursor: "pointer" }}
              onClick={() => onSeek(s.start)}
              title={`${s.start.toFixed(1)}s`}
            >
              {s.text}{" "}
            </span>
          ))}
        </p>
      )}
      {/* Hint points timeline */}
      {hintPoints.length > 0 && duration > 0 && (
        <div style={{ position: "relative", height: 32, background: "#1e293b", borderRadius: 4, marginBottom: 8 }}>
          {/* track bar */}
          <div style={{ position: "absolute", top: 14, left: 0, right: 0, height: 4, background: "#334155", borderRadius: 2 }} />
          {hintPoints.map((hp, i) => (
            <button
              key={i}
              onClick={() => onSeek(hp.time)}
              title={hp.label}
              style={{
                position: "absolute",
                left: `${(hp.time / duration) * 100}%`,
                top: 4,
                transform: "translateX(-50%)",
                width: 10, height: 24,
                background: hp.importance === "high" ? "#f59e0b" : "#60a5fa",
                border: "none", borderRadius: 3, cursor: "pointer", padding: 0,
              }}
            />
          ))}
        </div>
      )}
      {/* Hint point labels */}
      {hintPoints.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
          {hintPoints.map((hp, i) => (
            <button
              key={i}
              className="secondary"
              style={{ fontSize: 12, padding: "2px 8px",
                borderColor: hp.importance === "high" ? "#f59e0b" : undefined }}
              onClick={() => onSeek(hp.time)}
            >
              ▶ {hp.label} <span className="muted">({hp.time.toFixed(0)}s)</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

Place this component **above** the video player in `PlanReview.tsx`. Load hint points alongside the transcript with `api.getHintPoints(id)` in the same `useEffect` that loads the transcript.

---

## Summary of all files to change

| File | Change |
|------|--------|
| `presets/fonts/` | Add new font files (copy TTFs) |
| `presets/rafiei_reel.yaml` | (optional) Update `persian_font` default |
| `engine/schema.py` | Add optional `caption_font` field to Canvas model |
| `engine/captions.py` | Respect `caption_font` override in `build_ass()` |
| `brain/hint_points.py` | **NEW** — LLM hint point extractor |
| `app/main.py` | Add `/fonts` endpoint, `/hint-points` endpoint, `caption_font` in GenerateBody |
| `web/src/api.ts` | Add `listFonts()`, `getHintPoints()`, types |
| `web/src/NewReel.tsx` | Font selector dropdown in step 2 |
| `web/src/PlanReview.tsx` | TranscriptPreviewPanel + hint point timeline above video |

---

## Acceptance criteria

1. **Font selector**: The dropdown in NewReel shows all font files from `presets/fonts/`. Selecting one causes the rendered captions to use that font. Selecting "Default" uses the preset default (`Vazirmatn` for Persian).
2. **Hint points**: After transcription, the review page shows the full transcript text above the video with clickable sentences. A timeline bar shows colored markers at key moments. Clicking a marker or label seeks the video to that time.
3. **No regression**: Existing jobs without hint points load normally. Font defaults to preset if none selected.
