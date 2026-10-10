import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type Job } from "./api";
import { JobCacheProvider, useJobCache } from "./JobCache";
import { setToken, clearToken } from "./auth";

function makeJob(id: string, name: string): Job {
  return {
    id, raw_name: name, status: "ready", created_at: "2026-01-01T00:00:00Z",
    render: { status: "idle", progress: 0, message: "", output: null, preview: false, versions: [] },
    versions: [],
  } as unknown as Job;
}

function Probe() {
  const cache = useJobCache();
  return <>
    <div data-testid="job-names">{cache.jobs.map(job => job.raw_name).join(",")}</div>
    <div data-testid="loading">{String(cache.loading)}</div>
    <button onClick={() => void cache.refetch()}>Refresh cache</button>
    <button onClick={() => void api.putPlan("j1", { segments: [] })}>Save plan</button>
  </>;
}

describe("JobCacheProvider", () => {
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); clearToken(); });

  it("loads jobs and refetches after a successful job mutation invalidates the cache", async () => {
    setToken(`h.${btoa(JSON.stringify({ exp: Date.now() / 1000 + 3600 }))}.s`);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/jobs" && !init?.method) return new Response(JSON.stringify([makeJob("j1", "First")]), { status: 200 });
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<JobCacheProvider><Probe /></JobCacheProvider>);

    expect(await screen.findByText("First")).toBeInTheDocument();
    const listCalls = () => fetchMock.mock.calls.filter(([url, init]) => String(url) === "/api/jobs" && !init?.method).length;
    expect(listCalls()).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Save plan" }));
    await waitFor(() => expect(listCalls()).toBe(2));
    expect(screen.getByTestId("job-names")).toHaveTextContent("First");
  });

  it("keeps the cached jobs visible while a background refresh is pending", async () => {
    setToken(`h.${btoa(JSON.stringify({ exp: Date.now() / 1000 + 3600 }))}.s`);
    let finishRefresh!: (jobs: Job[]) => void;
    const listJobs = vi.spyOn(api, "listJobs")
      .mockResolvedValueOnce([makeJob("j1", "Cached job")])
      .mockImplementationOnce(() => new Promise(resolve => { finishRefresh = resolve; }));
    render(<JobCacheProvider><Probe /></JobCacheProvider>);
    expect(await screen.findByText("Cached job")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refresh cache" }));
    await waitFor(() => expect(listJobs).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("job-names")).toHaveTextContent("Cached job");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");

    await act(async () => finishRefresh([makeJob("j2", "Fresh job")]));
    expect(screen.getByTestId("job-names")).toHaveTextContent("Fresh job");
  });
});
