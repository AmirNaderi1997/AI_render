import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Library from "./Library";
import { api, type LibraryAsset, type LibraryData } from "./api";

vi.mock("./AuthenticatedMedia", () => ({
  AuthenticatedMedia: ({ as: Tag = "div", ...props }: any) => React.createElement(Tag, props),
}));

const asset: LibraryAsset = {
  filename: "sunrise.mp4", category: "broll", path: "/media/sunrise.mp4",
  tags: ["morning"], mood: "calm", energy: 3,
};
const library: LibraryData = {
  counts: { broll: 1, music: 0, sfx: 0 }, assets: [asset],
};

describe("Library", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders assets returned by the library API", async () => {
    vi.spyOn(api, "getLibrary").mockResolvedValue(library);
    render(<Library />);

    expect(await screen.findByText("sunrise.mp4")).toBeInTheDocument();
    expect(screen.getByText("morning")).toBeInTheDocument();
    expect(screen.getByText("E3")).toBeInTheDocument();
  });

  it("clamps edited energy to 1–5 and never sends an out-of-range value", async () => {
    vi.spyOn(api, "getLibrary").mockResolvedValue(library);
    const update = vi.spyOn(api, "updateLibraryAsset").mockResolvedValue(asset);
    render(<Library />);
    await screen.findByText("sunrise.mp4");
    fireEvent.click(screen.getByRole("button", { name: "Edit tags" }));

    const energy = screen.getByLabelText("Energy (1-5)") as HTMLInputElement;
    fireEvent.change(energy, { target: { value: "9" } });
    expect(energy).toHaveValue(5);
    fireEvent.change(energy, { target: { value: "0" } });
    expect(energy).toHaveValue(1);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(update).toHaveBeenCalledOnce());
    const sentEnergy = update.mock.calls[0][2].energy;
    expect(sentEnergy).toBe(1);
    expect(sentEnergy).not.toBe(0);
    expect(sentEnergy).not.toBe(9);
  });
});
