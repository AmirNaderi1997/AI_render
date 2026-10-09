import React from "react";
import { api, type Job, subscribeJobCacheInvalidation } from "./api";

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

  const invalidate = React.useCallback(() => setVersion(value => value + 1), []);
  const refetch = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setJobs(await api.listJobs());
      hasLoaded.current = true;
    } catch (nextError) {
      setError(nextError);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => subscribeJobCacheInvalidation(invalidate), [invalidate]);
  React.useEffect(() => {
    if (hasLoaded.current) void refetch();
  }, [refetch, version]);

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
