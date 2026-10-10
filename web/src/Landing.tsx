import React from "react";
import { Link } from "react-router-dom";

const features = [
  { icon: "↑", title: "Upload footage", desc: "Start with your own video and build an edit around it." },
  { icon: "✦", title: "AI edit plan", desc: "Turn footage and speech into a plan you can review and adjust." },
  { icon: "▣", title: "Storyboard", desc: "Plan scenes for reels, posts, and stories from a prompt." },
  { icon: "▶", title: "Render", desc: "Preview your edit, then render the finished video." },
  { icon: "✓", title: "Quality check", desc: "Review quality check results and apply suggested fixes." },
  { icon: "↗", title: "Premiere export", desc: "Download an editable Premiere import package with its media." },
  { icon: "◈", title: "Hermes publishing", desc: "Plan and publish Instagram content from Hermes Studio." },
];

export default function Landing() {
  return (
    <div className="landing">
      <div className="landing-hero">
        <div className="landing-badge">Rafiei AI Editor</div>
        <h1 className="landing-title">Create videos with AI</h1>
        <p className="landing-tagline">
          Upload footage or start with a prompt. Plan, edit, render, and review your content in one place.
        </p>
        <div className="landing-cta">
          <Link className="landing-btn-primary" to="/signup">Create your first reel</Link>
          <Link className="landing-btn-secondary" to="/login">Log in</Link>
        </div>
      </div>
      <section className="landing-features" aria-label="What you can do">
        {features.map((f, i) => (
          <div key={i} className="landing-feature-card">
            <div className="landing-feature-icon" aria-hidden="true">{f.icon}</div>
            <h3>{f.title}</h3>
            <p>{f.desc}</p>
          </div>
        ))}
      </section>
      <div className="landing-footer">
        Rafiei AI Editor
      </div>
    </div>
  );
}
