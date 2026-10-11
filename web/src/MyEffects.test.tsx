import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MyEffects from "./MyEffects";
import { api } from "./api";

vi.mock("./ui", () => ({
  LoadingState: () => <div>Loading</div>,
  friendlyError: (error: unknown) => String(error),
}));

const activeLearned = {
  active: true, enabled: true, sample_count: 3,
  metrics: { cut_length_avg: 2.5 }, confidence: {}, preset_overrides: {},
};

describe("My Effects plan styles", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "listEffects").mockResolvedValue([]);
    vi.spyOn(api, "getMyEffects").mockResolvedValue({ favorites: {}, rules: [], dislikes: [], selected_rafiei_style: null } as any);
    vi.spyOn(api, "getRafieiStyles").mockResolvedValue({ preferred_effects: [] } as any);
    vi.spyOn(api, "getStyleLibrary").mockResolvedValue({ drafts: [], profiles: [] });
    vi.spyOn(api, "getPlanStyleSelection").mockResolvedValue({ style_id: null, version: null, name: null });
    vi.spyOn(api, "getLearnedProfile").mockResolvedValue(activeLearned);
    vi.spyOn(api, "updateLearnedProfile").mockResolvedValue({ ok: true });
    vi.spyOn(api, "setPlanStyleSelection").mockResolvedValue({ ok: true, style_id: null, version: null, name: null });
    vi.spyOn(api, "resetLearnedProfile").mockResolvedValue({ ok: true });
  });

  it("lets the selected learned profile be deselected back to defaults", async () => {
    render(<MyEffects />);
    const learned = await screen.findByRole("button", { name: /Learned profile/ });
    expect(learned).toHaveAttribute("aria-pressed", "true");

    vi.mocked(api.getLearnedProfile).mockResolvedValue({ ...activeLearned, enabled: false });
    fireEvent.click(learned);

    await waitFor(() => expect(api.updateLearnedProfile).toHaveBeenCalledWith({ enabled: false }));
    expect(await screen.findByRole("button", { name: /Rafiei Reel defaults/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("deletes the learned profile while retaining the explicit default choice", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<MyEffects />);
    await screen.findByRole("button", { name: /Learned profile/ });
    vi.mocked(api.getLearnedProfile).mockResolvedValue({
      active: false, enabled: false, sample_count: 3, metrics: {}, confidence: {}, preset_overrides: {},
    });

    fireEvent.click(screen.getByRole("button", { name: "Delete learned profile" }));

    await waitFor(() => expect(api.resetLearnedProfile).toHaveBeenCalledTimes(1));
    expect(api.setPlanStyleSelection).toHaveBeenCalledWith(null, null);
    await waitFor(() => expect(screen.queryByRole("button", { name: /Learned profile/ })).not.toBeInTheDocument());
  });
});
