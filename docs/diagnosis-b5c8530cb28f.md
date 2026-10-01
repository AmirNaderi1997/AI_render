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
