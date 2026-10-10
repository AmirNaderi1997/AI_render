import React, { useState } from "react";
import { Link, useSearchParams, useNavigate } from "react-router-dom";
import { api } from "./api";
import { friendlyError } from "./ui";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) { setError("Password must be at least 8 characters"); return; }
    if (password !== confirm) { setError("Passwords don't match"); return; }
    setLoading(true);
    try {
      await api.resetPassword(token, password);
      setSuccess(true);
      setTimeout(() => navigate("/login"), 2000);
    } catch (err: any) {
      setError(friendlyError(err, "reset your password"));
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return (
      <div className="auth-page">
        <div className="auth-card">
          <div className="auth-error">Invalid reset link — no token provided.</div>
          <div className="auth-links"><Link to="/forgot-password">Request a new reset link</Link></div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <div className="nav-brand-icon">R</div>
          <span className="nav-brand-text">AI Render</span>
        </div>
        <h2>Set a new password</h2>
        {success && <div className="ok">Password reset successfully! Redirecting to login...</div>}
        {error && <div className="auth-error" role="alert">{error}</div>}
        {!success && (
          <>
            <label htmlFor="reset-password">New password</label>
            <input id="reset-password" type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Min 8 characters" required autoFocus />
            <label htmlFor="reset-confirm">Confirm password</label>
            <input id="reset-confirm" type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Repeat password" required />
            <button type="submit" disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>{loading ? "Resetting..." : "Reset password"}</button>
          </>
        )}
        <div className="auth-links"><Link to="/login">Back to login</Link></div>
      </form>
    </div>
  );
}
