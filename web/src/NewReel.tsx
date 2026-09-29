import React from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";

export default function NewReel() {
  const nav = useNavigate();
  const [video, setVideo] = React.useState<File | null>(null);
  const [planFile, setPlanFile] = React.useState<File | null>(null);
  const [planText, setPlanText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [over, setOver] = React.useState(false);

  async function onCreate() {
    if (!video) { setErr("Select a raw video first"); return; }
    setBusy(true); setErr(null);
    try {
      const plan = planFile ?? (planText.trim() ? planText : undefined);
      const { job, errors } = await api.createJob(video, plan);
      if (errors.length) setErr("Plan warnings: " + errors.join("; "));
      nav(`/jobs/${job.id}`);
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally { setBusy(false); }
  }

  return (
    <div>
      <h1>New Reel</h1>

      <div className="card">
        <h2>1. Raw video</h2>
        <div
          className={`dropzone ${over ? "over" : ""}`}
          onDragOver={e => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={e => {
            e.preventDefault(); setOver(false);
            const f = e.dataTransfer.files[0];
            if (f) setVideo(f);
          }}
          onClick={() => document.getElementById("vid")!.click()}
        >
          {video ? <>Selected: <b>{video.name}</b> ({(video.size / 1e6).toFixed(1)} MB)</> :
            "Drag & drop a video here, or click to browse"}
          <input id="vid" type="file" accept="video/*" style={{ display: "none" }}
            onChange={e => setVideo(e.target.files?.[0] || null)} />
        </div>
      </div>

      <div className="card">
        <h2>2. Edit plan (optional now, required for render)</h2>
        <p className="muted">Upload a plan.json or paste it below.</p>
        <input type="file" accept="application/json" onChange={e => setPlanFile(e.target.files?.[0] || null)} />
        <textarea rows={10} placeholder='{"canvas": ..., "segments": [...], ...}'
          value={planText} onChange={e => setPlanText(e.target.value)}
          style={{ marginTop: 8 }} />
      </div>

      <div className="card">
        <h2>3. Style</h2>
        <select disabled defaultValue="rafiei_reel">
          <option value="rafiei_reel">Rafiei Reel Style</option>
        </select>
      </div>

      {err && <div className="errors">{err}</div>}
      <button onClick={onCreate} disabled={busy || !video}>{busy ? "Creating…" : "Create"}</button>
    </div>
  );
}
