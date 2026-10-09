import React from "react";
import { useParams } from "react-router-dom";
import { api } from "./api";
import { PremiereCard } from "./PremiereCard";
import { AuthenticatedMedia, useAuthenticatedMediaUrl } from "./AuthenticatedMedia";
import QCReview from "./QCReview";
import { LoadingState, friendlyError } from "./ui";

const TERMINAL_STATUSES = new Set(["completed", "failed", "error", "cancelled", "done", "ready", "skipped"]);

function DenoiseCard({ id }: { id: string }) {
  const [state, setState] = React.useState<any>(null);
  const [strength, setStrength] = React.useState(0.5);
  const [samples, setSamples] = React.useState<any>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [statusError, setStatusError] = React.useState("");
  const [samplesError, setSamplesError] = React.useState("");
  const [samplesLoading, setSamplesLoading] = React.useState(false);
  const polling = React.useRef(false);
  const samplesRequested = React.useRef(false);

  const poll = React.useCallback(() => {
    if (polling.current) return;
    polling.current = true;
    return api.getDenoiseStatus(id).then(s => {
      setState(s);
      setStatusError("");
      if (s.status === "ready" && !samplesRequested.current) {
        samplesRequested.current = true;
        setSamplesLoading(true);
        api.getDenoiseSamples(id).then(result => { setSamples(result); setSamplesError(""); })
          .catch(e => { samplesRequested.current = false; setSamplesError(friendlyError(e, "load the audio comparison")); })
          .finally(() => setSamplesLoading(false));
      }
      return s;
    }).catch(e => {
      setStatusError(friendlyError(e, "load audio cleanup status"));
      return null;
    }).finally(() => { polling.current = false; });
  }, [id]);

  React.useEffect(() => {
    let iv: ReturnType<typeof setInterval>;
    const tick = () => {
      const request = poll();
      request?.then(status => {
        if (status && TERMINAL_STATUSES.has(status.status)) clearInterval(iv);
      });
    };
    tick();
    iv = setInterval(tick, 2000);
    return () => clearInterval(iv);
  }, [poll, state?.status]);

  const started = state && state.status !== "idle";
  const processing = state?.status === "processing";
  const ready = state?.status === "ready";
  const approved = state?.approved;
  const bypassed = state?.bypass;
  const skipped = state?.status === "skipped";

  async function handleStart() {
    setLoading(true);
    try {
      await api.startDenoise(id, strength);
      poll();
    } catch (e) { setError(friendlyError(e, "start audio cleanup")); }
    finally { setLoading(false); }
  }

  async function handleApprove() {
    setLoading(true); setError("");
    try { await api.approveDenoise(id); poll(); }
    catch (e) { setError(friendlyError(e, "approve cleaned audio")); }
    finally { setLoading(false); }
  }

  async function handleBypass(bypass: boolean) {
    setLoading(true); setError("");
    try { await api.bypassDenoise(id, bypass); poll(); }
    catch (e) { setError(friendlyError(e, "update your audio choice")); }
    finally { setLoading(false); }
  }

  async function handleAdjust() {
    setLoading(true);
    try {
      await api.adjustDenoise(id, strength);
      poll();
    } catch (e) { setError(friendlyError(e, "reprocess the audio")); }
    finally { setLoading(false); }
  }

  const strengthLabel = strength <= 0.3 ? "Light" : strength <= 0.6 ? "Medium" : "Strong";

  return (
    <div className="card">
      <div className="section-header">
        <h2>Audio Cleanup</h2>
        {approved && (
          <span className="status-badge done" style={{ fontSize: 11 }}>
            Denoised at {(state.strength * 100).toFixed(0)}%
          </span>
        )}
        {bypassed && <span className="status-badge" style={{ fontSize: 11 }}>Using original</span>}
        {skipped && <span className="status-badge" style={{ fontSize: 11 }}>Skipped</span>}
      </div>
      {!state && !statusError && <LoadingState label="Checking audio cleanup…" rows={2} />}
      {statusError && <p className="errors" role="alert">{statusError}</p>}
      {error && <div className="errors" role="alert">{error}</div>}

      {state && !started && (
        <div>
          <p className="muted" style={{ marginBottom: 12 }}>
            Clean background noise from speech audio before mixing with music and SFX.
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
            <label style={{ flex: 1 }}>
              Strength: {strengthLabel} ({(strength * 100).toFixed(0)}%)
              <input type="range" min="0" max="1" step="0.05"
                value={strength} onChange={e => setStrength(parseFloat(e.target.value))}
                style={{ width: "100%", marginTop: 4 }} />
            </label>
          </div>
          <button onClick={handleStart} disabled={loading}>
            {loading ? "Starting..." : "Clean Speech Audio"}
          </button>
        </div>
      )}

      {processing && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="generating-pulse" style={{
            width: 8, height: 8, borderRadius: "50%", background: "var(--accent)"
          }} />
          <span>Processing noise removal...</span>
        </div>
      )}

      {state?.status === "error" && (
        <div className="errors" role="alert">{friendlyError(state.message, "clean the audio")}</div>
      )}

      {skipped && (
        <p className="muted">{state.message}</p>
      )}

      {ready && (
        <div>
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
              <label style={{ flex: 1 }}>
                Strength: {strengthLabel} ({(strength * 100).toFixed(0)}%)
                <input type="range" min="0" max="1" step="0.05"
                  value={strength} onChange={e => setStrength(parseFloat(e.target.value))}
                  style={{ width: "100%", marginTop: 4 }} />
              </label>
              {Math.abs(strength - state.strength) > 0.01 && (
                <button className="secondary" onClick={handleAdjust} disabled={loading}
                  style={{ fontSize: 12, padding: "6px 12px" }}>
                  {loading ? "..." : "Re-process"}
                </button>
              )}
            </div>
          </div>

          {samplesLoading && !samples && <LoadingState label="Loading audio comparison…" rows={2} />}
          {samplesError && <p className="errors" role="alert">{samplesError}</p>}
          {samples && (
            <div style={{ marginBottom: 16 }}>
              <p style={{ fontWeight: 600, marginBottom: 8 }}>A/B Comparison</p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <p className="muted" style={{ marginBottom: 4 }}>Original</p>
                  <AuthenticatedMedia as="audio" controls src={api.denoiseAudioUrl(id, "original")}
                    style={{ width: "100%" }} />
                </div>
                <div>
                  <p className="muted" style={{ marginBottom: 4 }}>Cleaned</p>
                  <AuthenticatedMedia as="audio" controls src={api.denoiseAudioUrl(id, "cleaned")}
                    style={{ width: "100%" }} />
                </div>
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            {!approved && (
              <button onClick={handleApprove} disabled={loading}>Approve &amp; Use</button>
            )}
            {!bypassed && (
              <button className="secondary" onClick={() => handleBypass(true)} disabled={loading}>Use Original</button>
            )}
            {(approved || bypassed) && (
              <button className="secondary" onClick={() => handleBypass(false)} disabled={loading}>
                Reset Choice
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function Render() {
  const { id } = useParams();
  const [s, setS] = React.useState<any>(null);
  const [statusError, setStatusError] = React.useState("");
  const [downloadBusy, setDownloadBusy] = React.useState(false);
  const [downloadError, setDownloadError] = React.useState("");
  const [rerenderError, setRerenderError] = React.useState("");
  const [plan, setPlan] = React.useState<any>(null);
  const [planError, setPlanError] = React.useState("");
  const currentJobId = React.useRef(id);
  currentJobId.current = id;
  const posterUrl = useAuthenticatedMediaUrl(id && s?.output
    ? api.exportUrl(id, s.output.replace(/\.mp4$/, "_poster.jpg")) : undefined);

  React.useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let active = true;
    let inFlight = false;
    let iv: ReturnType<typeof setInterval>;
    const isCurrent = () => active && !controller.signal.aborted && currentJobId.current === id;
    const tick = () => {
      if (inFlight) return;
      inFlight = true;
      api.renderStatus(id, controller.signal).then(next => {
        if (!isCurrent()) return;
        setS(next); setStatusError("");
        if (TERMINAL_STATUSES.has(next.status)) clearInterval(iv);
      }).catch(e => {
        if (isCurrent()) setStatusError(friendlyError(e, "load render status"));
      }).finally(() => { inFlight = false; });
    };
    tick();
    iv = setInterval(tick, 1000);
    return () => { active = false; clearInterval(iv); controller.abort(); };
  }, [id, s?.status]);

  React.useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let active = true;
    const isCurrent = () => active && !controller.signal.aborted && currentJobId.current === id;
    api.getJob(id, controller.signal).then(j => {
      if (isCurrent() && j.plan) setPlan(j.plan);
    }).catch(e => {
      if (isCurrent()) setPlanError(friendlyError(e, "load export details"));
    });
    return () => { active = false; controller.abort(); };
  }, [id]);

  async function download(url: string, filename: string) {
    setDownloadBusy(true); setDownloadError("");
    try { await api.downloadAuthenticated(url, filename); }
    catch (e) { setDownloadError(friendlyError(e, "download this export")); }
    finally { setDownloadBusy(false); }
  }

  if (!id || !s) return statusError ? <div className="errors" role="alert">{statusError} <button className="secondary" onClick={() => window.location.reload()}>Try again</button></div> : <LoadingState label="Loading render status…" />;

  const finished = s.status === "done";

  return (
    <div>
      {statusError && <p className="errors" role="alert">{statusError}</p>}
      {planError && <p className="errors" role="alert">{planError}</p>}
      {downloadError && <p className="errors" role="alert">{downloadError}</p>}
      {rerenderError && <p className="errors" role="alert">{rerenderError}</p>}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <a href={`/jobs/${id}`} style={{ color: "var(--text-tertiary)", fontSize: 13 }}>&larr; Back to plan</a>
        <span style={{ color: "var(--text-tertiary)" }}>/</span>
        <h1 style={{ marginBottom: 0 }}>Render</h1>
        <span className={`status-badge ${s.status === "done" ? "done" : s.status === "error" ? "error" : "running"}`}
          style={{ marginLeft: "auto" }}>
          {s.status}
        </span>
      </div>

      <div className="card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <span style={{ fontWeight: 600 }}>Progress</span>
          <span style={{ fontWeight: 700, color: "var(--accent-hover)", fontFamily: "SF Mono, monospace" }}>
            {s.progress}%
          </span>
        </div>
        <div className="progress" role="progressbar" aria-label="Render progress" aria-valuenow={s.progress || 0} aria-valuemin={0} aria-valuemax={100}>
          <div style={{ width: `${s.progress}%` }} />
        </div>
        {s.status === "error" ? <p className="errors" role="alert" style={{ marginTop: 8 }}>{friendlyError(s.message, "finish this render")} <a href={`/jobs/${id}`}>Return to the edit plan</a></p>
          : s.message && <p className="muted" role="status" style={{ marginTop: 8 }}>{s.message}</p>}
        {plan?.music && (
          <p className="muted" style={{ marginTop: 8 }}>
            Music: {plan.music.file?.split("/").pop()} at {plan.music.volume_db ?? -14} dB
            {plan.music.duck?.length ? ` · ${plan.music.duck.length} duck range(s)` : ""}
          </p>
        )}
      </div>

      <DenoiseCard id={id} />

      {finished && s.output && (
        <div className="card">
          <div className="section-header">
            <h2>Latest Export</h2>
            <span className="muted">{s.output}</span>
          </div>
          <AuthenticatedMedia as="video" src={api.exportUrl(id, s.output)} poster={posterUrl} controls />
          <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
            <button disabled={downloadBusy} onClick={() => void download(api.exportUrl(id, s.output), s.output)}>{downloadBusy ? "Downloading…" : "Download"}</button>
            {plan?.content_type === "post" && (
              <button className="secondary" disabled={downloadBusy} onClick={async () => {
                setDownloadBusy(true); setDownloadError("");
                try {
                  const blob = await api.exportImage(id);
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url; a.download = `${id}_post.png`; a.click();
                  URL.revokeObjectURL(url);
                } catch (e) { setDownloadError(friendlyError(e, "download the image")); }
                finally { setDownloadBusy(false); }
              }}>Download Image</button>
            )}
          </div>
          {plan?.generation_meta && (
            <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
              Provider: {plan.generation_meta.provider}
              {plan.generation_meta.total_cost != null && ` · Cost: $${plan.generation_meta.total_cost.toFixed(4)}`}
              {plan.generation_meta.provider?.startsWith("local_fixture") && (
                <div className="errors" role="status" style={{ marginTop: 8 }}>
                  Demo preview: this video uses placeholder color clips and is not ready for customers. Generate with a configured image provider and review the new render.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {s.versions?.length > 0 && (
        <div className="card">
          <h2>Previous Versions</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {s.versions.map((v: string) => (
              <button key={v} className="secondary" disabled={downloadBusy} onClick={() => void download(api.exportUrl(id, v), v)} style={{
                padding: "8px 14px",
                background: "rgba(255,255,255,0.02)",
                borderRadius: "var(--radius-sm)",
                fontSize: 13,
                fontFamily: "SF Mono, monospace",
                display: "flex",
                alignItems: "center",
                gap: 8
              }}>
                <span style={{ opacity: 0.5 }}>&#128190;</span> {v}
              </button>
            ))}
          </div>
        </div>
      )}

      <QCReview
        jobId={id}
        renderDone={finished}
        latestOutput={s.output}
        onRerender={async () => {
          setRerenderError("");
          try {
            await api.render(id, true);
            setS((prev: any) => ({ ...prev, status: "queued", progress: 0, message: "Re-rendering after QC fixes…" }));
          } catch (e: any) {
            setRerenderError(friendlyError(e, "start another preview after quality fixes"));
          }
        }}
      />

      <PremiereCard key={`${id}:${s.status}:${s.output || ""}`} id={id} />
    </div>
  );
}
