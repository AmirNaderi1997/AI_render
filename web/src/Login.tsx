import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "./api";
import { friendlyError } from "./ui";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.login(email, password);
      navigate("/new");
    } catch (err: any) {
      setError(friendlyError(err, "sign you in"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <div className="nav-brand-icon">R</div>
          <span className="nav-brand-text">AI Render</span>
        </div>
        <h2>Welcome back</h2>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <label htmlFor="login-email">Email</label>
        <input id="login-email" type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required autoFocus />
        <label htmlFor="login-password">Password</label>
        <input id="login-password" type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required />
        <button type="submit" disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>{loading ? "Logging in..." : "Log in"}</button>
        <div className="auth-links">
          <Link to="/forgot-password">Forgot password?</Link>
          <span>Don't have an account? <Link to="/signup">Sign up</Link></span>
        </div>
      </form>
    </div>
  );
}
