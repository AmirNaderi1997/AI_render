import React, { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";
import { friendlyError } from "./ui";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await api.forgotPassword(email);
      setSent(true);
      if (res._dev_token) setDevToken(res._dev_token);
    } catch (err) {
      setError(friendlyError(err, "send your reset link"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-brand">
          <div className="nav-brand-icon">R</div>
          <span className="nav-brand-text">AI Render</span>
        </div>
        <h2>Reset your password</h2>
        {sent ? (
          <>
            <div className="ok">If this email is registered, you'll receive a reset link.</div>
            {devToken && (
              <div className="auth-dev-banner">
                DEV: Reset token: <code>{devToken}</code>
                <br />
                <Link to={`/reset-password?token=${devToken}`}>Use reset link</Link>
              </div>
            )}
          </>
        ) : (
          <form onSubmit={submit}>
            {error && <div className="auth-error" role="alert">{error}</div>}
            <label htmlFor="forgot-email">Email</label>
            <input id="forgot-email" type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required autoFocus />
            <button type="submit" disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>{loading ? "Sending..." : "Send reset link"}</button>
          </form>
        )}
        <div className="auth-links">
          <Link to="/login">Back to login</Link>
        </div>
      </div>
    </div>
  );
}
