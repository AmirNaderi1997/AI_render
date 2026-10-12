import React from "react";
import { useParams } from "react-router-dom";
import { api, type MusicStatus } from "./api";
import { PremiereCard } from "./PremiereCard";
import { AuthenticatedMedia } from "./AuthenticatedMedia";
import QCReview from "./QCReview";
import { Breadcrumbs, JobWorkflow, LoadingState, NextStep, friendlyError } from "./ui";
import { completeDenoise, trackDenoise } from "./taskNotifications";

const TERMINAL_STATUSES = new Set(["completed", "failed", "error", "cancelled", "done", "ready", "skipped"]);

function DenoiseCard({ id }: { id: string }) {
  const [state, setState] = React.useState<any>(null);
  const [level, setLevel] = React.useState<"light" | "medium" | "heavy">("medium");
  const [preserveVoice, setPreserveVoice] = React.useState(true);
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
      if (s.status === "processing") trackDenoise(id);
      if (s.status === "ready") completeDenoise(id);
      setStatusError("");
      if (s.status === "ready" && !samplesRequested.current) {
        samplesRequested.current = true;
        setSamplesLoading(true);
        api.getDenoiseCompare(id).then(result => { setSamples(result); setSamplesError(""); })
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
      await api.triggerDenoise(id, level, preserveVoice);
      trackDenoise(id);
      poll();
    } catch (e) { setError(friendlyError(e, "start audio cleanup")); }
    finally { setLoading(false); }
  }

  async function handleApprove() {
    setLoading(true); setError("");
    try { await api.applyDenoise(id); poll(); }
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
      await api.triggerDenoise(id, level, preserveVoice);
      trackDenoise(id);
      poll();
    } catch (e) { setError(friendlyError(e, "reprocess the audio")); }
    finally { setLoading(false); }
  }

  const controls = (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16, marginBottom: 12 }}>
      <label>
        Strength{" "}
        <select value={level} onChange={e => setLevel(e.target.value as "light" | "medium" | "heavy")}>
          <option value="light">Light</option>
          <option value="medium">Medium</option>
          <option value="heavy">Heavy</option>
        </select>
      </label>
      <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input type="checkbox" checked={preserveVoice} onChange={e => setPreserveVoice(e.target.checked)} />
        Preserve Voice
      </label>
    </div>
  );

  return (
    <div className="card">
      <div className="section-header">
        <h2>Reduce Noise</h2>
        {approved && (
          <span className="status-badge done" style={{ fontSize: 11 }}>
            Denoised ({state.level ?? "custom"})
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
          {controls}
          <button onClick={handleStart} disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>
            {loading ? "Starting..." : "Reduce Noise"}
          </button>
        </div>
      )}

      {processing && (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="generating-pulse" style={{
            width: 8, height: 8, borderRadius: "50%", background: "var(--accent)"
          }} />
          <span>Reducing noise… this can take a minute</span>
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
          <div style={{ marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
            {controls}
            {(level !== state.level || preserveVoice !== state.preserve_voice) && (
              <button className="secondary" onClick={handleAdjust} disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}
                style={{ fontSize: 12, padding: "6px 12px" }}>
                {loading ? "..." : "Re-process"}
              </button>
            )}
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
                  <p className="muted" style={{ marginBottom: 4 }}>Denoised</p>
                  <AuthenticatedMedia as="audio" controls src={api.denoiseAudioUrl(id, "cleaned")}
                    style={{ width: "100%" }} />
                </div>
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            {!approved && (
              <button onClick={handleApprove} disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>Apply Denoised Audio</button>
            )}
            {!bypassed && (
              <button className="secondary" onClick={() => handleBypass(true)} disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>Use Original</button>
            )}
            {(approved || bypassed) && (
              <button className="secondary" onClick={() => handleBypass(false)} disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>
                Reset Choice
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

type MixSettings = { volume_level: number; fade_in_seconds: number; fade_out_seconds: number };

function formatDuration(seconds: number) {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function MusicCard({ id, renderStatus, renderOutput }: { id: string; renderStatus?: string; renderOutput?: string | null }) {
  const [music, setMusic] = React.useState<MusicStatus | null>(null);
  const [volume, setVolume] = React.useState(30);
  const [fadeIn, setFadeIn] = React.useState(2);
  const [fadeOut, setFadeOut] = React.useState(3);
  const [uploadPct, setUploadPct] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [previewNonce, setPreviewNonce] = React.useState(0);
  const fileInput = React.useRef<HTMLInputElement>(null);
  const syncedFile = React.useRef<string | null>(null);

  const load = React.useCallback(() => api.getMusicStatus(id).then(m => {
    setMusic(m);
    // Adopt the saved settings once per attached track; later edits stay local.
    if (m.attached && syncedFile.current !== m.file) {
      syncedFile.current = m.file;
      setVolume(Math.round(m.volume_level * 100));
      setFadeIn(m.fade_in_seconds);
      setFadeOut(m.fade_out_seconds);
    }
    if (!m.attached) syncedFile.current = null;
    return m;
  }).catch(e => { setError(friendlyError(e, "load music status")); return null; }), [id]);

  const mixing = music?.status === "queued" || music?.status === "running";
  const renderBusy = renderStatus === "queued" || renderStatus === "running";
  // Poll while a mix runs, and while a render runs (it auto-mixes attached music when it finishes).
  React.useEffect(() => {
    void load();
    if (!mixing && !renderBusy) return;
    const iv = setInterval(() => void load(), 2000);
    return () => clearInterval(iv);
  }, [load, mixing, renderBusy, renderStatus]);

  const settings: MixSettings = {
    volume_level: Math.min(100, Math.max(0, volume)) / 100,
    fade_in_seconds: Math.max(0, fadeIn || 0),
    fade_out_seconds: Math.max(0, fadeOut || 0),
  };
  const locked = busy || mixing || renderBusy || uploadPct !== null;
  const rendered = renderStatus === "done" && !!renderOutput;
  const mixCurrent = music?.status === "done" && !!music.output && music.mixed_from === renderOutput;

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError(""); setUploadPct(0);
    try {
      setMusic(await api.attachMusic(id, file, setUploadPct));
      syncedFile.current = null;
      await load();
    } catch (err) { setError(friendlyError(err, "add this music")); }
    finally { setUploadPct(null); }
  }

  async function run(action: () => Promise<unknown>, what: string) {
    setBusy(true); setError("");
    try { await action(); await load(); }
    catch (err) { setError(friendlyError(err, what)); }
    finally { setBusy(false); }
  }

  return (
    <div className="card">
      <div className="section-header">
        <h2>Background Music</h2>
        {mixCurrent && <span className="status-badge done" style={{ fontSize: 11 }}>Mixed</span>}
      </div>
      <input ref={fileInput} type="file" accept="audio/*,.mp3,.wav,.ogg,.m4a,.aac" onChange={onFile}
        style={{ display: "none" }} aria-label="Choose a music file" />
      {!music?.attached ? (
        <>
          <p className="muted">Add a track to mix under your video. It plays after every render automatically.</p>
          <button disabled={locked} title={(locked) ? "Wait for the current music operation to finish." : undefined} onClick={() => fileInput.current?.click()}>
            {uploadPct !== null ? "Uploading…" : "Add Music"}
          </button>
        </>
      ) : (
        <>
          <p style={{ margin: "0 0 12px" }}>
            <strong>{music.name}</strong> <span className="muted">· {formatDuration(music.duration_s)}</span>
          </p>
          <div style={{ display: "grid", gap: 12, maxWidth: 420 }}>
            <label>Volume: {volume}%
              <input type="range" min={0} max={100} step={1} value={volume} disabled={locked}
                onChange={e => setVolume(Number(e.target.value))} style={{ width: "100%" }} />
            </label>
            <div style={{ display: "flex", gap: 12 }}>
              <label>Fade in (s)
                <input type="number" min={0} max={60} step={0.5} value={fadeIn} disabled={locked}
                  onChange={e => setFadeIn(Number(e.target.value))} style={{ width: 90 }} />
              </label>
              <label>Fade out (s)
                <input type="number" min={0} max={60} step={0.5} value={fadeOut} disabled={locked}
                  onChange={e => setFadeOut(Number(e.target.value))} style={{ width: 90 }} />
              </label>
            </div>
          </div>
          <div style={{ marginTop: 12, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button className="secondary" disabled={locked} title={(locked) ? "Wait for the current music operation to finish." : undefined} onClick={() => setPreviewNonce(n => n + 1)}>Preview Mix</button>
            <button disabled={locked || !rendered} onClick={() => void run(() => api.mixMusic(id, settings), "apply the music")}
              title={rendered ? undefined : "Render the video first"}>
              {mixing ? "Mixing…" : "Apply to Render"}
            </button>
            <button className="secondary" disabled={locked} title={(locked) ? "Wait for the current music operation to finish." : undefined} onClick={() => fileInput.current?.click()}>Replace</button>
            <button className="secondary" disabled={locked} title={(locked) ? "Wait for the current music operation to finish." : undefined} onClick={() => void run(() => api.removeMusic(id), "remove the music")}>Remove Music</button>
          </div>
          {previewNonce > 0 && (
            <div style={{ marginTop: 12 }}>
              <AuthenticatedMedia as="audio" controls autoPlay src={api.musicMixPreviewUrl(id, settings, previewNonce)}
                aria-label="30-second mix preview" />
              <p className="muted" style={{ fontSize: 12 }}>First 30 seconds of the mix.</p>
            </div>
          )}
          {mixCurrent && music.output && (
            <div style={{ marginTop: 12 }}>
              <AuthenticatedMedia as="video" controls src={api.exportUrl(id, music.output)} aria-label="Video with music" />
              {music.technical_qc && <p className="muted">
                Mixed audio: {music.technical_qc.loudness_lufs ?? "unmeasured"} LUFS
                {music.technical_qc.true_peak_dbfs != null && ` · peak ${music.technical_qc.true_peak_dbfs} dBFS`}
              </p>}
              {music.technical_qc?.warnings.map((warning, i) => <p className="errors" key={i}>{warning}</p>)}
            </div>
          )}
        </>
      )}
      {uploadPct !== null && (
        <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={uploadPct} aria-label="Music upload progress"
          style={{ marginTop: 12, height: 8, background: "rgba(128,128,128,.25)", borderRadius: 4, overflow: "hidden" }}>
          <div style={{ width: `${uploadPct}%`, height: "100%", background: "currentColor", transition: "width .2s" }} />
        </div>
      )}
      {mixing && (
        <p className="muted" role="status" style={{ marginTop: 8 }}>Mixing music… {music?.progress ?? 0}%</p>
      )}
      {music?.status === "error" && (
        <p className="errors" role="alert" style={{ marginTop: 8 }}>{friendlyError(music.message, "mix the music")}</p>
      )}
      {error && <p className="errors" role="alert" style={{ marginTop: 8 }}>{error}</p>}
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
  const [job, setJob] = React.useState<import("./api").Job | null>(null);
  const [planError, setPlanError] = React.useState("");
  const currentJobId = React.useRef(id);
  currentJobId.current = id;

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
      if (isCurrent()) { setJob(j); if (j.plan) setPlan(j.plan); }
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
      <Breadcrumbs items={[{ label: "Jobs", to: "/jobs" }, { label: job?.raw_name || `Job ${id}`, to: `/jobs/${id}` }, { label: "Render & Export" }]} />
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
        <h1 style={{ marginBottom: 0 }}>Render</h1>
        <span className={`status-badge ${s.status === "done" ? "done" : s.status === "error" ? "error" : "running"}`}
          style={{ marginLeft: "auto" }}>
          {s.status}
        </span>
      </div>
      <JobWorkflow job={job} current={finished ? 4 : 3} renderStatus={s.status} />
      {finished && <NextStep>Review the export below, then download it or open it in Premiere.</NextStep>}

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

      <MusicCard id={id} renderStatus={s.status} renderOutput={s.output} />
      {finished && s.technical_qc && <div className="card" style={{ marginTop: 16 }}>
        <h2>Export checks</h2>
        <p className="muted">{s.technical_qc.width}×{s.technical_qc.height} · {s.technical_qc.duration_seconds}s
          {s.technical_qc.loudness_lufs != null && ` · ${s.technical_qc.loudness_lufs} LUFS`}
          {s.technical_qc.true_peak_dbfs != null && ` · peak ${s.technical_qc.true_peak_dbfs} dBFS`}</p>
        {s.technical_qc.warnings?.map((warning: string, i: number) => <p className="errors" key={i}>{warning}</p>)}
      </div>}

      {finished && s.output && (
        <div className="card" id="export">
          <div className="section-header">
            <h2>Latest Export</h2>
            <span className="muted">{s.output}</span>
          </div>
          <AuthenticatedMedia
            as="video"
            src={api.exportUrl(id, s.output)}
            preload="auto"
            aria-label={plan?.poster?.text ? `Video preview with embedded poster: ${plan.poster.text}` : "Video preview"}
            controls
          />
          <div style={{ marginTop: 12, display: "flex", gap: 10, alignItems: "center" }}>
            <button disabled={downloadBusy} title={(downloadBusy) ? "Wait for the current download to finish." : undefined} onClick={() => void download(api.exportUrl(id, s.output), s.output)}>{downloadBusy ? "Downloading…" : "Download"}</button>
            {plan?.content_type === "post" && (
              <button className="secondary" disabled={downloadBusy} title={(downloadBusy) ? "Wait for the current download to finish." : undefined} onClick={async () => {
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
              <button key={v} className="secondary" disabled={downloadBusy} title={(downloadBusy) ? "Wait for the current download to finish." : undefined} onClick={() => void download(api.exportUrl(id, v), v)} style={{
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

      <PremiereCard key={`${id}:${s.status}:${s.output || ""}`} id={id} renderDone={finished} />
    </div>
  );
}
