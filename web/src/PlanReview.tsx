import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, EffectPreset, Job, Transcript } from "./api";
import { Timeline } from "./Timeline";

type Tab = "visual" | "json";
type WordEdit = { text: string; start: number; end: number };

export default function PlanReview() {
  const { id } = useParams();
  const nav = useNavigate();
  const [job, setJob] = React.useState<Job | null>(null);
  const [planText, setPlanText] = React.useState("");
  const [errors, setErrors] = React.useState<string[]>([]);
  const [saved, setSaved] = React.useState(false);
  const [transcript, setTranscript] = React.useState<Transcript | null>(null);
  const [wordEdits, setWordEdits] = React.useState<Record<number, WordEdit>>({});
  const [effects, setEffects] = React.useState<EffectPreset[]>([]);
  const [transcriptMessage, setTranscriptMessage] = React.useState("");
  const [reviewModel, setReviewModel] = React.useState("medium");
  const [reviewHint, setReviewHint] = React.useState("");
  const [reviewAcknowledged, setReviewAcknowledged] = React.useState(false);
  const [tab, setTab] = React.useState<Tab>("visual");
  const [genStatus, setGenStatus] = React.useState<any>(null);
  const videoRef = React.useRef<HTMLVideoElement>(null);

  React.useEffect(() => {
    if (!id) return;
    api.getJob(id).then(j => {
      setJob(j);
      if (j.plan) setPlanText(JSON.stringify(j.plan, null, 2));
    });
    api.getTranscript(id).then(t => { setTranscript(t); setWordEdits({}); }).catch(() => {});
    api.listEffects().then(setEffects).catch(() => {});
    api.generateStatus(id).then(setGenStatus).catch(() => {});
  }, [id]);

  // Poll generate status if running
  React.useEffect(() => {
    if (!id || genStatus?.status !== "running") return;
    const iv = setInterval(() => {
      api.generateStatus(id).then(s => {
        setGenStatus(s);
        if (s.status === "done") {
          api.getJob(id).then(j => {
            setJob(j);
            if (j.plan) setPlanText(JSON.stringify(j.plan, null, 2));
          });
          api.getTranscript(id).then(t => { setTranscript(t); setWordEdits({}); }).catch(() => {});
        }
      }).catch(() => {});
    }, 1500);
    return () => clearInterval(iv);
  }, [id, genStatus?.status]);

  const parsedPlan = React.useMemo(() => {
    try { return JSON.parse(planText); } catch { return null; }
  }, [planText]);

  React.useEffect(() => setReviewAcknowledged(false), [planText]);

  React.useEffect(() => {
    if (!id || !parsedPlan) { setErrors(planText.trim() ? ["invalid JSON"] : []); return; }
    const t = setTimeout(async () => {
      const r = await api.validate(id, parsedPlan);
      setErrors(r.errors);
    }, 400);
    return () => clearTimeout(t);
  }, [planText, parsedPlan, id]);

  async function save(): Promise<boolean> {
    if (!id || !parsedPlan) return false;
    try {
      const r = await api.putPlan(id, parsedPlan);
      if (!r.ok) { setErrors(r.errors || []); return false; }
      setSaved(true); setTimeout(() => setSaved(false), 2000);
      return true;
    } catch (error: any) {
      setErrors([String(error.message || error)]);
      return false;
    }
  }

  async function doRender(preview: boolean) {
    if (!id) return;
    if (!(await save())) return;
    await api.render(id, preview);
    nav(`/jobs/${id}/render`);
  }

  async function openKdenlive() {
    if (!id) return;
    if (!(await save())) return;
    try {
      await api.openKdenlive(id);
    } catch {
      await api.render(id, true);
      alert("Building project first — try Open in Kdenlive again when render finishes.");
    }
  }

  function seekTo(t: number) {
    if (videoRef.current) { videoRef.current.currentTime = t; videoRef.current.play(); }
  }

  function updatePlanField(path: (string | number)[], value: any) {
    if (!parsedPlan) return;
    const copy = JSON.parse(JSON.stringify(parsedPlan));
    let obj: any = copy;
    for (let i = 0; i < path.length - 1; i++) obj = obj[path[i]];
    obj[path[path.length - 1]] = value;
    setPlanText(JSON.stringify(copy, null, 2));
  }

  function deleteItem(arrayPath: string[], index: number) {
    if (!parsedPlan) return;
    const copy = JSON.parse(JSON.stringify(parsedPlan));
    let arr: any = copy;
    for (const k of arrayPath) arr = arr[k];
    arr.splice(index, 1);
    setPlanText(JSON.stringify(copy, null, 2));
  }

  async function saveTranscriptCorrections() {
    if (!id || !transcript) return;
    const words = transcript.words.flatMap((word, index) => {
      const edit = wordEdits[index];
      return (word.reviewed || edit) ? [{ index,
        text: edit?.text ?? word.w, start: edit?.start ?? word.start, end: edit?.end ?? word.end }] : [];
    });
    try {
      const updated = await api.putTranscriptCorrections(id, transcript.cache_key || transcript.file_hash, words);
      setTranscript(updated); setWordEdits({});
      setTranscriptMessage("Corrections saved. Regenerate the plan to update captions and cuts.");
    } catch (error: any) { setTranscriptMessage(String(error.message || error)); }
  }

  async function regenerateFromTranscript() {
    if (!id || Object.keys(wordEdits).length) return;
    try {
      await api.generatePlan(id, { use_saved_transcript: true });
      setGenStatus({ status: "running", stage: "planning", message: "Using reviewed transcript" });
      setTranscriptMessage("Generating a new plan from the saved transcript…");
    } catch (error: any) { setTranscriptMessage(String(error.message || error)); }
  }

  async function retranscribeOnly() {
    if (!id || Object.keys(wordEdits).length) return;
    try {
      await api.generatePlan(id, { transcribe_only: true, whisper_model: reviewModel,
        language: transcript?.requested_language || transcript?.language || "fa",
        transcription_hint: reviewHint.trim() });
      setGenStatus({ status: "running", stage: "transcribing", message: "Creating a transcript candidate" });
      setTranscriptMessage("Re-transcribing only. The current plan and render remain available.");
    } catch (error: any) { setTranscriptMessage(String(error.message || error)); }
  }

  function updateEffect(segmentId: string, effectId: string) {
    if (!parsedPlan) return;
    const copy = JSON.parse(JSON.stringify(parsedPlan));
    copy.visual_effects = (copy.visual_effects || []).filter((effect: any) => effect.segment_id !== segmentId);
    if (effectId) copy.visual_effects.push({ segment_id: segmentId, type: effectId });
    if (copy.visual_effects.length) copy.version = "0.2";
    setPlanText(JSON.stringify(copy, null, 2));
  }

  if (!job) return <p>Loading…</p>;

  const isGenerating = genStatus?.status === "running";
  const needsReview = !!(parsedPlan?.caption_review?.length || parsedPlan?.effect_review?.length);

  return (
    <div>
      <h1>Job {job.id}</h1>

      {/* Generation progress */}
      {isGenerating && (
        <div className="card" style={{ borderLeft: "3px solid #2563eb" }}>
          <b>Generating plan…</b> Stage: {genStatus.stage}
          <div className="muted">{genStatus.message}</div>
        </div>
      )}
      {genStatus?.status === "error" && (
        <div className="errors">Generation failed: {genStatus.message}</div>
      )}

      {/* Cost display */}
      {genStatus?.cost_usd > 0 && (
        <div className="card" style={{ padding: "8px 12px", fontSize: 13 }}>
          LLM cost: <b>${genStatus.cost_usd.toFixed(4)}</b>
          {" "}({genStatus.model}, {genStatus.input_tokens} in / {genStatus.output_tokens} out)
        </div>
      )}

      <div className="grid2">
        <div className="card">
          <h2>Raw video</h2>
          <video ref={videoRef} src={api.rawUrl(job.id)} controls preload="metadata" />
        </div>
        <div className="card">
          <h2>Timeline</h2>
          <Timeline plan={parsedPlan} onSeek={seekTo} />
        </div>
      </div>

      {/* Transcript */}
      {transcript && (
        <div className="card">
          <h2>Transcript <span className="muted">({transcript.language}, {transcript.model_size || "model unknown"})</span></h2>
          <p className="muted">Click a word to hear it. Edit uncertain words, then save before regenerating the plan. Yellow words have low ASR confidence.</p>
          <TranscriptView
            transcript={transcript}
            plan={parsedPlan}
            onSeek={seekTo}
            edits={wordEdits}
            onEdit={(index, change) => setWordEdits(current => {
              const baseline: WordEdit = { text: transcript.words[index].w,
                start: transcript.words[index].start, end: transcript.words[index].end };
              return { ...current, [index]: { ...baseline, ...current[index], ...change } };
            })}
          />
          <div className="row" style={{ marginTop: 12 }}>
            <button onClick={saveTranscriptCorrections} disabled={!Object.keys(wordEdits).length}>Save transcript corrections</button>
            <button className="secondary" onClick={regenerateFromTranscript}
              disabled={isGenerating || !!Object.keys(wordEdits).length}>Regenerate plan from transcript</button>
          </div>
          <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
            <label>ASR model: <select value={reviewModel} onChange={e => setReviewModel(e.target.value)}>
              <option value="medium">medium</option><option value="small">small</option>
              <option value="large-v3">large-v3</option>
            </select></label>
            <input aria-label="Speech terms for re-transcription" value={reviewHint}
              onChange={e => setReviewHint(e.target.value)} placeholder="Speech terms (optional)" />
            <button className="secondary" onClick={retranscribeOnly}
              disabled={isGenerating || !!Object.keys(wordEdits).length}>Re-transcribe only</button>
          </div>
          {transcriptMessage && <p className="muted">{transcriptMessage}</p>}
        </div>
      )}

      {/* Plan editing tabs */}
      <div className="card">
        <div className="row" style={{ gap: 8, marginBottom: 12 }}>
          <button className={tab === "visual" ? "" : "secondary"} onClick={() => setTab("visual")}>
            Visual Editor
          </button>
          <button className={tab === "json" ? "" : "secondary"} onClick={() => setTab("json")}>
            JSON
          </button>
        </div>

        {tab === "visual" && parsedPlan ? (
          <VisualEditor
            plan={parsedPlan}
            effects={effects}
            onEffectChange={updateEffect}
            onUpdate={updatePlanField}
            onDelete={deleteItem}
            onSeek={seekTo}
          />
        ) : (
          <div>
            <textarea rows={22} value={planText} onChange={e => setPlanText(e.target.value)} />
          </div>
        )}

        {errors.length > 0 ? (
          <div className="errors">
            <div><b>Validation errors:</b></div>
            <ul>{errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
          </div>
        ) : parsedPlan ? <div className="ok">Plan is valid.</div> : null}
        {saved && <div className="ok">Saved.</div>}
      </div>

      <div className="row">
        {needsReview &&
          <label className="muted"><input type="checkbox" checked={reviewAcknowledged}
            onChange={e => setReviewAcknowledged(e.target.checked)} />
            I reviewed the marked captions against the audio and checked subject framing</label>}
        <button onClick={() => { void save(); }} className="secondary">Save plan</button>
        <button onClick={() => doRender(true)}>Preview (540x960)</button>
        <button onClick={() => doRender(false)}
          disabled={needsReview && !reviewAcknowledged}>Render (1080x1920)</button>
        <button onClick={openKdenlive} className="secondary">Open in Kdenlive</button>
        <a href={api.planUrl(job.id)}><button className="secondary">Download plan.json</button></a>
      </div>
    </div>
  );
}


/* ---------- Transcript view with clickable words ---------- */

function TranscriptView({ transcript, plan, onSeek, edits, onEdit }: {
  transcript: Transcript; plan: any; onSeek: (t: number) => void;
  edits: Record<number, WordEdit>; onEdit: (index: number, change: Partial<WordEdit>) => void;
}) {
  const [selected, setSelected] = React.useState<number | null>(null);
  const removedRanges = React.useMemo(() => {
    if (!plan?.segments || !transcript) return new Set<number>();
    const kept = new Set<number>();
    for (const seg of plan.segments) {
      for (let i = 0; i < transcript.words.length; i++) {
        const w = transcript.words[i];
        if (w.start >= seg.in - 0.05 && w.end <= seg.out + 0.05) kept.add(i);
      }
    }
    const removed = new Set<number>();
    for (let i = 0; i < transcript.words.length; i++) {
      if (!kept.has(i)) removed.add(i);
    }
    return removed;
  }, [transcript, plan]);

  return (
    <div className="transcript-words">
      {transcript.words.map((w, i) => (
        <span
          key={i}
          className={`tw ${removedRanges.has(i) ? "tw-removed" : ""} ${w.prob < 0.6 && !w.reviewed ? "tw-low" : ""} ${w.reviewed ? (w.original_w ? "tw-auto-corrected" : "tw-reviewed") : ""}`}
          title={
            w.reviewed && w.original_w
              ? `Auto-corrected: ${w.original_w} → ${w.w}\n${w.start.toFixed(2)}s–${w.end.toFixed(2)}s`
              : `${w.start.toFixed(2)}s — ${w.end.toFixed(2)}s (${(w.prob * 100).toFixed(0)}%)`
          }
          onClick={() => { onSeek(w.start); setSelected(i); }}
        >
          {edits[i]?.text ?? w.w}{" "}
        </span>
      ))}
      {selected !== null && <div className="row" style={{ marginTop: 10 }}>
        <span className="muted">{transcript.words[selected].start.toFixed(2)}s</span>
        <input aria-label="Correct selected word" dir="auto" value={edits[selected]?.text ?? transcript.words[selected].w}
          onChange={e => onEdit(selected, { text: e.target.value })} />
        <label className="muted">Start <input aria-label="Word start time" type="number" min="0" step="0.01"
          value={edits[selected]?.start ?? transcript.words[selected].start}
          onChange={e => onEdit(selected, { start: Number(e.target.value) })} /></label>
        <label className="muted">End <input aria-label="Word end time" type="number" min="0" step="0.01"
          value={edits[selected]?.end ?? transcript.words[selected].end}
          onChange={e => onEdit(selected, { end: Number(e.target.value) })} /></label>
        <button className="secondary" onClick={() => onSeek(transcript.words[selected].start)}>Replay</button>
      </div>}
    </div>
  );
}


/* ---------- Visual plan editor ---------- */

function VisualEditor({ plan, effects, onEffectChange, onUpdate, onDelete, onSeek }: {
  plan: any;
  effects: EffectPreset[];
  onEffectChange: (segmentId: string, effectId: string) => void;
  onUpdate: (path: (string | number)[], value: any) => void;
  onDelete: (arrayPath: string[], index: number) => void;
  onSeek: (t: number) => void;
}) {
  const [activeEffectSegment, setActiveEffectSegment] = React.useState<string | null>(null);
  return (
    <div className="visual-editor">
      {/* Segments */}
      <h3>Segments ({plan.segments?.length || 0})</h3>
      {!!plan.effect_review?.length &&
        <p className="errors">{plan.effect_review.length} motion effect(s) need a framing check in preview.</p>}
      {plan.segments?.map((seg: any, i: number) => (
        <div key={seg.id || i} className="ve-item" onClick={() => onSeek(seg.in)}>
          <span className="ve-id">{seg.id}</span>
          <span className="muted">{seg.in.toFixed(2)}s → {seg.out.toFixed(2)}s</span>
          <button className="secondary" onClick={e => {
            e.stopPropagation(); setActiveEffectSegment(activeEffectSegment === seg.id ? null : seg.id);
          }}>
            Effect: {(plan.visual_effects || []).find((effect: any) => effect.segment_id === seg.id)?.type || "Legacy zoom"}
          </button>
          {activeEffectSegment === seg.id && <label>Choose:
            <select aria-label={`Effect for ${seg.id}`}
              value={(plan.visual_effects || []).find((effect: any) => effect.segment_id === seg.id)?.type || ""}
              onClick={e => e.stopPropagation()}
              onChange={e => { onEffectChange(seg.id, e.target.value); setActiveEffectSegment(null); }}>
              <option value="">Legacy zoom</option>
              {[...new Set(effects.map(effect => effect.motion))].map(motion => (
                <optgroup key={motion} label={motion.replace(/_/g, " ")}>
                  {effects.filter(effect => effect.motion === motion).map(effect =>
                    <option key={effect.id} value={effect.id}>{effect.label}</option>)}
                </optgroup>
              ))}
            </select>
          </label>}
          {!(plan.visual_effects || []).some((effect: any) => effect.segment_id === seg.id) && <><label>Zoom from:
            <input type="number" step={0.05} min={1} max={1.5}
              value={seg.zoom?.from ?? 1}
              onChange={e => onUpdate(["segments", i, "zoom", "from"], +e.target.value)}
            />
          </label>
          <label>to:
            <input type="number" step={0.05} min={1} max={1.5}
              value={seg.zoom?.to ?? 1}
              onChange={e => onUpdate(["segments", i, "zoom", "to"], +e.target.value)}
            />
          </label>
          </>}
          <button className="danger-sm" onClick={e => { e.stopPropagation(); onDelete(["segments"], i); }}>✕</button>
        </div>
      ))}

      {/* Captions */}
      <h3>Captions ({plan.captions?.length || 0})</h3>
      {!!plan.caption_review?.length &&
        <p className="errors">{plan.caption_review.length} caption(s) need audio review. Compare the text with the highlighted transcript and raw video before final render.</p>}
      {plan.captions?.map((cap: any, i: number) => (
        <div key={i} className="ve-item" onClick={() => onSeek(cap.start)}>
          <span className={`ve-style ve-${cap.style}`}>{cap.style}</span>
          {plan.caption_review?.some((warning: any) => warning.caption_index === i) &&
            <span title={plan.caption_review.find((warning: any) => warning.caption_index === i)?.source_text}>
              ⚠️
            </span>}
          <input type="text" value={cap.text}
            onChange={e => onUpdate(["captions", i, "text"], e.target.value)}
            onClick={e => e.stopPropagation()}
          />
          <span className="muted">{cap.start.toFixed(2)}s–{cap.end.toFixed(2)}s</span>
          <button className="danger-sm" onClick={e => { e.stopPropagation(); onDelete(["captions"], i); }}>✕</button>
        </div>
      ))}

      {/* B-roll */}
      <h3>B-roll ({plan.broll?.length || 0})</h3>
      {plan.broll?.map((b: any, i: number) => (
        <div key={i} className="ve-item" onClick={() => onSeek(b.at)}>
          <span className="muted">@{b.at.toFixed(2)}s, {b.duration.toFixed(1)}s</span>
          <span>{b.query || b.file}</span>
          <button className="danger-sm" onClick={e => { e.stopPropagation(); onDelete(["broll"], i); }}>✕</button>
        </div>
      ))}

      {/* SFX */}
      <h3>SFX ({plan.sfx?.length || 0})</h3>
      {plan.sfx?.map((s: any, i: number) => (
        <div key={i} className="ve-item" onClick={() => onSeek(s.at)}>
          <span className="muted">@{s.at.toFixed(2)}s</span>
          <span>{s.file?.split("/").pop()}</span>
          <button className="danger-sm" onClick={e => { e.stopPropagation(); onDelete(["sfx"], i); }}>✕</button>
        </div>
      ))}
    </div>
  );
}
