import React from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";

function fmtSize(n: number) {
  return n >= 1e9 ? (n / 1e9).toFixed(2) + " GB" : (n / 1e6).toFixed(1) + " MB";
}

export default function NewReel() {
  const nav = useNavigate();
  const [video, setVideo] = React.useState<File | null>(null);
  const [planFile, setPlanFile] = React.useState<File | null>(null);
  const [planText, setPlanText] = React.useState("");
  const [style, setStyle] = React.useState("rafiei_reel");
  const [instruction, setInstruction] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [genStatus, setGenStatus] = React.useState<any>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [over, setOver] = React.useState(false);
  const [jobId, setJobId] = React.useState<string | null>(null);

  const inputRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    const stop = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  }, []);

  React.useEffect(() => {
    if (!generating || !jobId) return;
    const tick = () =>
      api.generateStatus(jobId).then(s => {
        setGenStatus(s);
        if (s.status === "done") {
          setGenerating(false);
          nav(`/jobs/${jobId}`);
        } else if (s.status === "error") {
          setGenerating(false);
          setErr("Plan generation failed: " + s.message);
        }
      }).catch(() => {});
    tick();
    const iv = setInterval(tick, 1500);
    return () => clearInterval(iv);
  }, [generating, jobId, nav]);

  function pick(f?: File | null) {
    if (!f) return;
    if (!(f.type.startsWith("video/") || /\.(mp4|mov)$/i.test(f.name))) {
      setErr(`"${f.name}" is not a video file (.mp4 / .mov)`); return;
    }
    setErr(null); setVideo(f);
  }

  async function onCreate() {
    if (!video) { setErr("Select a raw video first"); return; }
    setBusy(true); setErr(null);
    try {
      const plan = planFile ?? (planText.trim() ? planText : undefined);
      const { job, errors } = await api.createJob(video, plan);
      if (errors.length) setErr("Plan warnings: " + errors.join("; "));
      setJobId(job.id);
      nav(`/jobs/${job.id}`);
    } catch (e: any) {
      setErr("Upload failed: " + String(e.message || e));
    } finally { setBusy(false); }
  }

  async function onGenerate() {
    if (!video) { setErr("Select a raw video first"); return; }
    setBusy(true); setErr(null);
    try {
      const { job } = await api.createJob(video);
      setJobId(job.id);
      await api.generatePlan(job.id, { style, instruction: instruction.trim() });
      setGenerating(true);
    } catch (e: any) {
      setErr("Failed: " + String(e.message || e));
    } finally { setBusy(false); }
  }

  return (
    <div>
      <h1>New Reel</h1>

      <div className="card">
        <h2>1. Raw video</h2>
        <label
          htmlFor="vid"
          className={`dropzone ${over ? "over" : ""}`}
          style={{ display: "block", cursor: "pointer" }}
          onDragEnter={e => { e.preventDefault(); setOver(true); }}
          onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={e => {
            e.preventDefault(); setOver(false);
            pick(e.dataTransfer.files[0]);
          }}
        >
          {video ? <>Selected: <b>{video.name}</b> ({fmtSize(video.size)})</> :
            "Drag & drop a video here, or click to browse"}
        </label>
        <input id="vid" ref={inputRef} type="file"
          style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden" }}
          onChange={e => { pick(e.target.files?.[0]); e.target.value = ""; }} />
      </div>

      <div className="card">
        <h2>2. Style</h2>
        <select value={style} onChange={e => setStyle(e.target.value)}>
          <option value="rafiei_reel">Rafiei Reel Style</option>
        </select>
      </div>

      <div className="card">
        <h2>3. Instruction (optional)</h2>
        <input
          type="text"
          placeholder="e.g. Make the CTA stronger, add more punch-ins…"
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          style={{ width: "100%" }}
        />
      </div>

      <div className="card">
        <h2>4. Generate or upload plan</h2>
        <div className="row" style={{ gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={onGenerate} disabled={busy || generating || !video}
            style={{ background: "#2563eb" }}>
            {generating ? "Generating…" : "Generate Edit Plan"}
          </button>
          <span className="muted">— or upload a manual plan.json:</span>
        </div>

        {generating && genStatus && (
          <div style={{ marginTop: 12, padding: "8px 12px", background: "#1e293b", borderRadius: 6 }}>
            <div>Stage: <b>{genStatus.stage || "starting"}</b></div>
            <div className="muted">{genStatus.message}</div>
          </div>
        )}

        <div style={{ marginTop: 12 }}>
          <input type="file" accept="application/json" onChange={e => setPlanFile(e.target.files?.[0] || null)} />
          <textarea rows={6} placeholder='{"canvas": ..., "segments": [...], ...}'
            value={planText} onChange={e => setPlanText(e.target.value)}
            style={{ marginTop: 8 }} />
        </div>
      </div>

      {err && <div className="errors">{err}</div>}
      <button onClick={onCreate} disabled={busy || !video} className="secondary">
        {busy ? "Creating…" : "Create (with manual plan)"}
      </button>
    </div>
  );
}
