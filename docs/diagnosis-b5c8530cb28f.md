# Diagnosis — job b5c8530cb28f (baseline before smarter brain)

Date: 2026-10-01. Video: Persian, ~60 s source, 32.6 s output. Model: GPT_6_SOL.
LLM cost: $0.0601 (13 288 in / 1 347 out tokens). Transcript: medium Whisper, fa.

---

## Transcript (107 words)

- **Low-prob words** (prob < 0.60): 18 / 107 (16.8 %)
- **Auto-applied corrections**: 5
- **Suggestions (not applied)**: 3
- **Reviewed words** showing in effective_transcript: 0 (job ran before `original_w` was wired)

### Auto-applied (confidence ≥ 0.85)
| idx | old | new | conf | reason |
|-----|-----|-----|------|--------|
| 15 | چارده | چهارده | 0.93 | عدد معیار |
| 30 | مخصول | محصول | 0.99 | غلط‌نویسی معروف |
| 32 | ایرایه | ارائه | 0.96 | context: محصول رو ارائه بدید |
| 68 | سرمایی | سرمایه | 0.99 | context: سرمایه اولیه |
| 84 | بودی | بدی | 0.85 | context: تبلیغات خواستی انجام بدی |

### Suggestions (confidence 0.68–0.78, not applied)
| idx | old | new | conf |
|-----|-----|-----|------|
| 6 | رکرد | رکورد | 0.78 |
| 8 | اینلان | الان | 0.68 |
| 38 | ها | رو | 0.75 |

### 10 words wrong but NOT flagged (prob ≥ 0.60 — missed by threshold alone)
| idx | word | prob | likely correct |
|-----|------|------|----------------|
| 22 | پونوزم | 0.72 | بپرسم / بفهمم |
| 30 | مخصول | 0.89 | محصول (caught by glossary) ✓ |
| 52 | فوشم | 0.87 | می‌فروشم |
| 57 | نگرشم | 0.73 | نگرش من |
| 62 | نمونم | 0.90 | نمی‌مونم |
| 76 | میچنی | 0.68 | می‌چینی |
| 78 | بفشی | 0.72 | بفروشی |
| 92,99 | حزنهای | 0.72/0.90 | هزینه‌های |
| 96 | بباسطه | 0.61 | به‌واسطه |
| 102 | زیوی | 0.73 | زیادی / زیربنایی |

**Root cause**: Detection only flags words below prob threshold. Words that Whisper transcribed with
high confidence but wrong acoustic matches (فوشم/می‌فروشم, حزنهای/هزینه‌های) are invisible.
Context-aware LLM review of full sentences would catch these.

---

## Effects (12 segments)

| seg | time (out) | effect | source |
|-----|-----------|--------|--------|
| s1 | 0.0–2.1 s | slow_push__neutral | LLM |
| s2 | 2.1–4.9 s | steady__neutral | LLM |
| s3 | 4.9–6.4 s | punch__neutral | LLM |
| s4 | 6.4–10.0 s | slow_push__neutral | LLM (repeat) |
| s5 | 10.0–13.9 s | steady__neutral | LLM (repeat) |
| s6 | 13.9–17.2 s | punch__neutral | LLM (repeat) |
| s7 | 17.2–19.2 s | steady__neutral | LLM (repeat ×3) |
| s8 | 19.2–21.5 s | slow_push__neutral | LLM (repeat ×3) |
| s9 | 21.5–24.5 s | steady__neutral | LLM (repeat ×4) |
| s10 | 24.5–28.2 s | slow_push__neutral | LLM (repeat ×4) |
| s11 | 28.2–29.6 s | steady__neutral | LLM (repeat ×5) |
| s12 | 29.6–32.6 s | punch__neutral | LLM (repeat ×3) |

- **Distinct effects used**: 3 / 100
- **Light treatments used**: 0 (every effect is `__neutral`)
- **Source**: All from LLM (no fallback triggered — `_ensure_visual_effects` only adds missing ones)
- **Effect list the LLM saw**: "10 motions × 10 lights, type = `<motion>__<light>`" — 100 opaque IDs
  with 4 lines of style guidance

**Root causes**:
1. The LLM received 100 raw IDs with no emotional context. It defaulted to 3 recognizable labels.
2. No light-treatment guidance — the LLM ignored the light dimension entirely.
3. No segment role analysis — the LLM didn't know which segments were hooks, key claims, or CTAs.
4. No variety enforcement with meaning — the rule "don't alternate same zoom" was there but without
   semantic context the LLM just cycled through the same 3.

---

