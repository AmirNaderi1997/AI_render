# Codex Prompt — Rafiei Styles in My Effects + Hint Colors + Auto-Effect & Font-Selector Verification

## What the 5 reference videos show (visual analysis)

After reviewing all 5 Rafiei videos frame-by-frame, the consistent visual style across all of them is:

| Video | Dominant look |
|-------|--------------|
| aeauccxbvy | Podcast setting, casual black shirt, warm plant BG. White subs + yellow/gold emphasis words. Small "Founder of RAFIEI HOLDING" lower-third credit, semi-transparent dark box under subs. |
| e08g5p7u8h | Office setting, beige suit. White subs + **cyan/teal** emphasis on key word. Reza Rafiei signature watermark. |
| i3dlpr04oa | Office, dark formal suit, red tie. White subs + **cyan** emphasis. Same watermark. |
| mf0fjqmi30 | Podcast, black shirt, side-look cuts. White subs + **yellow** emphasis. Numbered intro title overlay full-width. |
| pvsup737on | Formal desk, black suit. **Large bold opening title** at very top (dark pill bg), smaller sub-title below, same yellow emphasis. Reza Rafiei logo watermark bottom. |

**Shared Rafiei style patterns observed across all videos:**
1. **Caption layout**: Normal captions white, emphasis word in a contrasting color (gold `#FFD700` or cyan `#00E5FF`) — single keyword highlight per caption line.
2. **Opening title card**: Bold, large, centered upper zone — used as a hook in the first 1–3 seconds with a semi-transparent dark pill/box background.
3. **Cuts**: Frequent jump-cuts, 2–5 sec per segment, speaker-reactive (cuts on pauses/gestures).
4. **No heavy motion effects** — no camera shake, no RGB split. Camera is static or slow push/pull.
5. **Color grade**: Warm/neutral. No heavy LUTs visible.
6. **Watermark**: "رضا رفیعی / Reza Rafiei" calligraphic signature at the bottom center, small.
7. **Credit lower-third**: Semi-transparent pill tag — "Founder of RAFIEI HOLDING" appears on some videos.

---

## Task 1 — Add "Rafiei Styles" preset section to My Effects page

### Backend changes

#### 1. `presets/rafiei_reel.yaml` — Add Rafiei-specific effect rules
Under an existing or new `rafiei_style:` key, document the preferred effect set observed:

```yaml
rafiei_style:
  caption_emphasis_color: "#FFD700"   # gold for numbers/key words
  caption_emphasis_alt_color: "#00E5FF" # cyan for contrast moments
  opening_title: true                  # always add opening-title hook segment
  preferred_effects:
    - steady__neutral           # static camera, most segments
    - slow_push__neutral        # gentle push for building moments
    - punch__neutral            # quick punch-in on a key word
    - slow_pull__neutral        # pull out for wide/reflective moments
  avoid_effects:
    - camera_shake
    - rgb_split
    - zoom_blur_transition
    - emoji_sticker_pop
  watermark:
    text: "رضا رفیعی"
    font: "maneli"             # script/calligraphic font
    position: "bottom_center"
    opacity: 0.7
    size: 28
  credit_lower_third:
    text: "Founder of RAFIEI HOLDING"
    font: "RAY-MEDIUM"
    show_on_intro: true
```

#### 2. `app/main.py` — Add `GET /rafiei-styles` endpoint
This endpoint returns the curated Rafiei style presets as structured data the UI can display and apply:

```python
@app.get("/rafiei-styles")
def get_rafiei_styles():
    """Return Rafiei-style presets for My Effects page."""
    import yaml
    p = PROJECT_ROOT / "presets" / "rafiei_reel.yaml"
    style = yaml.safe_load(p.read_text())
    rafiei = style.get("rafiei_style", {})
    return {
        "preferred_effects": rafiei.get("preferred_effects", []),
        "avoid_effects": rafiei.get("avoid_effects", []),
        "caption_emphasis_color": rafiei.get("caption_emphasis_color", "#FFD700"),
        "caption_emphasis_alt_color": rafiei.get("caption_emphasis_alt_color", "#00E5FF"),
        "opening_title": rafiei.get("opening_title", True),
        "watermark": rafiei.get("watermark", {}),
        "credit_lower_third": rafiei.get("credit_lower_third", {}),
    }
```

