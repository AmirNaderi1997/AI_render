import React from "react";
import { Link } from "react-router-dom";

const features = [
  { icon: "✦", title: "AI-Powered Editing", desc: "Auto-generates edit plans from your raw footage using vision AI and speech analysis." },
  { icon: "▣", title: "Content Creator", desc: "Generate Reels, Posts & Stories from a simple text prompt — no footage needed." },
  { icon: "◈", title: "Smart Style Learning", desc: "AI learns YOUR editing style from reference reels and applies it automatically." },
  { icon: "↗", title: "Premiere Pro Integration", desc: "Export directly to Adobe Premiere Pro with captions, effects, and timelines." },
];

export default function Landing() {
  return (
    <div className="landing">
      <div className="landing-hero">
        <div className="landing-badge">AI-Powered Video Editor</div>
        <h1 className="landing-title">AI Render</h1>
        <p className="landing-tagline">
          Transform raw footage into polished Instagram content with AI
        </p>
        <div className="landing-cta">
          <Link className="landing-btn-primary" to="/signup">Get Started</Link>
          <Link className="landing-btn-secondary" to="/login">Log In</Link>
        </div>
      </div>
      <div className="landing-features">
        {features.map((f, i) => (
          <div key={i} className="landing-feature-card">
            <div className="landing-feature-icon">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.desc}</p>
          </div>
        ))}
      </div>
      <div className="landing-footer">
        AI Render
      </div>
    </div>
  );
}