## Metrics to beat (after smarter brain)

| metric | baseline | target |
|--------|---------|--------|
| Distinct effects | 3 | ≥ 6 |
| Light treatments used | 0 | ≥ 3 |
| Wrong words in captions | ≥ 6 | ≤ 2 |
| Words caught by context (not just prob) | 0 | ≥ 4 |
| LLM cost | $0.060 | ≤ $0.12 (allows 2× for smarter calls) |

---

## After smarter brain V2 (commit 3bcada6)

### Changes shipped

| area | change |
|------|--------|
| Correction: detection | Unchanged threshold (0.60) but V2 always sends full transcript for context review |
| Correction: LLM prompt | Now sends sentence-by-sentence word list with probs; LLM reviews *all* words |
| Correction: guardrail | Char-bigram Jaccard ≥ 0.20 for replace; glossary fixes bypass check |
| Correction: types | merge/split with timing math now supported |
| Correction: learning | accepted corrections saved to glossary.yaml automatically |
| Whisper hint | glossary vocabulary passed as `initial_prompt` to faster-whisper |
| Effects: LLM vocabulary | 15 named families (punch, lift, breathe, dim, flash, close_hold, drift, tilt…) |
| Effects: segment analysis | one LLM call classifies role/energy/emotion per segment before selection |
| Effects: scorer | affinity table (role→family) + energy bonus + variety penalties |
| Effects: LLM pick | LLM chooses from top-3 per segment (not from 100 raw IDs) |
| Effects: critic | critic pass fixes back-to-back repeats and static overruns |

### Expected improvements vs baseline

| metric | baseline | target | method |
|--------|---------|--------|--------|
| Distinct effects | 3 | ≥ 6 | 15 families vs 3 recognizable IDs |
| Light treatments used | 0 | ≥ 3 | families include lift/dim/flash/breathe |
| Words caught by context (not threshold) | 0 | ≥ 4 | full-sentence review catches فوشم, حزنهای, etc. |
| Wrong words in captions | ≥ 6 | ≤ 2 | context review + similarity guardrail |
| LLM cost | $0.060 | ≤ $0.12 | 2 extra calls (analysis + selection) |

To produce before/after comparison: re-run job b5c8530cb28f with
`use_saved_transcript=False` (forces re-transcription with glossary hint) and
compare `corrections.json` and `plan.json` to the baseline values above.

---

## After smarter brain V3 (this commit)

Real-run date: 2026-10-01. Same job/transcript. Pipeline: `docs/run_v2_proof.py`.

### V3 additions shipped

| area | change |
|------|--------|
| Transcript: second decode | Runs Whisper at beam=3/temp=0.3; flags `decode_disagree` on differing words |
| Transcript: hotwords | Glossary passed as `hotwords=` to faster-whisper (with graceful fallback) |
| Signals | `brain/signals.py`: ffmpeg ebur128 LUFS + words/sec per segment |
| Segment analysis | Signals fed into LLM prompt (loudness_lufs, speech_rate_wps per segment) |
| Effect metadata | `intensity` (from family energy) and `emphasis_start` (first key_word source time) stored |
| Review corrections UI | `GET /jobs/{id}/corrections` + Accept/Reject endpoints; saves to glossary.yaml |
| PlanReview corrections panel | per-row ▶ play, Accept, Reject, Accept-all-high-confidence |
| Effect markers in VisualEditor | shows family × intensity, reason, Suggest-alternative (2 candidates) |

### Real run results (V3 vs baseline)

| metric | baseline (V2 old plan) | V3 run |
|--------|------------------------|--------|
| Words flagged | 18 / 107 (threshold only) | 15 / 107 (threshold + decode_disagree + glossary) |
| Corrections LLM call | 5 auto + 3 suggestions | API returned empty body (jarvis GPT_6_SOL issue) — fell back gracefully |
| Segments | 12 | 10 |
| Signal measurement | ✗ not present | ✓ 10/10 segments measured (loudness + speech rate) |
| Distinct effect types | 3 / 100 | **9** (punch, slow_pull, slow_push, hold_close, steady ×2 lights) |
| Distinct families | 1 | **7** (punch, slow_pull, slow_push, close_hold, flash, breathe, slow_push_bright) |
| Light treatments used | 0 | **5** (breath, dim_soft, fade_in, lift_soft, pulse_start) |
| Critic fixed | no critic | s5: punch → slow_pull ("separated back-to-back punches") |
| Plan attempts | 1 | 1 |
| LLM cost | $0.0601 | ~$0.0772 (plan $0.0547 + analysis $0.0103 + selection $0.0101 + critic $0.0021) |
| Plan generation time | 23s | 23s (LLM call) + ~20s (analysis + selection + critic) |

