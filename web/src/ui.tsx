import React from "react";

/** Keep operational details in logs while giving people a useful next step. */
export function friendlyError(error: unknown, action = "complete this action"): string {
  const message = error instanceof Error ? error.message : String(error ?? "");
  if (/401|unauthori[sz]ed|session expired/i.test(message)) return "Your session has expired. Sign in again and retry.";
  if (/403|forbidden/i.test(message)) return "You do not have access to this item. Check your account and try again.";
  if (/413|too large|file size/i.test(message)) return "This file is too large. Choose a smaller file and try again.";
  if (/network|failed to fetch|timeout|timed out|502|503|504/i.test(message)) return "We could not reach the server. Check your connection and try again.";
  if (/invalid credentials|incorrect password/i.test(message)) return "The email or password is incorrect. Check both and try again.";
  if (/already exists|already registered/i.test(message)) return "This account already exists. Sign in or use another email.";
  if (/^invalid json$/i.test(message)) return "The edit plan is not valid JSON. Check its formatting and try again.";
  return `We could not ${action}. Please try again. If it keeps happening, contact support.`;
}

export function LoadingState({ label, rows = 3 }: { label: string; rows?: number }) {
  return <div className="ui-state ui-loading" role="status" aria-live="polite" aria-label={label}>
    <span className="ui-spinner" aria-hidden="true" />
    <span>{label}</span>
    <div className="ui-skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => <span key={i} />)}
    </div>
  </div>;
}

export function EmptyState({ icon = "✦", title, description, action }: {
  icon?: string; title: string; description: string; action?: React.ReactNode;
}) {
  return <div className="empty-state ui-empty">
    <div className="empty-state-icon" aria-hidden="true">{icon}</div>
    <strong>{title}</strong><p>{description}</p>{action}
  </div>;
}
