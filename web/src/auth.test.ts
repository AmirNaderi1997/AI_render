import { afterEach, describe, expect, it } from "vitest";
import { clearToken, getUser, isAuthenticated, setToken } from "./auth";

function makeToken(payload: object): string {
  return `h.${btoa(JSON.stringify(payload))}.s`;
}

afterEach(() => clearToken());

describe("auth", () => {
  it("is unauthenticated until a valid unexpired token is set, and again after clearToken", () => {
    expect(isAuthenticated()).toBe(false);
    setToken(makeToken({ exp: Date.now() / 1000 + 3600 }));
    expect(isAuthenticated()).toBe(true);
    clearToken();
    expect(isAuthenticated()).toBe(false);
  });

  it("rejects expired and malformed tokens", () => {
    setToken(makeToken({ exp: Date.now() / 1000 - 10 }));
    expect(isAuthenticated()).toBe(false);
    expect(getUser()).toBeNull();
    setToken("not-a-jwt");
    expect(isAuthenticated()).toBe(false);
    expect(getUser()).toBeNull();
  });

  it("getUser decodes id, email and name from the token", () => {
    setToken(makeToken({ sub: "u1", email: "a@b.co", name: "Ann", exp: Date.now() / 1000 + 3600 }));
    expect(getUser()).toEqual({ id: "u1", email: "a@b.co", name: "Ann" });
  });
});