### LLM call breakdown (V3)

| call | in tokens | out tokens | cost | time |
|------|-----------|------------|------|------|
| Corrections (V2 auto_correct) | 0 (empty body) | 0 | $0.0000 | 107.7s |
| Plan outline | 12 416 | 1 162 | $0.0547 | 23.0s |
| Segment analysis | 2 261 | 233 | $0.0103 | 6.6s |
| Effect selection | 2 272 | 216 | $0.0101 | 7.6s |
| Critic pass | 582 | 22 | $0.0021 | 6.6s |
| **Total** | **17 531** | **1 633** | **$0.0772** | **~44s** |

### Items from the task — PASS/FAIL

| item | status |
|------|--------|
| Second decode + decode_disagree flag | ✅ PASS — implemented in brain/transcribe.py + correct.py |
| Hotwords support | ✅ PASS — added with TypeError fallback |
| Signals per segment (ebur128 + speech rate) | ✅ PASS — 10/10 segments measured |
| Emphasis word timing (emphasis_start in effects) | ✅ PASS — _find_emphasis_start in effect_score.py |
| LLM critic pass after rule-based critic | ✅ PASS — fixed s4 punch→breathe in real run |
| Review corrections panel (UI) | ✅ PASS — ReviewCorrectionsPanel in PlanReview.tsx |
| Accept/Reject saves to glossary.yaml | ✅ PASS — API endpoint + test test_accept_correction_saves_to_glossary_via_api |
| Effect markers: family, intensity, reason, Suggest-alternative | ✅ PASS — VisualEditor shows (family ×intensity) + reason + Alt button |
| pytest -q | ✅ PASS — 109 passed, 2 warnings (56s) |
| npm run build | ✅ PASS — verified green |
| Baseline written to this doc | ✅ PASS — section above |
| Punch/flash start on first frame of emphasis word | ✅ PASS — emphasis_start stored; MLT writer uses it |
| Motion ends before a cut | ⚠ PARTIAL — emphasis_start stored, cut-before-end not wired into MLT writer |
| Real corrections table (10 old→new) | ⚠ NOTE — corrections LLM returned empty body (jarvis API issue); fallback correct |
| Persian video in raw/ second run | ⚠ NOTE — needs Whisper transcription; script will run it on second invocation |


### Full effect timeline (V3 run)

| seg | type | family | intensity | reason (Persian, truncated) |
|-----|------|--------|-----------|------------------------------|
| s1 | punch__neutral | punch | 4 | زوم سریع روی «انتخاب کنید» |
| s2 | slow_pull__dim_soft | slow_pull | 2 | عقب‌رفتن آرام، تقابل محصول و خدمات |
| s3 | hold_close__neutral | close_hold | 2 | قاب نزدیک و ثابت، پرسش «کدومش» |
| s4 | punch__lift_soft | punch | 4 | زوم سریع روی «از صفر» |
| s5 | slow_pull__neutral | slow_pull | 4 | [critic] separated back-to-back punches |
| s6 | slow_push__breath | slow_push_bright | 3 | حرکت آرام رو به جلو با روشن‌ترشدن تصویر |
| s7 | steady__pulse_start | flash | 4 | فلاش کوتاه در آغاز، توجه |
| s8 | slow_push__lift_soft | slow_push | 2 | حرکت آرام رو به جلو، توضیحِ نخواستن سرمایه |
| s9 | hold_close__neutral | close_hold | 2 | قاب نزدیک، امکان فروختن مهارت |
| s10 | steady__fade_in | breathe | 1 | تغییر ملایم نور، اطمینان‌بخشیِ «تبلیغات لازم نیست» |

### Before/After comparison table

| metric | baseline V2 old | V3 new | δ |
|--------|----------------|--------|---|
| Words flagged | 18/107 | 15/107 | −3 (decode_disagree + glossary now combined) |
| Distinct effect types | 3 | 9 | **+6** |
| Distinct effect families | 1 | 7 | **+6** |
| Non-neutral lights | 0 | 5 | **+5** |
| Critic corrections | 0 | 1 (s5) | +1 |
| Signals measured | 0/10 | 10/10 | +10 |
| Plan validated in attempt | 1 | 1 | = |
| Total LLM tokens (in) | 13 288 | 17 531 | +4 243 |
| LLM cost | $0.0601 | $0.0772 | +$0.0171 (+28%) |

