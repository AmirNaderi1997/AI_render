import React from "react";
import { LoadingState, friendlyError } from "./ui";
import { api } from "./api";

const TERMINAL_STATUSES = new Set(["completed", "failed", "error", "cancelled", "done"]);

interface QCReviewProps {
  jobId: string;
  renderDone: boolean;
  latestOutput?: string;
  onRerender?: () => void | Promise<void>;
}

type QCStatus = {
  status: string;
  message: string;
  current_round: number;
  total_issues: number;
  fixed_issues: number;
  issues: any[];
  changes: any[];
};

export default function QCReview({ jobId, renderDone, latestOutput, onRerender }: QCReviewProps) {
  const [qc, setQC] = React.useState<QCStatus | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [applying, setApplying] = React.useState(false);
  const [ignored, setIgnored] = React.useState<Set<number>>(new Set());
  const [error, setError] = React.useState("");
  const [initialLoading, setInitialLoading] = React.useState(true);
  const polling = React.useRef(false);

  const poll = React.useCallback(() => {
    if (polling.current) return;
    polling.current = true;
    return api.qcStatus(jobId).then(status => { setQC(status); setError(""); return status; }).catch(e => {
      setError(friendlyError(e, "load quality check status"));
      return null;
    })
      .finally(() => { polling.current = false; setInitialLoading(false); });
  }, [jobId]);

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
  }, [poll, qc?.status]);

  const startQC = async () => {
    setLoading(true);
    setError("");
    try {
      await api.runQC(jobId);
      poll();
    } catch (e: any) {
      setError(friendlyError(e, "start the quality check"));
    }
    setLoading(false);
  };

  const applyFixes = async (indices?: number[]) => {
    setApplying(true);
    setError("");
    try {
      const result = await api.applyQCFixes(jobId, indices);
      if (onRerender && result.changes?.length > 0) {
        // Wait until the render endpoint has invalidated the previous QC state
        // before polling again. Otherwise this request can reload the old issues
        // in the small gap between applying the plan patch and queuing the render.
        await onRerender();
        setQC(null);
        setIgnored(new Set());
      }
      await poll();
    } catch (e: any) {
      setError(friendlyError(e, "apply quality fixes"));
    }
    setApplying(false);
  };

  const applyAll = () => {
    const activeIndices = qc!.issues
      .map((_, i) => i)
      .filter(i => !ignored.has(i));
    applyFixes(activeIndices);
  };

  const toggleIgnore = (idx: number) => {
    setIgnored(prev => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  };

  const isRunning = qc?.status === "running" || qc?.status === "sampling" ||
    qc?.status === "reviewing" || qc?.status === "patching";

  if (!renderDone) return null;

  const severityColor = (s: string) =>
    s === "error" ? "#ef4444" : s === "warning" ? "#f59e0b" : "#6b7280";

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="section-header">
        <h2>QC Check</h2>
        {qc?.status === "done" && (
          <span className="status-badge done" style={{ marginLeft: "auto" }}>
            {qc.total_issues === 0 ? "Passed" : `${qc.total_issues} issue(s)`}
          </span>
        )}
      </div>

      {initialLoading && <LoadingState label="Loading quality check…" rows={2} />}
      {!initialLoading && !isRunning && qc?.status !== "done" && (
        <button onClick={startQC} disabled={loading} title={loading ? "Starting quality check" : undefined}>
          {loading ? "Starting…" : "Run QC Check"}
        </button>
      )}

      {isRunning && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div className="generating-pulse" style={{
            width: 10, height: 10, borderRadius: "50%", background: "var(--accent)"
          }} />
          <span>{qc?.message || "Running QC…"}</span>
          {qc?.current_round ? <span className="muted">Round {qc.current_round}</span> : null}
        </div>
      )}

      {error && <p className="errors" role="alert" style={{ marginTop: 8 }}>{error} <button className="secondary" onClick={() => void poll()} disabled={polling.current} title={polling.current ? "Checking quality status" : undefined}>Retry</button></p>}

      {qc?.status === "done" && qc.issues.length > 0 && (
        <>
          <div style={{ marginTop: 12 }}>
            {qc.issues.map((issue, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "8px 12px", borderRadius: "var(--radius-sm)",
                background: ignored.has(i) ? "transparent" : "rgba(255,255,255,0.02)",
                opacity: ignored.has(i) ? 0.4 : 1,
                marginBottom: 4,
              }}>
                <span style={{
                  display: "inline-block", width: 8, height: 8, borderRadius: "50%",
                  background: severityColor(issue.severity), flexShrink: 0,
                }} />
                <span style={{ fontFamily: "SF Mono, monospace", fontSize: 12, color: "var(--text-tertiary)", minWidth: 45 }}>
                  {issue.timestamp?.toFixed(1)}s
                </span>
                <span style={{ flex: 1, fontSize: 13 }}>{issue.description}</span>
                <span style={{
                  fontSize: 11, padding: "2px 6px", borderRadius: 4,
                  background: severityColor(issue.severity) + "22",
                  color: severityColor(issue.severity),
                }}>
                  {issue.type}
                </span>
                <button
                  onClick={() => applyFixes([i])}
                  disabled={applying || ignored.has(i)}
                  title={applying ? "Applying quality fixes" : ignored.has(i) ? "Restore this issue before applying a fix" : undefined}
                  aria-label={`Apply fix for issue at ${issue.timestamp?.toFixed(1)} seconds`}
                  style={{ fontSize: 12, padding: "4px 10px" }}
                >
                  Apply fix
                </button>
                <button
                  onClick={() => toggleIgnore(i)}
                  disabled={applying}
                  title={applying ? "Applying quality fixes" : undefined}
                  aria-label={`${ignored.has(i) ? "Restore" : "Ignore"} issue at ${issue.timestamp?.toFixed(1)} seconds`}
                  style={{ fontSize: 12, padding: "4px 10px", background: "transparent", border: "1px solid var(--border)" }}
                >
                  {ignored.has(i) ? "Restore" : "Ignore"}
                </button>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button onClick={applyAll} disabled={applying || ignored.size === qc.issues.length} title={applying ? "Applying quality fixes" : ignored.size === qc.issues.length ? "Restore an issue to apply a fix" : undefined}>
              {applying ? "Applying…" : "Fix All & Re-render"}
            </button>
          </div>

          {qc.changes.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <h3 style={{ fontSize: 13, marginBottom: 6 }}>Applied Changes</h3>
              {qc.changes.map((c, i) => (
                <div key={i} style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 2 }}>
                  ✓ {c.description}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {qc?.status === "done" && qc.total_issues === 0 && (
        <p style={{ color: "var(--success, #22c55e)", marginTop: 8 }}>
          All checks passed — no issues found.
        </p>
      )}

      {qc?.status === "error" && (
        <p className="errors" role="alert" style={{ marginTop: 8 }}>{friendlyError(qc.message, "finish the quality check")}</p>
      )}
    </div>
  );
}
