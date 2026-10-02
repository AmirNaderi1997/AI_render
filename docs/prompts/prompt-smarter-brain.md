# Prompt — make effect selection and transcript correction smarter

Paste into Claude Code, started from `~/Documents/AI_render`. Only one agent at a time. Work on main, commit locally, never push.

---

Project: ~/Documents/AI_render (Rafiei AI Editor), main at decba00, 84 tests. Effect catalog and auto transcript
correction work, but in my real test (job b5c8530cb28f) both are too dumb: effects feel random/repetitive and
correction misses obvious wrong words. Make both much smarter. LLM = jarvis via brain/llm.py (key is in .env).

## 0. Diagnose job b5c8530cb28f first (no code changes yet)
- Transcript: total words, flagged words, auto-applied, suggestions; 10 examples of words that look wrong but were
  NOT flagged; was the correction LLM actually called (log line, tokens)?
- Effects: list every effect in the plan with time, segment text, and whether it came from the LLM or from the
  _ensure_visual_effects fallback rhythm. Count distinct effects used. Show the exact effect list the LLM saw.
- Write findings to docs/diagnosis-b5c8530cb28f.md. This is the baseline to beat.

## 1. Smarter transcript correction
1. Better ASR input: pass glossary terms to faster-whisper (`initial_prompt` with topic + key terms, and `hotwords`
   if the installed version supports it). Use language=fa and model "medium" (or large-v3 if time allows) for
   Persian; record which was used.
2. Second opinion: use the multi-candidate data Codex added (or run a second decode with different beam/temperature
   or model). Any word where the two disagree is flagged, besides low prob and glossary hits.
3. Context review, not only flagged words: send the LLM the transcript sentence by sentence (with timestamps and
   prob per word) plus the topic/instruction line and glossary. Ask it to find words that do not make sense in
   context (wrong homophones, broken names, wrong numbers, split/merged words), and return
   [{indices, old, new, confidence, reason, type: replace|merge|split}].
4. Guardrails: only accept a fix that sounds similar to the original (compare a Persian-to-Latin transliteration
   with edit distance; threshold in preset) or is a glossary/candidate word. Never rewrite style, grammar or meaning.
   Reject fixes that change more than 2 words in a row.
5. Support merge/split with correct timing (split = divide range by character length; merge = union).
6. Learn: when I edit a word manually or reject/accept a suggestion in the UI, save it to presets/glossary.yaml
   (known_errors / vocabulary) so the next video benefits.
7. UI: a "Review corrections" panel listing each change (old -> new, reason, confidence, play button that plays
   that word's audio) with Accept / Reject / Accept all high-confidence.

## 2. Smarter effect selection
The current catalog is 10 motions x 10 lights; the LLM gets ids without meaning, so it picks blindly and the
fallback rhythm repeats. Replace blind picking with a two-step "editor brain":
1. Analyse each segment (one LLM call for the whole video, structured output): role (hook, claim, explanation,
   list item, number/stat, story, joke, emotion, question, CTA), energy 1-5, emotion, key word(s), and whether it
   is a turning point. Add measured signals per segment: loudness and speech rate (from transcript + ffmpeg),
   and face size/position if available (mediapipe/opencv optional; skip gracefully if not installed).
2. Rich catalog: for every effect add human meaning: mood, energy level 1-5, best roles, avoid_after (effects it
   should not follow), max_per_minute, and a one-line "what the viewer feels". Group the 100 presets into named
   families (e.g. "punch-in hit", "slow push", "drift", "flash accent", "calm hold") so the LLM chooses from
   ~15-20 meaningful families with intensity, not 100 opaque ids.
3. Selection = scoring + constraints, then LLM: score every family against each segment (role match, energy match,
   emphasis words, position in video: strong hook in first 2 s, strongest accent on the key claim, calm before
   CTA, CTA distinct). Enforce variety (no same family twice in a row, max share per family, rhythm: an accent every
   2-4 s, no static shot longer than the style limit). Give the LLM the top 3 candidates per segment with scores and
   let it choose + explain; fall back to the top score, never to a fixed rhythm.
4. Sync to speech: punch-ins land on the first frame of the emphasis word; motion ends before a cut; no effect
   starts inside a word except on the key word.
5. Self-check: after planning, a cheap LLM critic pass reads the effect timeline + segment roles and returns issues
   (repetition, effect not matching meaning, too busy, too flat); apply its fixes once.
6. UI: each effect marker shows family, intensity and reason; "Suggest alternative" shows the next 2 candidates.
7. All weights and limits in presets/rafiei_reel.yaml.

## Tests (mocked LLM)
- Correction: disagreement between candidates flags a word; similarity guard rejects a meaning-changing fix;
  merge/split timing; manual edit is added to glossary; hotwords/initial_prompt passed to the transcriber.
- Effects: scorer picks hook family for first segment, accent on key claim; no family twice in a row; no static
  shot over the limit; LLM picking an id outside its candidates is rejected; critic fix applied; exact duration kept.

## Real run and comparison
- Re-run job b5c8530cb28f (same video) end to end and compare with the baseline in docs/diagnosis-b5c8530cb28f.md:
  corrected words (with 10 examples old -> new), words still wrong, distinct effects used, how many from LLM vs
  fallback, the effect timeline with reasons, LLM cost, plan vs render duration, 5 frame paths.
- pytest -q and npm run build green. Commit locally on main, do not push.

## Report
PASS/FAIL per section, the before/after comparison table, and what is still open.
