import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate, NavLink } from "react-router-dom";
import NewReel from "./NewReel";
import PlanReview from "./PlanReview";
import Render from "./Render";
import MyEffects from "./MyEffects";

function App() {
  return (
    <BrowserRouter>
      <nav>
        <strong>Rafiei AI Editor</strong>
        <NavLink to="/new">New Reel</NavLink>
        <NavLink to="/jobs">Jobs</NavLink>
        <NavLink to="/my-effects">My Effects</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/new" replace />} />
          <Route path="/new" element={<NewReel />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/jobs/:id" element={<PlanReview />} />
          <Route path="/jobs/:id/render" element={<Render />} />
          <Route path="/my-effects" element={<MyEffects />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

function Jobs() {
  const [jobs, setJobs] = React.useState<any[]>([]);
  React.useEffect(() => {
    fetch("/api/jobs").then(r => r.json()).then(setJobs);
  }, []);
  return (
    <div>
      <h1>Jobs</h1>
      {jobs.length === 0 && <p className="muted">No jobs yet. <a href="/new">Create one.</a></p>}
      <ul>
        {jobs.map(j => (
          <li key={j.id}>
            <a href={`/jobs/${j.id}`}>{j.id}</a> — raw: {j.raw_name || "—"}, render: {j.render.status}
          </li>
        ))}
      </ul>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
