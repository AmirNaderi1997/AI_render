let accessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;

export function getToken(): string | null {
  return accessToken;
}

export function setToken(token: string | null): void {
  accessToken = token;
}

export function clearToken(): void {
  accessToken = null;
}

export function handleUnauthorized(): never {
  clearToken();
  if (window.location.pathname !== "/login") window.location.assign("/login");
  throw new Error("Session expired");
}

export function isAuthenticated(): boolean {
  const token = getToken();
  if (!token) return false;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.exp * 1000 > Date.now();
  } catch {
    return false;
  }
}

export function getUser(): { id: string; email: string; name: string } | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    if (payload.exp * 1000 < Date.now()) return null;
    return { id: payload.sub, email: payload.email, name: payload.name };
  } catch {
    return null;
  }
}

function tokenExpiresWithin(seconds: number): boolean {
  const token = getToken();
  if (!token) return true;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.exp * 1000 - Date.now() < seconds * 1000;
  } catch {
    return true;
  }
}

export async function ensureFreshToken(): Promise<string | null> {
  if (!tokenExpiresWithin(300)) return getToken();
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    try {
      const r = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: "{}",
        signal: AbortSignal.timeout(5000),
      });
      if (!r.ok) {
        clearToken();
        return null;
      }
      const data = await r.json();
      setToken(data.access_token);
      return data.access_token as string;
    } catch {
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/** Restore the in-memory access token from the HttpOnly refresh cookie. */
export function restoreSession(): Promise<string | null> {
  return ensureFreshToken();
}
