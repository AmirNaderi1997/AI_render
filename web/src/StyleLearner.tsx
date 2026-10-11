import React from "react";
import { api } from "./api";
import { Link } from "react-router-dom";
import { EmptyState, LoadingState, friendlyError } from "./ui";

const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "mkv", "webm", "m4v"]);
const errorText = (error: unknown) => {
  const message = error instanceof Error ? error.message : "";
  const detail = message.match(/^(?:400|409|422) (.+)$/s);
  return detail ? detail[1] : friendlyError(error, "update the learned style");
};

function ReferenceVideoPreview({ refId, name }: { refId: string; name: string }) {
  const [src, setSrc] = React.useState("");
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    let cancelled = false;
    let objectUrl = "";
    setSrc("");
    setError("");
    void api.authenticatedObjectUrl(api.styleReferenceVideoUrl(refId)).then(url => {
      if (cancelled) URL.revokeObjectURL(url);
      else { objectUrl = url; setSrc(url); }
    }).catch(reason => {
      if (!cancelled) setError(friendlyError(reason, "load the reference preview"));
    });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [refId]);

  if (error) return <p className="errors" role="alert">Preview unavailable: {error}</p>;
  if (!src) return <p className="muted" role="status">Loading preview…</p>;
  return <video controls preload="metadata" src={src} aria-label={`Preview of ${name}`} style={{ display: "block", width: "100%", maxWidth: 480, maxHeight: 270, marginTop: 10, borderRadius: 8, background: "#000" }} />;
}

