import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, Job } from "./api";
import { Timeline } from "./Timeline";

export default function PlanReview() {
  const { id } = useParams();
  const nav = useNavigate();
  const [job, setJob] = React.useState<Job | null>(null);
  const [planText, setPlanText] = React.useState("");
  const [errors, setErrors] = React.useState<string[]>([]);
  const [saved, setSaved] = React.useState(false);
  const videoRef = React.useRef<HTMLVideoElement>(null);

  React.useEffect(() => {
    if (!id) return;
    api.getJob(id).then(j => {
      setJob(j);
      if (j.plan) setPlanText(JSON.stringify(j.plan, null, 2));
    });
  }, [id]);

  const parsedPlan = React.useMemo(() => {
    try { return JSON.parse(planText); } catch { return null; }
  }, [planText]);

  // debounced live validate
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
    // engine needs project.mlt — trigger a build via a lightweight non-preview render is heavy;
    // instead reuse the render endpoint's build step by calling it if not yet rendered.
    try {
      await api.openKdenlive(id);
    } catch (e: any) {
      // if project.mlt missing, fall back to running a fast preview build then retry
      await api.render(id, true);
      alert("Building project first — try Open in Kdenlive again when render finishes.");
    }
  }

  if (!job) return <p>Loading…</p>;

  return (
    <div>
      <h1>Job {job.id}</h1>
      <div className="grid2">
        <div className="card">
          <h2>Raw video</h2>
          <video ref={videoRef} src={api.rawUrl(job.id)} controls preload="metadata" />
        </div>
        <div className="card">
          <h2>Timeline</h2>
          <Timeline plan={parsedPlan} onSeek={t => {
            if (videoRef.current) { videoRef.current.currentTime = t; videoRef.current.play(); }
          }} />
        </div>
      </div>

      <div className="card">
        <h2>Plan (JSON)</h2>
        <textarea rows={22} value={planText} onChange={e => setPlanText(e.target.value)} />
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
