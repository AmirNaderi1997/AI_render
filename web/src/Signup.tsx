import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "./api";
import { friendlyError } from "./ui";

export default function Signup() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) { setError("Password must be at least 8 characters"); return; }
    if (password !== confirm) { setError("Passwords don't match"); return; }
    setLoading(true);
    try {
      await api.signup(email, name, password);
      navigate("/new");
    } catch (err: any) {
      setError(friendlyError(err, "create your account"));
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
        <h2>Create your account</h2>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <label htmlFor="signup-name">Name</label>
        <input id="signup-name" type="text" autoComplete="name" value={name} onChange={e => setName(e.target.value)} placeholder="Your name" required autoFocus />
        <label htmlFor="signup-email">Email</label>
        <input id="signup-email" type="email" autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required />
        <label htmlFor="signup-password">Password</label>
        <input id="signup-password" type="password" autoComplete="new-password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Min 8 characters" required />
        <label htmlFor="signup-confirm">Confirm password</label>
        <input id="signup-confirm" type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Repeat password" required />
        <button type="submit" disabled={loading} title={(loading) ? "Wait for loading to finish." : undefined}>{loading ? "Creating account..." : "Create account"}</button>
        <div className="auth-links">
          <span>Already have an account? <Link to="/login">Log in</Link></span>
        </div>
      </form>
    </div>
  );
}
