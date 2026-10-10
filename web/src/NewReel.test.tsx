import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const createJob = vi.fn();
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    api: {
      ...actual.api,
      listFonts: vi.fn(async () => []),
      getLibrary: vi.fn(async () => ({ assets: [] })),
      getStyleLibrary: vi.fn(async () => ({})),
      createJob: (...args: unknown[]) => createJob(...args),
    },
  };
});

import NewReel from "./NewReel";

describe("NewReel upload cancel", () => {
  it("aborts the in-flight upload signal and shows the retry state", async () => {
    let signal: AbortSignal | undefined;
    createJob.mockImplementation((_v, _p, onProgress: (n: number) => void, s: AbortSignal) => {
      signal = s;
      onProgress(40);
      return new Promise((_, reject) => s.addEventListener("abort", () => reject(new Error("Upload cancelled"))));
    });

    const { container } = render(<MemoryRouter><NewReel /></MemoryRouter>);
    const input = container.querySelector<HTMLInputElement>("#vid")!;
    fireEvent.change(input, { target: { files: [new File(["x"], "clip.mp4", { type: "video/mp4" })] } });
    fireEvent.click(await screen.findByRole("button", { name: /create \(with manual plan\)/i }));

    const cancel = await screen.findByRole("button", { name: /cancel upload/i });
    expect(signal?.aborted).toBe(false);
    fireEvent.click(cancel);

    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(screen.queryByRole("button", { name: /cancel upload/i })).toBeNull());
    expect((await screen.findAllByRole("button", { name: /retry upload/i })).length).toBeGreaterThan(0);
  });
});
