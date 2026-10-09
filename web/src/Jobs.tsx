import React from "react";
import { NavLink } from "react-router-dom";
import { useJobCache } from "./JobCache";
import { EmptyState, LoadingState, friendlyError } from "./ui";

export default function Jobs() {
  const { jobs, loading, error, refetch } = useJobCache();

  React.useEffect(() => {
    void refetch();
    const handleFocus = () => void refetch();
    window.addEventListener("focus", handleFocus);
    return () => window.removeEventListener("focus", handleFocus);
  }, [refetch]);

  const statusColor = (status: string) =>
    status === "done" ? "done" : status === "running" ? "running" : status === "error" ? "error" : "";

  return (
    <div>
      <h1>Jobs</h1>
      {loading && jobs.length === 0 ? <LoadingState label="Loading your jobs…" /> : error && jobs.length === 0 ? (
        <div className="errors" role="alert">{friendlyError(error, "load your jobs")} <button className="secondary" onClick={() => void refetch()}>Try again</button></div>
      ) : jobs.length === 0 ? (
        <EmptyState icon="🎬" title="No jobs yet" description="Start with a video or create content from a prompt."
          action={<NavLink className="button-link" to="/new">Create your first reel</NavLink>} />
      ) : (
        <>
          {error && <div className="errors" role="alert">{friendlyError(error, "refresh your jobs")} <button className="secondary" onClick={() => void refetch()}>Try again</button></div>}
          <div className="jobs-list">
            {jobs.map(job => (
              <NavLink key={job.id} to={`/jobs/${job.id}`} className="job-item">
                <span className="job-id">{job.id}</span>
                <span className="job-meta"><span>{job.raw_name || "Untitled"}</span></span>
                <span className={`status-badge ${statusColor(job.render.status)}`}>{job.render.status}</span>
              </NavLink>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
