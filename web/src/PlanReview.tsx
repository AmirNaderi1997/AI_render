import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, Job, Transcript } from "./api";
import { Timeline } from "./Timeline";

type Tab = "visual" | "json";

export default function PlanReview() {
  const { id } = useParams();
  const nav = useNavigate();
  const [job, setJob] = React.useState<Job | null>(null);
  const [planText, setPlanText] = React.useState("");
  const [errors, setErrors] = React.useState<string[]>([]);
  const [saved, setSaved] = React.useState(false);
  const [transcript, setTranscript] = React.useState<Transcript | null>(null);
  const [tab, setTab] = React.useState<Tab>("visual");
  const [genStatus, setGenStatus] = React.useState<any>(null);
  const videoRef = React.useRef<HTMLVideoElement>(null);

  React.useEffect(() => {
    if (!id) return;
    api.getJob(id).then(j => {
      setJob(j);
      if (j.plan) setPlanText(JSON.stringify(j.plan, null, 2));
    });
    api.getTranscript(id).then(setTranscript).catch(() => {});
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
          api.getTranscript(id).then(setTranscript).catch(() => {});
        }
      }).catch(() => {});
    }, 1500);
    return () => clearInterval(iv);
  }, [id, genStatus?.status]);

  const parsedPlan = React.useMemo(() => {
    try { return JSON.parse(planText); } catch { return null; }
  }, [planText]);

  React.useEffect(() => {
    if (!id || !parsedPlan) { setErrors(planText.trim() ? ["invalid JSON"] : []); return; }
    const t = setTimeout(async () => {
      const r = await api.validate(id, parsedPlan);
      setErrors(r.errors);
    }, 400);
    return () => clearTimeout(t);
  }, [planText, parsedPlan, id]);

  async function save() {
    if (!id || !parsedPlan) return;
    const r = await api.putPlan(id, parsedPlan);
    if (!r.ok) setErrors(r.errors || []);
    else { setSaved(true); setTimeout(() => setSaved(false), 2000); }
  }

  async function doRender(preview: boolean) {
    if (!id) return;
    await save();
    if (errors.length) return;
    await api.render(id, preview);
    nav(`/jobs/${id}/render`);
  }

  async function openKdenlive() {
    if (!id) return;
    await save();
    if (errors.length) return;
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

  if (!job) return <p>Loading…</p>;

  const isGenerating = genStatus?.status === "running";

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
          <h2>Transcript <span className="muted">({transcript.language})</span></h2>
          <TranscriptView
            transcript={transcript}
            plan={parsedPlan}
            onSeek={seekTo}
          />
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
        <button onClick={save} className="secondary">Save plan</button>
        <button onClick={() => doRender(true)}>Preview (540x960)</button>
        <button onClick={() => doRender(false)}>Render (1080x1920)</button>
        <button onClick={openKdenlive} className="secondary">Open in Kdenlive</button>
        <a href={api.planUrl(job.id)}><button className="secondary">Download plan.json</button></a>
      </div>
    </div>
  );
}


/* ---------- Transcript view with clickable words ---------- */

function TranscriptView({ transcript, plan, onSeek }: {
  transcript: Transcript; plan: any; onSeek: (t: number) => void;
}) {
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
          className={`tw ${removedRanges.has(i) ? "tw-removed" : ""}`}
          title={`${w.start.toFixed(2)}s — ${w.end.toFixed(2)}s (${(w.prob * 100).toFixed(0)}%)`}
          onClick={() => onSeek(w.start)}
        >
          {w.w}{" "}
        </span>
      ))}
    </div>
  );
}


/* ---------- Visual plan editor ---------- */

function VisualEditor({ plan, onUpdate, onDelete, onSeek }: {
  plan: any;
  onUpdate: (path: (string | number)[], value: any) => void;
  onDelete: (arrayPath: string[], index: number) => void;
  onSeek: (t: number) => void;
}) {
  return (
    <div className="visual-editor">
      {/* Segments */}
      <h3>Segments ({plan.segments?.length || 0})</h3>
      {plan.segments?.map((seg: any, i: number) => (
        <div key={seg.id || i} className="ve-item" onClick={() => onSeek(seg.in)}>
          <span className="ve-id">{seg.id}</span>
          <span className="muted">{seg.in.toFixed(2)}s → {seg.out.toFixed(2)}s</span>
          <label>Zoom from:
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
          <button className="danger-sm" onClick={e => { e.stopPropagation(); onDelete(["segments"], i); }}>✕</button>
        </div>
      ))}

      {/* Captions */}
      <h3>Captions ({plan.captions?.length || 0})</h3>
      {plan.captions?.map((cap: any, i: number) => (
        <div key={i} className="ve-item" onClick={() => onSeek(cap.start)}>
          <span className={`ve-style ve-${cap.style}`}>{cap.style}</span>
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