export default function StyleLearner() {
  const [profile, setProfile] = React.useState<any>(null);
  const [analyses, setAnalyses] = React.useState<any[]>([]);
  const [feedback, setFeedback] = React.useState<any>(null);
  const [uploading, setUploading] = React.useState(false);
  const [uploadPercent, setUploadPercent] = React.useState(0);
  const [uploadMsg, setUploadMsg] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [rebuilding, setRebuilding] = React.useState(false);
  const [actionStatus, setActionStatus] = React.useState("");
  const [error, setError] = React.useState("");
  const fileInput = React.useRef<HTMLInputElement>(null);
  const reloadSeq = React.useRef(0);
  const hasLoaded = React.useRef(false);
  const mounted = React.useRef(true);
  React.useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const reload = React.useCallback(async () => {
    const seq = ++reloadSeq.current;
    if (!hasLoaded.current) setLoading(true);
    const [profileResult, analysesResult, feedbackResult] = await Promise.allSettled([
      api.getLearnedProfile(), api.listReferenceAnalyses(), api.getFeedbackSummary(),
    ]);
    if (!mounted.current || seq !== reloadSeq.current) return;
    const failures: string[] = [];
    if (profileResult.status === "fulfilled") setProfile(profileResult.value);
    else failures.push(`Profile: ${errorText(profileResult.reason)}`);
    if (analysesResult.status === "fulfilled") setAnalyses(analysesResult.value.analyses);
    else failures.push(`References: ${errorText(analysesResult.reason)}`);
    if (feedbackResult.status === "fulfilled") setFeedback(feedbackResult.value);
    else failures.push(`Feedback: ${errorText(feedbackResult.reason)}`);
    hasLoaded.current = true;
    setError(failures.join("\n"));
    setLoading(false);
  }, []);

  React.useEffect(() => { void reload(); }, [reload]);

  async function handleUpload(files: FileList | null) {
    if (!files?.length || uploading || busy || loading) return;
    setUploading(true);
    setUploadMsg("");
    setError("");
    let count = 0;
    const messages: string[] = [];
    try {
      const list = Array.from(files);
      for (const [index, file] of list.entries()) {
        const extension = file.name.split(".").pop()?.toLowerCase();
        if (!extension || !VIDEO_EXTENSIONS.has(extension) || file.size === 0 || file.size > 500_000_000) {
          messages.push(`${file.name}: ${!extension || !VIDEO_EXTENSIONS.has(extension) ? "Use MP4, MOV, MKV, WEBM, or M4V" : file.size === 0 ? "File is empty" : "Maximum file size is 500 MB"}`);
          continue;
        }
        setUploadPercent(0);
        setUploadMsg(`Analyzing ${file.name} (${index + 1} of ${list.length})…`);
        try {
          await api.analyzeReference(file, setUploadPercent);
          count++;
        } catch (e) {
          messages.push(`${file.name}: ${errorText(e)}`);
        }
      }
      if (count > 0) {
        try { await api.rebuildLearnedProfile(); }
        catch (e) { messages.push(`Profile rebuild failed: ${errorText(e)}`); }
      }
      messages.unshift(`Analyzed ${count} reel(s).`);
    } finally {
      if (mounted.current) {
        setUploadMsg(messages.join("\n"));
        setUploading(false);
        if (fileInput.current) fileInput.current.value = "";
        await reload();
      }
    }
  }

  async function handleReset() {
    if (!confirm("Reset to default style? This removes the learned profile but keeps reference reels for rebuilding.")) return;
    setBusy(true); setError("");
    try {
      await api.resetLearnedProfile();
      await reload();
      setUploadMsg("Reset to default style. Reference reels are retained; use Rebuild Profile to restore the learned style.");
    } catch (e) { setError(`Reset failed: ${errorText(e)}`); }
    finally { setBusy(false); }
  }

  async function handleDeleteAnalysis(filename: string) {
    setBusy(true); setError("");
    try {
      await api.deleteReferenceAnalysis(filename);
      await reload();
      setUploadMsg("Reference removed and profile updated.");
    } catch (e) {
      await reload();
      setError(`Reference update failed: ${errorText(e)}`);
    } finally { setBusy(false); }
  }

  async function handleRebuild() {
    setBusy(true); setRebuilding(true); setError(""); setActionStatus("Rebuilding profile from your analyzed reels…");
    try {
      const result = await api.rebuildLearnedProfile();
      await reload();
      setActionStatus(`Profile rebuilt from ${result.sample_count} reference reel${result.sample_count === 1 ? "" : "s"}.`);
    } catch (e) {
      setActionStatus("");
      setError(`Profile rebuild failed: ${errorText(e)}`);
    } finally { setBusy(false); setRebuilding(false); }
  }

  async function handleEnabled(enabled: boolean) {
    setBusy(true); setError("");
    try { await api.updateLearnedProfile({ enabled }); await reload(); }
    catch (e) { setError(`Could not update learned style: ${errorText(e)}`); }
    finally { setBusy(false); }
  }

  const defaultPreset = {
    "editing.max_static_sec": 4.0,
    "captions.max_words": 5,
    "music.default_volume_db": -14,
  };

  return (
    <div>
      <h1>Style Learner</h1>
      <p className="muted">
        Upload your own edited reels to teach the AI your editing style.
        The system learns your cut rhythm, pacing, caption density, and more.
      </p>
      <p className="muted">Style Learner analyzes video references. To build a reusable look from still images, use the <Link to="/style-library">Styles &amp; Fonts Library</Link>.</p>
      {loading && <LoadingState label="Loading style learner…" />}
      {error && <div className="errors" role="alert" style={{ whiteSpace: "pre-wrap" }}>{error} <button type="button" className="secondary" onClick={() => void reload()}>Retry</button></div>}

      {/* Upload section */}
      <div className="card">
        <h2>Reference Reels</h2>
        <p className="muted">
          Upload finished reels you've edited. The more references, the better the AI learns your style.
          {profile?.sample_count > 0 && ` (${profile.sample_count} analyzed)`}
        </p>
        <div
          style={{
            border: "2px dashed var(--border)", borderRadius: "var(--radius-sm)",
            padding: 32, textAlign: "center", marginBottom: 16,
            opacity: uploading ? 0.5 : 1,
          }}
          onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); if (!uploading && !busy && !loading) void handleUpload(e.dataTransfer.files); }}
        >
          <p role={uploading ? "status" : undefined}>{uploading ? `Uploading/analyzing... ${uploadPercent}% uploaded` : "Drag & drop reference reels here (MP4, MOV, MKV, WEBM, M4V; 500 MB max each)"}</p>
          <input ref={fileInput} type="file" accept=".mp4,.mov,.mkv,.webm,.m4v" multiple aria-label="Upload reference reels"
            onChange={e => void handleUpload(e.target.files)} disabled={uploading || busy || loading} />
        </div>
        {uploadMsg && <pre className="muted" role="status" style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{uploadMsg}</pre>}

        {!loading && analyses.length === 0 && <EmptyState icon="🎞" title="No reference reels yet" description="Upload three finished reels above to activate your learned style." />}

        {analyses.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <h3>Analyzed Reels ({analyses.length})</h3>
            {analyses.map(a => (
              <div key={a._file} className="ve-item" style={{ flexDirection: "column", alignItems: "stretch" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <b>{a.source_file || a._file}</b>
                  <span className="muted">
                    {a.total_duration?.toFixed(1)}s · {a.cut_count} cuts · avg {a.cut_lengths?.avg?.toFixed(2)}s
                  </span>
                  <button type="button" className="danger-sm" aria-label={`Remove ${a.source_file || a._file}`} disabled={uploading || busy || loading} title={(uploading || busy || loading) ? "Wait for loading to finish." : undefined} onClick={() => void handleDeleteAnalysis(a._file)}>&#10005;</button>
                </div>
                <div style={{ display: "flex", gap: 16, fontSize: 12, marginTop: 6 }}>
                  <span>Min cut: {a.cut_lengths?.min?.toFixed(2)}s</span>
                  <span>Max cut: {a.cut_lengths?.max?.toFixed(2)}s</span>
                  <span>Pacing: {a.pacing?.trend}</span>
                  {a.audio?.mean_volume_db != null && <span>Avg volume: {a.audio.mean_volume_db?.toFixed(1)} dB</span>}
                </div>
                <ReferenceVideoPreview refId={a._file} name={a.source_file || a._file} />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Profile view */}
      {profile && (
        <div className="card">
          <div className="section-header">
            <h2>Learned Profile</h2>
            <span className={profile.active ? "status-badge done" : "status-badge"}>
              {profile.active ? (profile.enabled ? "Active" : "Paused") : profile.sample_count >= 3 ? "Needs rebuild" : `Need ${Math.max(0, 3 - (profile.sample_count || 0))} more reels`}
            </span>
          </div>

          {Object.keys(profile.metrics || {}).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <h3>Metrics</h3>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
                {Object.entries(profile.metrics as Record<string, any>).map(([key, value]) => (
                  <div key={key} style={{
                    padding: 12, background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--border)",
                  }}>
                    <div style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{key.replace(/_/g, " ")}</div>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>
                      {typeof value === "number" ? value.toFixed(2) : String(value)}
                    </div>
                    {profile.confidence?.[key] != null && (
                      <div style={{ marginTop: 4 }}>
                        <div style={{
                          height: 4, borderRadius: 2, background: "var(--border)",
                          overflow: "hidden",
                        }}>
                          <div style={{
                            width: `${(profile.confidence[key] as number) * 100}%`,
                            height: "100%",
                            background: (profile.confidence[key] as number) >= 0.6 ? "var(--success)" : "var(--warning)",
                          }} />
                        </div>
                        <span style={{ fontSize: 10, color: "var(--text-tertiary)" }}>
                          confidence: {((profile.confidence[key] as number) * 100).toFixed(0)}%
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Comparison view */}
          {profile.active && profile.preset_overrides && Object.keys(profile.preset_overrides).length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h3>Your Style vs AI Default</h3>
              <table style={{ width: "100%", fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Metric</th>
                    <th style={{ textAlign: "right" }}>AI Default</th>
                    <th style={{ textAlign: "right" }}>Your Style</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(profile.preset_overrides as Record<string, any>).flatMap(([section, values]) =>
                    Object.entries(values as Record<string, any>).map(([key, value]) => (
                      <tr key={`${section}.${key}`}>
                        <td>{section}.{key}</td>
                        <td style={{ textAlign: "right", color: "var(--text-tertiary)" }}>
                          {(defaultPreset as any)[`${section}.${key}`] ?? "—"}
                        </td>
                        <td style={{ textAlign: "right", fontWeight: 600 }}>
                          {typeof value === "number" ? value.toFixed(1) : String(value)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Few-shot examples */}
      {profile?.few_shot_examples?.length > 0 && (
        <div className="card">
          <h2>Learned Examples</h2>
          <p className="muted">Representative segment sequences extracted from your reference reels:</p>
          {profile.few_shot_examples.map((ex: any, i: number) => (
            <div key={i} className="ve-item" style={{ flexDirection: "column", alignItems: "stretch" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <b>{ex.source}</b>
                <span className="muted">{ex.total_duration}s · {ex.segment_count} segments · avg {ex.avg_cut_length}s</span>
              </div>
              {ex.segments_preview && (
                <div style={{ fontSize: 11, fontFamily: "monospace", marginTop: 4 }}>
                  {ex.segments_preview.map((s: any) => `${s.id}: ${s.in}→${s.out}`).join(" | ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Feedback summary */}
      {feedback && feedback.total_events > 0 && (
        <div className="card">
          <h2>Edit Feedback Summary</h2>
          <p className="muted">
            {feedback.total_events} corrections across {feedback.jobs_with_feedback} job(s)
          </p>
          {feedback.change_frequency && Object.keys(feedback.change_frequency).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <h3>Correction Frequency</h3>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {Object.entries(feedback.change_frequency as Record<string, number>)
                  .sort((a, b) => (b[1] as number) - (a[1] as number))
                  .map(([type, count]) => (
                    <div key={type} style={{
                      padding: "6px 12px", background: "var(--bg-elevated)",
                      borderRadius: "var(--radius-sm)", border: "1px solid var(--border)",
                      fontSize: 12,
                    }}>
                      <span style={{ fontWeight: 600 }}>{count}x</span>{" "}
                      {type.replace(/_/g, " ")}
                    </div>
                  ))}
              </div>
            </div>
          )}
          {feedback.effect_corrections && Object.keys(feedback.effect_corrections).length > 0 && (
            <div style={{ marginTop: 12 }}>
              <h3>Effect Replacements</h3>
              {Object.entries(feedback.effect_corrections as Record<string, Record<string, number>>).map(([old, replacements]) => (
                <div key={old} className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                  <span style={{ textDecoration: "line-through" }}>{old}</span> →{" "}
                  {Object.entries(replacements).map(([n, c]) => `${n} (${c}x)`).join(", ")}
                </div>
              ))}
            </div>
          )}
          {typeof feedback.segment_duration_bias === "number" && feedback.segment_duration_bias !== 0 && (
            <p className="muted" style={{ marginTop: 8 }}>
              Segment duration bias: {feedback.segment_duration_bias > 0 ? "+" : ""}{feedback.segment_duration_bias.toFixed(2)}s
              (users tend to {feedback.segment_duration_bias > 0 ? "lengthen" : "shorten"} segments)
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="action-bar">
        {actionStatus && <span role="status" aria-live="polite">{rebuilding && <span className="ui-spinner" aria-hidden="true" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 8 }} />}{actionStatus}</span>}
        <label className="muted">
          <input type="checkbox" checked={Boolean(profile?.active && profile?.enabled)}
            onChange={e => void handleEnabled(e.target.checked)}
            disabled={!profile?.active || uploading || busy || loading} />
          Apply learned style to future plans without a pinned style
        </label>
        <button type="button" className="secondary" disabled={uploading || busy || loading || !Object.keys(profile?.metrics || {}).length} title={(uploading || busy || loading || !Object.keys(profile?.metrics || {}).length) ? "Analyze reference reels before saving a style." : undefined} onClick={() => void handleReset()}>Reset to Default</button>
        {analyses.length > 0 && (
          <button type="button" disabled={uploading || busy || loading} aria-busy={rebuilding} title={(uploading || busy || loading) ? "Wait for loading to finish." : "Recalculate your learned profile from all analyzed reels."} onClick={() => void handleRebuild()}>{rebuilding ? "Rebuilding…" : "Rebuild Profile"}</button>
        )}
      </div>
    </div>
  );
}
