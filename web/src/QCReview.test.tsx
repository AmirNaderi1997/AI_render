import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import QCReview from "./QCReview";
import { api } from "./api";

const qc = (status: string) => ({
  status, message: status, current_round: 0, total_issues: 0,
  fixed_issues: 0, issues: [], changes: [],
});
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });

describe("QCReview polling", () => {
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  it.each(["completed", "failed", "error", "cancelled", "done"])(
    "stops polling after terminal status %s", async terminal => {
      vi.useFakeTimers();
      const status = vi.spyOn(api, "qcStatus").mockResolvedValue(qc(terminal));
      render(<QCReview jobId="j1" renderDone />);
      await flush();
      const settledCalls = status.mock.calls.length;
      expect(settledCalls).toBeGreaterThan(0);

      await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
      expect(status).toHaveBeenCalledTimes(settledCalls);
    },
  );

  it("starts polling again after a QC rerun is triggered", async () => {
    vi.useFakeTimers();
    const statuses = [qc("failed"), qc("failed"), qc("running"), qc("running"), qc("done")];
    const status = vi.spyOn(api, "qcStatus").mockImplementation(async () => statuses.shift() ?? qc("done"));
    const run = vi.spyOn(api, "runQC").mockResolvedValue({ status: "running" });
    render(<QCReview jobId="j1" renderDone />);
    await flush();
    expect(screen.getByRole("button", { name: "Run QC Check" })).toBeInTheDocument();
    const settledCalls = status.mock.calls.length;

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Run QC Check" })); await Promise.resolve(); });
    await flush();
    expect(run).toHaveBeenCalledOnce();
    const afterRerunCalls = status.mock.calls.length;
    expect(afterRerunCalls).toBeGreaterThan(settledCalls);
    await act(async () => { await vi.advanceTimersByTimeAsync(2_100); });
    expect(status.mock.calls.length).toBeGreaterThan(afterRerunCalls);
  });

  it("waits for re-render invalidation before loading QC status again", async () => {
    const oldResult = {
      ...qc("done"), total_issues: 1,
      issues: [{ timestamp: 1, severity: "warning", type: "caption", description: "Old problem" }],
    };
    let renderQueued = false;
    const status = vi.spyOn(api, "qcStatus").mockImplementation(async () => renderQueued ? qc("idle") : oldResult);
    vi.spyOn(api, "applyQCFixes").mockResolvedValue({ ok: true, changes: [{ field: "captions" }], plan: {} });
    const onRerender = vi.fn(async () => { renderQueued = true; });

    render(<QCReview jobId="j1" renderDone latestOutput="v1_preview.mp4" onRerender={onRerender} />);
    expect(await screen.findByText("Old problem")).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Apply fix for issue/ })); });

    expect(onRerender).toHaveBeenCalledOnce();
    expect(status.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("Old problem")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run QC Check" })).toBeInTheDocument();
  });
});
