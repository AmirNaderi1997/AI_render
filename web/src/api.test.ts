import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, subscribeJobCacheInvalidation } from "./api";
import { clearToken, setToken } from "./auth";

const okJson = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

beforeEach(() => {
  setToken(`h.${btoa(JSON.stringify({ exp: Date.now() / 1000 + 3600 }))}.s`);
});
afterEach(() => {
  clearToken();
  vi.unstubAllGlobals();
});

describe("job cache invalidation", () => {
  it("a successful job mutation notifies cache subscribers; reads and validate do not", async () => {
    const fetchMock = vi.fn(async () => okJson({ ok: true, errors: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const listener = vi.fn();
    const unsubscribe = subscribeJobCacheInvalidation(listener);

    await api.listJobs();
    await api.validate("j1", {});
    expect(listener).not.toHaveBeenCalled();

    await api.putPlan("j1", { segments: [] });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    unsubscribe();
    await api.putPlan("j1", { segments: [] });
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