#### 3. `app/main.py` — Add `POST /my-effects/apply-rafiei` endpoint
Applies the Rafiei style preset to the user's `my_effects.yaml` in one click:

```python
@app.post("/my-effects/apply-rafiei")
def apply_rafiei_style():
    """One-click: apply Rafiei style to My Effects (set favorites, rules, dislikes)."""
    from engine.effects_v4 import MyEffectsPreset
    import yaml
    style = yaml.safe_load((PROJECT_ROOT / "presets" / "rafiei_reel.yaml").read_text())
    rafiei = style.get("rafiei_style", {})

    my = MyEffectsPreset()
    # Set preferred effects as favorites with weight 1.5
    for eff_id in rafiei.get("preferred_effects", []):
        my.favorites[eff_id] = {"weight": 1.5, "tags": ["rafiei"]}
    # Add Rafiei rules
    rafiei_rules = [
        {"text": "روی کلمات کلیدی و اعداد زوم ملایم — punch__neutral", "priority": "hard"},
        {"text": "هیچ‌وقت camera_shake یا rgb_split نزن — سبک رفیعی استاتیک است", "priority": "hard"},
        {"text": "اوایل ویدیو حتماً opening title با قلم بولد نمایش بده", "priority": "hard"},
        {"text": "روی جملات احساسی slow_push استفاده کن", "priority": "soft"},
        {"text": "بین بخش‌های اصلی slow_pull برای تنفس بزن", "priority": "soft"},
    ]
    # Merge, don't duplicate
    existing_texts = {r["text"] for r in my.rules}
    for rule in rafiei_rules:
        if rule["text"] not in existing_texts:
            my.rules.append(rule)
    # Add dislikes
    for eff_id in rafiei.get("avoid_effects", []):
        my.dislikes.add(eff_id)
    my.save()
    return {"ok": True, "applied": "rafiei_style"}
```

---

## Task 2 — Add hint colors to all effects on My Effects page

### Visual specification (from video analysis)
Color-code each effect card by its `energy` and `mood`:

| Energy level | Card left-border / badge color |
|---|---|
| 5 (max) | `#ef4444` red |
| 4 | `#f97316` orange |
| 3 | `#eab308` yellow |
| 2 | `#22c55e` green |
| 1 (calm) | `#3b82f6` blue |

Also add a small mood badge text on each card (e.g. "tension", "intimate", "building").

### `web/src/MyEffects.tsx` — Full rewrite of the effect grid section

The `Effect` interface needs to be extended with the new fields the API now returns. Update `api.ts`'s `EffectPreset` type and `listEffects()` first (see api.ts change below), then update `MyEffects.tsx`:

#### `web/src/api.ts` — Extend `EffectPreset` type
```typescript
export interface EffectPreset {
  id: string;
  motion: string;
  light: string;
  label: string;
  description: string;
  energy?: number;         // 1-5
  mood?: string;           // "tension" | "intimate" | "building" | "punctuation" | "cinematic" | etc
  best_roles?: string[];
  category?: string;       // "motion" | "light" | "glitch" | "overlay" | "text" | "transition"
  hint_color?: string;     // computed from energy; can also be returned by backend directly
}

// Also add:
export interface RafieiStyle {
  preferred_effects: string[];
  avoid_effects: string[];
  caption_emphasis_color: string;
  caption_emphasis_alt_color: string;
  opening_title: boolean;
  watermark: { text: string; font: string; position: string; opacity: number; size: number };
  credit_lower_third: { text: string; font: string; show_on_intro: boolean };
}

// In api object add:
async getRafieiStyles(): Promise<RafieiStyle> {
  return j(await fetch(`${BASE}/rafiei-styles`));
},
async applyRafieiStyle(): Promise<{ ok: boolean }> {
  return j(await fetch(`${BASE}/my-effects/apply-rafiei`, { method: "POST" }));
},
```

#### `web/src/MyEffects.tsx` — Full updated component

Key changes:
1. Load `api.getRafieiStyles()` alongside effects and my-effects.
2. Add `ENERGY_COLORS` map and `hintColor(eff)` helper.
3. Add a **"Rafiei Styles" section** above Favorites — shows the 5 preferred effects as preview cards, plus an "Apply Rafiei Style →" button.
4. Each effect card now shows:
   - A left color bar matching its energy level.
   - A small badge with `mood` text.
   - Tooltip with `description` and `best_roles`.
5. Favorites section becomes a two-column grid (label + hint color + description snippet).

