import React from "react";
import { NavLink } from "react-router-dom";
import { useJobCache } from "./JobCache";
import { EmptyState, LoadingState, friendlyError } from "./ui";
import { AuthenticatedMedia } from "./AuthenticatedMedia";
import { api } from "./api";

export default function Jobs() {
  const { jobs, loading, error, refetch } = useJobCache();
  const [query, setQuery] = React.useState("");
  const [search, setSearch] = React.useState("");
  React.useEffect(() => { const timer = window.setTimeout(() => setSearch(query.trim().toLocaleLowerCase()), 250); return () => window.clearTimeout(timer); }, [query]);
  const visible = React.useMemo(() => jobs.filter(job => `${job.raw_name || ""} ${job.id}`.toLocaleLowerCase().includes(search)), [jobs, search]);

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
      {jobs.length > 0 && <label className="jobs-search">Search jobs<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search by name or ID" /></label>}
      {loading && jobs.length > 0 && <LoadingState label="Refreshing your jobs…" rows={1} />}
      {loading && jobs.length === 0 ? <LoadingState label="Loading your jobs…" /> : error && jobs.length === 0 ? (
        <div className="errors" role="alert">{friendlyError(error, "load your jobs")} <button className="secondary" onClick={() => void refetch()}>Try again</button></div>
      ) : jobs.length === 0 ? (
        <EmptyState icon="🎬" title="No jobs yet" description="Start with a video or create content from a prompt."
          action={<NavLink className="button-link" to="/new">Create your first reel</NavLink>} />
      ) : (
        <>
          {error && <div className="errors" role="alert">{friendlyError(error, "refresh your jobs")} <button className="secondary" onClick={() => void refetch()}>Try again</button></div>}
          {visible.length === 0 ? <EmptyState icon="⌕" title="No matching jobs" description="Try a different name or job ID." action={<button className="secondary" onClick={() => setQuery("")}>Clear search</button>} /> : <div className="jobs-list">
            {visible.map(job => (
              <NavLink key={job.id} to={`/jobs/${job.id}`} className="job-item">
                {job.render.status === "done" && job.render.output ? <AuthenticatedMedia as="img" className="job-thumb" loading="lazy" decoding="async" alt={`Poster for ${job.raw_name || job.id}`} src={api.exportUrl(job.id, job.render.output.replace(/\.mp4$/, "_poster.jpg"))} /> : <span className="job-thumb job-thumb-placeholder" aria-hidden="true">▶</span>}
                <span className="job-id" dir="ltr">{job.id}</span>
                <span className="job-meta"><span dir="auto">{job.raw_name || "Untitled"}</span></span>
                <span className={`status-badge ${statusColor(job.render.status)}`}>{job.render.status}</span>
              </NavLink>
            ))}
          </div>}
        </>
      )}
    </div>
  );
}
