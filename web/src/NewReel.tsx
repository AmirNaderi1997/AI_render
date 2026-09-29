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
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [over, setOver] = React.useState(false);

  const inputRef = React.useRef<HTMLInputElement>(null);

  // Stop the browser navigating to a video dropped just outside the zone.
  React.useEffect(() => {
    const stop = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  }, []);

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
      nav(`/jobs/${job.id}`);
    } catch (e: any) {
      console.error("upload failed", e);
      setErr("Upload failed: " + String(e.message || e));
    } finally { setBusy(false); }
  }

  return (
    <div>
      <h1>New Reel</h1>

      <div className="card">
        <h2>1. Raw video</h2>
        {/* A <label htmlFor> opens the picker natively in every browser. The input is
            visually hidden (not display:none) so Safari keeps it focusable/clickable. */}
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
