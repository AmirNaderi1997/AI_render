import React from "react";
import { api, type Job, subscribeJobCacheInvalidation } from "./api";
import { notify } from "./ui";
import { isAuthenticated } from "./auth";
import { pollDenoiseNotifications } from "./taskNotifications";

type JobCacheValue = {
  jobs: Job[];
  loading: boolean;
  error: unknown;
  refetch: () => Promise<void>;
  invalidate: () => void;
};

const JobCacheContext = React.createContext<JobCacheValue | null>(null);

export function JobCacheProvider({ children }: { children: React.ReactNode }) {
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [version, setVersion] = React.useState(0);
  const hasLoaded = React.useRef(false);
  const previous = React.useRef<Job[]>([]);
  const fetching = React.useRef(false);

  const invalidate = React.useCallback(() => setVersion(value => value + 1), []);
  const refetch = React.useCallback(async () => {
    if (fetching.current) return;
    fetching.current = true;
    setLoading(true);
    setError(null);
    try {
      const next = await api.listJobs();
      if (hasLoaded.current) for (const job of next) {
        const before = previous.current.find(item => item.id === job.id);
        if (before && before.render.status !== "done" && job.render.status === "done") notify(`Render complete: ${job.raw_name || job.id}`);
      }
      previous.current = next;
      setJobs(next);
      hasLoaded.current = true;
    } catch (nextError) {
      setError(nextError);
    } finally {
      setLoading(false);
      fetching.current = false;
    }
  }, []);

  React.useEffect(() => subscribeJobCacheInvalidation(invalidate), [invalidate]);
  React.useEffect(() => { if (isAuthenticated()) void refetch(); }, [refetch]);
  React.useEffect(() => {
    if (hasLoaded.current) void refetch();
  }, [refetch, version]);
  React.useEffect(() => {
    const timer = window.setInterval(() => { if (isAuthenticated() && document.visibilityState === "visible") { void refetch(); void pollDenoiseNotifications(); } }, 15000);
    return () => window.clearInterval(timer);
  }, [refetch]);

  const value = React.useMemo(
    () => ({ jobs, loading, error, refetch, invalidate }),
    [jobs, loading, error, refetch, invalidate],
  );
  return <JobCacheContext.Provider value={value}>{children}</JobCacheContext.Provider>;
}

export function useJobCache(): JobCacheValue {
  const value = React.useContext(JobCacheContext);
  if (!value) throw new Error("useJobCache must be used inside JobCacheProvider");
  return value;
}