```tsx
import React from "react";
import { api, EffectPreset, RafieiStyle } from "./api";

const ENERGY_COLORS: Record<number, string> = {
  5: "#ef4444",
  4: "#f97316",
  3: "#eab308",
  2: "#22c55e",
  1: "#3b82f6",
};

function hintColor(eff: EffectPreset): string {
  return ENERGY_COLORS[eff.energy ?? 3] ?? "#94a3b8";
}

export default function MyEffects() {
  const [effects, setEffects] = React.useState<EffectPreset[]>([]);
  const [myEffects, setMyEffects] = React.useState<any>(null);
  const [rafiei, setRafiei] = React.useState<RafieiStyle | null>(null);
  const [editMode, setEditMode] = React.useState(false);
  const [newRule, setNewRule] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [applyingRafiei, setApplyingRafiei] = React.useState(false);

  React.useEffect(() => {
    Promise.all([
      api.listEffects().then(setEffects),
      fetch("/api/my-effects").then(r => r.json()).then(setMyEffects),
      api.getRafieiStyles().then(setRafiei).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  async function handleApplyRafiei() {
    setApplyingRafiei(true);
    try {
      await api.applyRafieiStyle();
      const updated = await fetch("/api/my-effects").then(r => r.json());
      setMyEffects(updated);
    } finally {
      setApplyingRafiei(false);
    }
  }

  const handleToggleFavorite = (effectId: string) => { /* same as before */ };
  const handleAddRule = () => { /* same as before */ };
  const handleRemoveRule = (idx: number) => { /* same as before */ };

  if (loading) return <div>Loading…</div>;
  if (!myEffects) return <div>Error loading My Effects</div>;

  const effectById = Object.fromEntries(effects.map(e => [e.id, e]));

  return (
    <div className="my-effects">
      <h1>My Effects</h1>

      {/* ── Rafiei Styles Section ─────────────────────────── */}
      {rafiei && (
        <section>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>🎬 Rafiei Styles</h2>
            <button
              onClick={handleApplyRafiei}
              disabled={applyingRafiei}
              style={{ background: "#2563eb", color: "#fff", border: "none", borderRadius: 6,
                padding: "6px 14px", cursor: "pointer", fontSize: 13 }}
            >
              {applyingRafiei ? "Applying…" : "Apply Rafiei Style →"}
            </button>
          </div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 12 }}>
            Based on 5 Rafiei reference videos: static camera, gentle push/pull,
            yellow/cyan emphasis captions, bold opening title, no shake/glitch.
          </p>
          <div className="effect-grid">
            {rafiei.preferred_effects.map(id => {
              const eff = effectById[id];
              if (!eff) return null;
              const color = hintColor(eff);
              return (
                <div key={id} className="effect-card rafiei-preferred"
                  style={{ borderLeftColor: color }}
                  title={eff.description}>
                  <div className="effect-label">{eff.label}</div>
                  {eff.mood && <span className="mood-badge" style={{ background: color + "22", color }}>{eff.mood}</span>}
                  <div className="effect-desc">{eff.description}</div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 10, fontSize: 12 }} className="muted">
            Avoid: {rafiei.avoid_effects.join(", ")}
          </div>
        </section>
      )}

      {/* ── Favorites Section ─────────────────────────────── */}
      <section>
        <h2>Favorites</h2>
        <div className="effect-grid">
          {effects.map(eff => {
            const isFav = !!myEffects.favorites[eff.id];
            const color = hintColor(eff);
            return (
              <div
                key={eff.id}
                className={`effect-card ${isFav ? "favorite" : ""}`}
                style={{ borderLeftColor: color }}
                onClick={() => handleToggleFavorite(eff.id)}
                title={eff.description + (eff.best_roles?.length ? `\nBest for: ${eff.best_roles.join(", ")}` : "")}
              >
                <div className="effect-label">{eff.label}</div>
                {eff.mood && (
                  <span className="mood-badge" style={{ background: color + "22", color }}>
                    {eff.mood}
                  </span>
                )}
                <div className="effect-star">{isFav ? "★" : "☆"}</div>
                {isFav && (
                  <input type="range" min="0.5" max="2" step="0.1"
                    defaultValue={myEffects.favorites[eff.id].weight || 1.0}
                    onClick={e => e.stopPropagation()}
                    onChange={e => { /* same weight update as before */ }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* ── My Rules ──────────────────────────────────────── */}
      <section>
        <h2>My Rules</h2>
        {/* same rules UI as before */}
      </section>

      <style>{`
        .my-effects { padding: 2rem; max-width: 1200px; margin: 0 auto; }
        h2 { font-size: 1.3rem; margin-top: 2rem; margin-bottom: 1rem; }
        .effect-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
          gap: 1rem;
        }
        .effect-card {
          border: 2px solid #334155;
          border-left: 5px solid #94a3b8;  /* overridden inline */
          border-radius: 8px;
          padding: 10px 10px 10px 8px;
          cursor: pointer;
          transition: all 0.15s;
          position: relative;
          background: #0f172a;
        }
        .effect-card:hover { background: #1e293b; }
        .effect-card.favorite { border-top-color: #ffd700; background: #1e1a00; }
        .effect-card.rafiei-preferred { border-top-color: #2563eb; }
        .effect-label { font-weight: 600; font-size: 0.85rem; margin-bottom: 4px; }
        .effect-desc { font-size: 0.72rem; color: #94a3b8; margin-top: 4px; line-height: 1.3; }
        .mood-badge {
          display: inline-block;
          font-size: 0.65rem;
          padding: 1px 6px;
          border-radius: 99px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: 0.04em;
          margin-bottom: 2px;
        }
        .effect-star { font-size: 1.2rem; margin: 4px 0; }
        input[type="range"] { width: 100%; cursor: pointer; margin-top: 6px; }
        /* rules same as before */
      `}</style>
    </div>
  );
}
```

---

## Task 3 — Verify and fix auto-effect selection

### What to check

#### Backend: `engine/effects_v4.py` — `catalog_for_api()` function
The `/effects` endpoint calls `catalog_for_api()`. Verify it returns **both** the legacy catalog AND `EXTENDED_EFFECTS`:

```python
def catalog_for_api() -> list[dict]:
    """Return all effects (legacy + V4 extended) for the frontend."""
    result = []
    # Legacy effects from v3
    for eff_id, eff in _LEGACY_CATALOG.items():
        result.append({
            "id": eff_id,
            "motion": eff.get("motion", ""),
            "light": eff.get("light", ""),
            "label": eff.get("label", eff_id),
            "description": eff.get("description", ""),
            "energy": eff.get("energy", 2),
            "mood": eff.get("mood", "neutral"),
            "best_roles": eff.get("best_roles", []),
            "category": eff.get("category", "motion"),
        })
    # V4 extended effects
    for eff_id, eff in EXTENDED_EFFECTS.items():
        result.append({
            "id": eff_id,
            "motion": eff.get("category", ""),
            "light": "",
            "label": eff.get("label", eff_id),
            "description": eff.get("description", ""),
            "energy": eff.get("energy", 2),
            "mood": eff.get("mood", "neutral"),
            "best_roles": eff.get("best_roles", []),
            "category": eff.get("category", ""),
        })
    return result
```

If `catalog_for_api()` does not currently pass `energy`, `mood`, `best_roles`, and `category` through to the response, add them — the frontend hint colors depend on them.

#### `engine/effects.py` — Legacy catalog must also carry `energy` and `mood`
Spot-check the legacy `EFFECT_CATALOG` entries. If they lack `energy`/`mood`, add a migration pass inside `catalog_for_api()` that infers energy from motion/light names:

```python
MOTION_ENERGY = {
    "punch": 4, "flash": 5, "slam": 5, "tilt_up": 3, "pan": 2,
    "slow_push": 2, "slow_pull": 2, "steady": 1, "hold_close": 1,
}
LIGHT_ENERGY = {"lift_medium": 3, "lift_soft": 2, "neutral": 1, "dim_soft": 1, "pulse_end": 3, "pulse_start": 3, "breath": 1}

def _infer_energy(eff_id: str) -> int:
    for k, v in MOTION_ENERGY.items():
        if k in eff_id:
            return v
    for k, v in LIGHT_ENERGY.items():
        if k in eff_id:
            return v
    return 2

def _infer_mood(eff_id: str) -> str:
    if "punch" in eff_id or "flash" in eff_id: return "energetic"
    if "slow" in eff_id or "hold" in eff_id: return "intimate"
    if "steady" in eff_id: return "neutral"
    if "tilt" in eff_id or "pan" in eff_id: return "building"
    return "neutral"
```

---

## Task 4 — Verify and fix the font selector (NewReel + PlanReview)

### Check list (verify each, fix any that fail)

#### 1. `GET /fonts` endpoint
- Does it exist in `app/main.py`? If not, add it (see previous codex prompt).
- Does `fonts_dir()` from `engine/captions.py` correctly resolve `presets/fonts/` from the new font files (IRAN_Kharazmi, maneli, RAY family)?
- Does it recursively find TTF/OTF files in subdirectories (IRAN_Kharazmi and maneli may be in subfolders)?

Fix if needed:
```python
@app.get("/fonts")
def list_fonts():
    from engine.captions import load_style, fonts_dir
    from engine.schema import PROJECT_ROOT
    style = load_style("rafiei_reel")
    d = fonts_dir(style)
    if not d or not d.is_dir():
        # Fallback: scan presets/fonts/ directly
        d = PROJECT_ROOT / "presets" / "fonts"
    if not d.is_dir():
        return {"fonts": []}
    fonts = set()
    for f in d.rglob("*"):
        if f.suffix.lower() in (".ttf", ".otf"):
            fonts.add(f.stem)
    return {"fonts": sorted(fonts)}
```

#### 2. `NewReel.tsx` — Font dropdown
- Is there a `<select>` for `captionFont` in the Style card (step 2)?
- Does it call `api.listFonts()` on mount?
- Does it pass `caption_font` to `api.generatePlan()` in `onGenerate()`?
- Does the dropdown show all font names from `presets/fonts/`?

If font dropdown is missing or broken: add it (see previous codex prompt, Task 1, Frontend changes, NewReel.tsx section).

#### 3. `engine/captions.py` — `build_ass()` respects `caption_font`
- Does `build_ass()` check `plan.canvas.caption_font` (or however it is stored)?
- Does it override `base["font"]` correctly?
- Does the SRT/MLT path also pick up the font?

#### 4. `engine/schema.py` — `caption_font` field
- Is `caption_font: Optional[str] = None` present on `Canvas` or the plan root?

Write a focused test: generate a plan with `caption_font="RAY-ExtraBold"`, build the ASS, assert `Fontname` in the Style header matches `RAY-ExtraBold`.

---

## Summary of all files to change / verify

| File | Action |
|------|--------|
| `presets/rafiei_reel.yaml` | Add `rafiei_style:` block with preferred/avoid effects, colors, watermark |
| `engine/effects_v4.py` | Fix `catalog_for_api()` to include `energy`, `mood`, `best_roles`, `category` for ALL effects |
| `engine/effects.py` | Verify legacy catalog has `energy`/`mood`; add inference fallback if not |
| `app/main.py` | Add `GET /rafiei-styles`, `POST /my-effects/apply-rafiei`; verify `GET /fonts` exists & recurses |
| `web/src/api.ts` | Extend `EffectPreset` type with `energy`, `mood`, `best_roles`, `category`; add `getRafieiStyles()`, `applyRafieiStyle()` |
| `web/src/MyEffects.tsx` | Rafiei Styles section + Apply button; hint color bars + mood badges on all effect cards |
| `web/src/NewReel.tsx` | Verify font dropdown exists and works; fix if missing |
| `engine/captions.py` | Verify `build_ass()` uses `caption_font` override; fix if missing |
| `engine/schema.py` | Verify `caption_font` field on Canvas model; add if missing |
| `tests/test_captions.py` | Add test: `caption_font` in plan → correct Fontname in ASS output |

---

## Acceptance criteria

1. **My Effects → Rafiei Styles section** appears at the top, showing 5 preferred effects with energy-colored left border and mood badge. "Apply Rafiei Style →" button one-click populates favorites, rules, and dislikes.
2. **All effect cards** (Rafiei + Favorites) have a left color bar: red=energy 5 → blue=energy 1, plus a small mood badge pill.
3. **`GET /effects`** returns `energy`, `mood`, `best_roles` for every effect including legacy ones.
4. **Font dropdown** in NewReel lists all fonts from `presets/fonts/` (including RAY, IRAN Kharazmi, maneli). Selected font is included in plan and renders in ASS output with correct Fontname.
5. **Auto-effect** selection (existing `brain/` logic) reads My Effects favorites and dislikes; a Rafiei dislike (`rgb_split`) never appears in a generated plan after "Apply Rafiei Style" is used.
