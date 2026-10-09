import { api } from "./api";
import { notify } from "./ui";

const pendingDenoise = new Set<string>();
const checking = new Set<string>();

export function trackDenoise(id: string) { pendingDenoise.add(id); }

export function completeDenoise(id: string) {
  if (!pendingDenoise.delete(id)) return;
  notify("Audio cleanup is ready for review.");
}

export async function pollDenoiseNotifications() {
  await Promise.all([...pendingDenoise].filter(id => !checking.has(id)).map(async id => {
    checking.add(id);
    try {
      const result = await api.getDenoiseStatus(id);
      if (result.status === "ready") completeDenoise(id);
      if (["error", "failed", "skipped"].includes(result.status)) pendingDenoise.delete(id);
    } catch { /* The next poll will retry. */ }
    finally { checking.delete(id); }
  }));
}
