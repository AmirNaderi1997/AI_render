import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, subscribeJobCacheInvalidation } from "./api";
import { clearToken, getToken, setToken } from "./auth";

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

describe("authenticated API helpers", () => {
  it("sends the in-memory token as a Bearer Authorization header", async () => {
    const fetchMock = vi.fn(async () => okJson([]));
    vi.stubGlobal("fetch", fetchMock);

    await api.listJobs();

    expect(fetchMock).toHaveBeenCalledOnce();
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(`Bearer ${getToken()}`);
  });

  it("clears the token and navigates to login after a 401", async () => {
    const fetchMock = vi.fn(async () => new Response("expired", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const assign = vi.fn();
    vi.stubGlobal("window", { ...window, location: { pathname: "/jobs", assign } });

    await expect(api.listJobs()).rejects.toThrow("Session expired");
    expect(getToken()).toBeNull();
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("propagates JSON API error details", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "job is locked" }),
      { status: 409, headers: { "content-type": "application/json" } },
    )));

    await expect(api.listJobs()).rejects.toThrow("409 job is locked");
  });
});
