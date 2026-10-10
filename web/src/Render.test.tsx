import React from "react";
import { act, render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import Render from "./Render";
import { api } from "./api";

vi.mock("./PremiereCard", () => ({ PremiereCard: () => null }));
vi.mock("./AuthenticatedMedia", () => ({ AuthenticatedMedia: () => null }));
vi.mock("./QCReview", () => ({ default: () => null }));
vi.mock("./ui", () => ({
  Breadcrumbs: () => null, JobWorkflow: () => null, LoadingState: () => <div>Loading</div>,
  NextStep: ({ children }: any) => <div>{children}</div>, friendlyError: (e: any) => String(e),
}));
vi.mock("./taskNotifications", () => ({ completeDenoise: vi.fn(), trackDenoise: vi.fn() }));

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
const terminal = ["completed", "failed", "error", "cancelled", "done", "ready", "skipped"];
const renderResponse = (status: string) => ({ status, progress: 100, message: status, output: undefined, preview: false, versions: [] });
const denoiseResponse = (status: string) => ({ status, message: status, level: "medium", preserve_voice: true, approved: false, bypass: false });
const musicResponse = {
  attached: false, file: null, name: null, duration_s: 0, volume_level: 0.3,
  fade_in_seconds: 2, fade_out_seconds: 3, status: "idle" as const,
  progress: 0, message: "", output: null, mixed_from: null,
};

function mountRender() {
  return render(<MemoryRouter initialEntries={["/jobs/j1/render"]}>
    <Routes><Route path="/jobs/:id/render" element={<Render />} /></Routes>
  </MemoryRouter>);
}

describe("Render polling", () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it.each(terminal)("stops render-status polling at %s", async status => {
    vi.useFakeTimers();
    const renderStatus = vi.spyOn(api, "renderStatus").mockResolvedValue(renderResponse(status));
    vi.spyOn(api, "getJob").mockResolvedValue({ id: "j1", raw_name: "Job", plan: null } as any);
    vi.spyOn(api, "getDenoiseStatus").mockResolvedValue(denoiseResponse("idle"));
    vi.spyOn(api, "getMusicStatus").mockResolvedValue(musicResponse);
    mountRender();
    await flush();
    const settledCalls = renderStatus.mock.calls.length;
    expect(settledCalls).toBeGreaterThan(0);

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(renderStatus).toHaveBeenCalledTimes(settledCalls);
  });

  it.each(terminal)("stops denoise-status polling at %s", async status => {
    vi.useFakeTimers();
    const denoiseStatus = vi.spyOn(api, "getDenoiseStatus").mockResolvedValue(denoiseResponse(status));
    vi.spyOn(api, "renderStatus").mockResolvedValue(renderResponse("done"));
    vi.spyOn(api, "getJob").mockResolvedValue({ id: "j1", raw_name: "Job", plan: null } as any);
    vi.spyOn(api, "getMusicStatus").mockResolvedValue(musicResponse);
    vi.spyOn(api, "getDenoiseCompare").mockResolvedValue({ original_url: "o", denoised_url: "d" });
    mountRender();
    await flush();
    const settledCalls = denoiseStatus.mock.calls.length;
    expect(settledCalls).toBeGreaterThan(0);

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(denoiseStatus).toHaveBeenCalledTimes(settledCalls);
  });
});
