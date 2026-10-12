import { getToken, ensureFreshToken, handleUnauthorized, setToken } from "./auth";

const BASE = "/api";

type JobCacheListener = () => void;
const jobCacheListeners = new Set<JobCacheListener>();

export function subscribeJobCacheInvalidation(listener: JobCacheListener): () => void {
  jobCacheListeners.add(listener);
  return () => jobCacheListeners.delete(listener);
}

export function invalidateJobCache(): void {
  jobCacheListeners.forEach(listener => listener());
}

function isJobMutation(url: string, init?: RequestInit): boolean {
  const method = (init?.method || "GET").toUpperCase();
  if (["GET", "HEAD", "OPTIONS"].includes(method)) return false;
  const pathname = new URL(url, window.location.origin).pathname;
  if (!pathname.startsWith(`${BASE}/jobs`)) return false;
  // Validation is read-only despite using POST, so it must not churn the list cache.
  return !pathname.endsWith("/validate");
}

export interface Job {
  id: string;
  dir: string;
  raw_name?: string;
  plan_name: string;
  render: {
    status: string; progress: number; message: string;
    output?: string; preview: boolean;
  };
  generate: {
    status: string; stage: string; message: string;
    cost_usd: number; input_tokens: number; output_tokens: number; model: string;
  };
  versions: string[];
  plan?: any;
  has_transcript?: boolean;
}

export type PremiereMode = "editable_plan" | "rendered_video" | "plan_and_render" | "saved_project" | "reveal";
export interface PremiereStatus {
  available?: boolean;
  message?: string | null;
  capability: { available: boolean; local_launch_supported: boolean; version: string | null; bundle_id: string | null; app_path: string | null };
  editable_plan: "ready" | "stale" | "missing";
  final_render: "final" | "preview_only" | "missing" | "outdated";
  saved_project: "linked" | "outdated" | "not_linked";
  project_state: "not_linked" | "linked_current" | "linked_outdated" | "missing";
  render_name: string | null;
  xml_name: string;
  srt_name: string;
  project_name?: string;
  artifact_hashes?: { plan?: string; xml?: string; srt?: string; render?: string | null };
  changed_hashes?: Record<string, { linked: string | null; current: string | null }>;
  warnings: string[];
  bridge?: {
    available: boolean; protocol_version: number;
    state: "not_connected" | "waiting_for_premiere" | "paired" | "completed" | "partial" | "failed" | "stale";
    operation_id?: string; expires_at_unix?: number;
    bridge?: { kind?: string; version?: string; premiere_version?: string | null };
    receipt?: any;
  };
}

export interface Transcript {
  file_hash: string;
  cache_key?: string;
  model_size?: string;
  requested_language?: string;
  correction_count?: number;
  language: string;
  duration: number;
  words: { w: string; start: number; end: number; prob: number; reviewed?: boolean; original_w?: string }[];
  sentences: { text: string; start: number; end: number }[];
}

export interface EffectPreset {
  id: string; motion: string; light: string; label: string;
  description: string; needs_framing_review: boolean; strong_accent: boolean;
  energy?: number; mood?: string; best_roles?: string[]; category?: string; hint_color?: string;
}

export interface RafieiStyle {
  preferred_effects: string[]; avoid_effects: string[];
  caption_emphasis_color: string; caption_emphasis_alt_color: string;
  opening_title: boolean;
  watermark: { text: string; font: string; position: string; opacity: number; size: number };
  credit_lower_third: { text: string; font: string; show_on_intro: boolean };
}

export interface Correction {
  index: number;
  old: string;
  new: string;
  confidence: number;
  reason: string;
  type?: string;
}

export interface Corrections {
  auto_applied: Correction[];
  suggestions: Correction[];
}

export interface GenerateStatus {
  status: string; stage: string; message: string;
  cost_usd: number; input_tokens: number; output_tokens: number; model: string;
  asr_engine: string; asr_fallback_reason: string; asr_audio_seconds: number; asr_cost_usd: number;
  correction_model: string;
}

export interface FontEntry {
  id: string; kind: string; name?: string; family?: string; style?: string;
  filename?: string; sha256?: string; review_state: string;
  metadata?: { family: string; style: string; weight: number; license?: string;
    license_url?: string; glyph_count: number;
    persian_coverage: { supported: boolean; missing: string[] };
    latin_coverage: { supported: boolean; missing: string[] } };
  extracted_text?: string; ocr_note?: string;
  font_candidates?: { family: string; confidence: string; basis: string }[];
  copied_text?: string; font_name?: string; source?: any;
}
export interface FontLibrary { version: number; candidates: FontEntry[]; approved: FontEntry[] }
export interface StyleDraft { id: string; name: string; state: string; source: any; evidence: any[]; profile: any }
export interface StyleProfile { style_id: string; version: number; name: string; state: string; source: any; profile: any; evidence: any[] }
export interface StyleLibraryData { drafts: StyleDraft[]; profiles: StyleProfile[] }
export interface PlanStyleSelection { style_id: string | null; version: number | null; name: string | null; selected: boolean; default_hidden: boolean }
export interface LearnedStyleProfile {
  exists: boolean; active: boolean; enabled: boolean; sample_count: number;
  metrics: Record<string, unknown>; confidence: Record<string, unknown>;
  preset_overrides: Record<string, unknown>;
}

export interface LibraryAsset {
  filename: string; category: "broll" | "music" | "sfx"; path: string;
  tags: string[]; mood?: string; energy?: number;
  duration_sec?: number; description?: string;
}
export interface LibraryData {
  counts: { broll: number; music: number; sfx: number };
  assets: LibraryAsset[];
}

export interface MusicStatus {
  attached: boolean;
  file: string | null;
  name: string | null;
  duration_s: number;
  volume_level: number;
  fade_in_seconds: number;
  fade_out_seconds: number;
  status: "idle" | "queued" | "running" | "done" | "error";
  progress: number;
  message: string;
  output: string | null;
  mixed_from: string | null;
  technical_qc?: { loudness_lufs: number | null; true_peak_dbfs: number | null; warnings: string[] } | null;
}

async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  await ensureFreshToken();
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const r = await fetch(url, { ...init, headers });
  if (r.status === 401) handleUnauthorized();
  if (r.ok && isJobMutation(url, init)) invalidateJobCache();
  return r;
}

async function authenticatedObjectUrl(url: string): Promise<string> {
  const response = await authFetch(url);
  if (!response.ok) {
    const message = await response.text().catch(() => "");
    throw new Error(`${response.status} ${message || response.statusText}`);
  }
  return URL.createObjectURL(await response.blob());
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const t = await r.text().catch(() => "");
    let msg = t;
    try { const d = JSON.parse(t).detail; msg = typeof d === "string" ? d : JSON.stringify(d); } catch { /* raw text */ }
    throw new Error(`${r.status}${msg ? ` ${msg}` : ` ${r.statusText || "Request failed"}`}`);
  }
  if (r.status === 204) return undefined as T;
  try {
    return await r.json() as T;
  } catch {
    throw new Error(`Server returned an invalid JSON response (${r.status} ${r.statusText})`);
  }
}

async function uploadWithProgress<T>(url: string, body: FormData,
  onProgress?: (percent: number) => void, signal?: AbortSignal): Promise<T> {
  await ensureFreshToken();
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    if (signal?.aborted) {
      reject(new Error("Upload was cancelled"));
      return;
    }
    const abort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener("abort", abort);
    xhr.open("POST", url);
    signal?.addEventListener("abort", abort, { once: true });
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = event => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.min(100, Math.round(event.loaded / event.total * 100)));
      }
    };
    xhr.onerror = () => { cleanup(); reject(new Error("Upload failed: network error")); };
    xhr.onabort = () => { cleanup(); reject(new Error("Upload was cancelled")); };
    xhr.onload = () => {
      cleanup();
      if (xhr.status === 401) {
        try { handleUnauthorized(); } catch (error) { reject(error); }
        return;
      }
      let data: any;
      try { data = JSON.parse(xhr.responseText); }
      catch {
        reject(new Error(`Server returned an invalid JSON response (${xhr.status} ${xhr.statusText})`));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = data?.detail;
        reject(new Error(`${xhr.status} ${typeof detail === "string" ? detail : JSON.stringify(detail ?? xhr.statusText)}`));
        return;
      }
      resolve(data as T);
    };
    xhr.send(body);
  });
}

export const api = {
  authenticatedObjectUrl,
  async downloadAuthenticated(url: string, filename: string, openInNewTab = false,
    onProgress?: (percent: number | null) => void): Promise<void> {
    let objectUrl: string;
    if (onProgress) {
      const response = await authFetch(url);
      if (!response.ok) {
        const message = await response.text().catch(() => "");
        throw new Error(`${response.status} ${message || response.statusText}`);
      }
      const total = Number(response.headers.get("content-length")) || 0;
      const reader = response.body?.getReader();
      if (!reader) {
        onProgress(null);
        objectUrl = URL.createObjectURL(await response.blob());
      } else {
        const chunks: Uint8Array[] = [];
        let received = 0;
        onProgress(total ? 0 : null);
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.byteLength;
          onProgress(total ? Math.min(100, Math.round(received / total * 100)) : null);
        }
        objectUrl = URL.createObjectURL(new Blob(chunks as BlobPart[], { type: response.headers.get("content-type") || "application/octet-stream" }));
      }
    } else {
      objectUrl = await authenticatedObjectUrl(url);
    }
    if (openInNewTab) {
      const opened = window.open(objectUrl, "_blank", "noopener");
      if (!opened) URL.revokeObjectURL(objectUrl);
      else window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
      return;
    }
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  },
  async signup(email: string, name: string, password: string): Promise<{ access_token: string; refresh_token: string; user: { id: string; email: string; name: string } }> {
    const r = await fetch(`${BASE}/auth/signup`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, name, password }),
    });
    if (!r.ok) {
      const t = await r.text();
      let msg = t;
      try { msg = JSON.parse(t).detail; } catch {}
      throw new Error(msg);
    }
    const data = await r.json();
    setToken(data.access_token);
    return data;
  },
  async login(email: string, password: string): Promise<{ access_token: string; refresh_token: string; user: { id: string; email: string; name: string } }> {
    const r = await fetch(`${BASE}/auth/login`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      const t = await r.text();
      let msg = t;
      try { msg = JSON.parse(t).detail; } catch {}
      throw new Error(msg);
    }
    const data = await r.json();
    setToken(data.access_token);
    return data;
  },
  async forgotPassword(email: string): Promise<{ ok: boolean; message: string; _dev_token?: string }> {
    const r = await fetch(`${BASE}/auth/forgot-password`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "Could not send the password reset email");
    return data;
  },
  async resetPassword(token: string, new_password: string): Promise<{ ok: boolean }> {
    const r = await fetch(`${BASE}/auth/reset-password`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, new_password }),
    });
    if (!r.ok) {
      const t = await r.text();
      let msg = t;
      try { msg = JSON.parse(t).detail; } catch {}
      throw new Error(msg);
    }
    return r.json();
  },
  async getMe(): Promise<{ id: string; email: string; name: string }> {
    return j(await authFetch(`${BASE}/auth/me`));
  },

  async createJob(video: File, plan?: File | string,
    onProgress?: (percent: number) => void, signal?: AbortSignal): Promise<{ job: Job; errors: string[] }> {
    const fd = new FormData();
    fd.append("video", video);
    if (plan instanceof File) fd.append("plan", plan);
    else if (typeof plan === "string") fd.append("plan_text", plan);
    return uploadWithProgress(`${BASE}/jobs`, fd, onProgress, signal);
  },
  async getJob(id: string, signal?: AbortSignal): Promise<Job> {
    return j(await authFetch(`${BASE}/jobs/${id}`, { signal }));
  },
  async listJobs(): Promise<Job[]> {
    return j(await authFetch(`${BASE}/jobs`));
  },
  async putPlan(id: string, plan: any): Promise<{ ok: boolean; errors?: string[] }> {
    const r = await authFetch(`${BASE}/jobs/${id}/plan`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ plan }),
    });
    if (r.status === 422) return r.json();
    return j(r);
  },
  async validate(id: string, plan: any, signal?: AbortSignal): Promise<{ ok: boolean; errors: string[] }> {
    return j(await authFetch(`${BASE}/jobs/${id}/validate`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ plan }),
      signal,
    }));
  },
  async generatePlan(id: string, opts?: {
    style?: string; instruction?: string;
    whisper_model?: string; language?: string | null; use_saved_transcript?: boolean;
    transcribe_only?: boolean;
    transcription_hint?: string;
    asr_engine?: string;
    caption_font?: string;
    caption_font_id?: string;
    style_id?: string; style_version?: number;
    output_kind?: "reel" | "story" | "post";
    transition_style?: "auto" | "none" | "crossfade" | "directional" | "zoom";
    transition_request?: string;
  }): Promise<{ status: string; stage: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/generate-plan`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(opts || {}),
    }));
  },
  async getStyleLibrary(): Promise<StyleLibraryData> { return j(await authFetch(`${BASE}/style-library`)); },
  async addStyleSnapshots(files: File[], name: string): Promise<StyleDraft> {
    const fd = new FormData(); files.forEach(file => fd.append("files", file)); fd.append("name", name);
    return j(await authFetch(`${BASE}/style-library/snapshots`, { method: "POST", body: fd }));
  },
  async addStyleVideo(file: File, name: string): Promise<StyleDraft> {
    const fd = new FormData(); fd.append("file", file); fd.append("name", name);
    return j(await authFetch(`${BASE}/style-library/video`, { method: "POST", body: fd }));
  },
  async addStyleFile(file: File, name: string): Promise<StyleDraft> {
    const fd = new FormData(); fd.append("file", file); fd.append("name", name);
    return j(await authFetch(`${BASE}/style-library/file`, { method: "POST", body: fd }));
  },
  async updateStyleDraft(id: string, draft: { name: string; profile: any }): Promise<StyleDraft> {
    return j(await authFetch(`${BASE}/style-library/drafts/${id}`, { method: "PUT",
      headers: { "content-type": "application/json" }, body: JSON.stringify(draft) }));
  },
  async approveStyleDraft(id: string): Promise<StyleProfile> {
    return j(await authFetch(`${BASE}/style-library/drafts/${id}/approve`, { method: "POST" }));
  },
  async forkStyleProfile(styleId: string, version: number): Promise<StyleDraft> {
    return j(await authFetch(`${BASE}/style-library/profiles/${styleId}/versions/${version}/draft`, { method: "POST" }));
  },
  async deleteStyleDraft(id: string): Promise<{ ok: boolean; id: string; state: string }> {
    return j(await authFetch(`${BASE}/style-library/drafts/${id}`, { method: "DELETE" }));
  },
  async deleteStyleProfile(styleId: string, version: number): Promise<{ ok: boolean; style_id: string; version: number; state: string }> {
    return j(await authFetch(`${BASE}/style-library/profiles/${styleId}/versions/${version}`, { method: "DELETE" }));
  },
  async getPlanStyleSelection(): Promise<PlanStyleSelection> {
    return j(await authFetch(`${BASE}/style/plan-selection`));
  },
  async setPlanStyleSelection(styleId: string | null, version: number | null): Promise<PlanStyleSelection & { ok: boolean }> {
    return j(await authFetch(`${BASE}/style/plan-selection`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ style_id: styleId, version }),
    }));
  },
  async clearPlanStyleSelection(): Promise<PlanStyleSelection & { ok: boolean }> {
    return j(await authFetch(`${BASE}/style/plan-selection`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ style_id: null, version: null, selected: false }),
    }));
  },
  async setPlanDefaultVisibility(hidden: boolean): Promise<{ ok: boolean; default_hidden: boolean }> {
    return j(await authFetch(`${BASE}/style/plan-default-visibility`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ hidden }),
    }));
  },
  styleEvidenceUrl(asset: string): string { return `${BASE}/style-library/evidence/${encodeURIComponent(asset)}`; },
  async generateStatus(id: string, signal?: AbortSignal): Promise<GenerateStatus> {
    return j(await authFetch(`${BASE}/jobs/${id}/generate-plan/status`, { signal }));
  },
  async getTranscript(id: string, signal?: AbortSignal): Promise<Transcript> {
    return j(await authFetch(`${BASE}/jobs/${id}/transcript`, { signal }));
  },
  async putTranscriptCorrections(id: string, base_key: string,
    words: { index: number; text: string; start?: number; end?: number }[]): Promise<Transcript> {
    return j(await authFetch(`${BASE}/jobs/${id}/transcript/corrections`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ base_key, words }),
    }));
  },
  async listEffects(signal?: AbortSignal): Promise<EffectPreset[]> {
    return j(await authFetch(`${BASE}/effects`, { signal }));
  },
  async listFonts(signal?: AbortSignal): Promise<string[]> {
    const data = await j<{ fonts: string[] }>(await authFetch(`${BASE}/fonts`, { signal }));
    return data.fonts;
  },
  async getFontLibrary(): Promise<FontLibrary> {
    return j(await authFetch(`${BASE}/font-library`));
  },
  async addFontTextReference(body: { name: string; copied_text: string; font_name?: string; visual_reference?: string }): Promise<FontEntry> {
    return j(await authFetch(`${BASE}/font-library/text`, { method: "POST",
      headers: { "content-type": "application/json" }, body: JSON.stringify(body) }));
  },
  async addFontImage(file: File): Promise<FontEntry> {
    const fd = new FormData(); fd.append("image", file);
    return j(await authFetch(`${BASE}/font-library/image`, { method: "POST", body: fd }));
  },
  async addFontFile(file: File): Promise<FontEntry> {
    const fd = new FormData(); fd.append("font", file);
    return j(await authFetch(`${BASE}/font-library/font`, { method: "POST", body: fd }));
  },
  async approveFont(id: string): Promise<FontEntry> {
    return j(await authFetch(`${BASE}/font-library/${id}/approve`, { method: "POST" }));
  },
  async deleteFont(id: string): Promise<{ ok: boolean; id: string; state: string }> {
    return j(await authFetch(`${BASE}/font-library/${id}`, { method: "DELETE" }));
  },
  fontFileUrl(id: string, candidate = false): string {
    return candidate ? `${BASE}/font-library/candidates/${id}/file` : `${BASE}/font-library/fonts/${id}/file`;
  },
  async getMyEffects(): Promise<any> {
    return j(await authFetch(`${BASE}/my-effects`));
  },
  async putMyEffects(data: any): Promise<any> {
    return j(await authFetch(`${BASE}/my-effects`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify(data),
    }));
  },
  async getRafieiStyles(): Promise<RafieiStyle> {
    return j(await authFetch(`${BASE}/rafiei-styles`));
  },
  async selectRafieiStyle(styleId: string | null): Promise<{ ok: boolean; selected_rafiei_style: string | null }> {
    return j(await authFetch(`${BASE}/my-effects/select-rafiei`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ style_id: styleId }),
    }));
  },
  async getCorrections(id: string, signal?: AbortSignal): Promise<Corrections> {
    return j(await authFetch(`${BASE}/jobs/${id}/corrections`, { signal }));
  },
  async acceptCorrection(id: string, body: {
    base_key: string; index: number; old: string; new: string;
    start?: number; end?: number; save_to_glossary?: boolean;
  }): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/corrections/accept`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }));
  },
  async rejectCorrection(id: string, body: { index: number; old: string }): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/corrections/reject`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }));
  },
  async render(id: string, preview: boolean, loudnorm = true): Promise<{ status: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/render?preview=${preview}&loudnorm=${loudnorm}`, { method: "POST" }));
  },
  async renderStatus(id: string, signal?: AbortSignal) {
    return j<{
      status: string; progress: number; message: string;
      output?: string; preview: boolean; versions: string[];
    }>(await authFetch(`${BASE}/jobs/${id}/render/status`, { signal }));
  },
  premiereUrl(id: string) { return `${BASE}/jobs/${id}/premiere`; },
  premiereXmlUrl(id: string) { return `${BASE}/jobs/${id}/premiere.xml`; },
  premiereCaptionsUrl(id: string) { return `${BASE}/jobs/${id}/premiere/captions`; },
  premiereReportUrl(id: string) { return `${BASE}/jobs/${id}/premiere/report`; },
  async premiereReport(id: string, signal?: AbortSignal) {
    return j<any>(await authFetch(`${BASE}/jobs/${id}/premiere/report`, { signal }));
  },
  async premiereStatus(id: string) {
    return j<PremiereStatus>(await authFetch(`${BASE}/jobs/${id}/premiere/status`));
  },
  async openPremiere(id: string, mode: PremiereMode, confirmPreview = false) {
    return j<{ status: string; message: string }>(await authFetch(`${BASE}/jobs/${id}/premiere/open`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ mode, confirm_preview: confirmPreview }),
    }));
  },
  async linkPremiereProject(id: string) {
    return j<{ status: string; project_name: string; message?: string }>(await authFetch(`${BASE}/jobs/${id}/premiere/link-project`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ project_name: `ai-render-${id}-clean.prproj` }),
    }));
  },
  async startPremiereBridge(id: string, forceRefresh = false) {
    return j<{ operation_id: string; pairing_code: string; state: string; expires_in_seconds: number; bridge_kind: string }>(
      await authFetch(`${BASE}/jobs/${id}/premiere/bridge/session`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ force_refresh: forceRefresh }),
      }));
  },
  async runQC(id: string): Promise<{ status: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/qc/run`, { method: "POST" }));
  },
  async qcStatus(id: string) {
    return j<{
      status: string; message: string; current_round: number;
      total_issues: number; fixed_issues: number;
      issues: any[]; changes: any[];
    }>(await authFetch(`${BASE}/jobs/${id}/qc/status`));
  },
  async applyQCFixes(id: string, issueIndices?: number[]): Promise<{ ok: boolean; changes: any[]; plan: any }> {
    return j(await authFetch(`${BASE}/jobs/${id}/qc/apply`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ issue_indices: issueIndices ?? null }),
    }));
  },
  async uploadMusic(id: string, file: File): Promise<{ ok: boolean; path: string }> {
    const fd = new FormData();
    fd.append("file", file);
    return j(await authFetch(`${BASE}/jobs/${id}/music/upload`, { method: "POST", body: fd }));
  },
  async generateMusic(id: string, prompt: string): Promise<{ ok: boolean; path: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/music/generate`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt }),
    }));
  },
  async importLibraryMusic(id: string, filename: string): Promise<{ ok: boolean; path: string }> {
    const response = await authFetch(`${BASE}/library/music/${encodeURIComponent(filename)}/preview`);
    if (!response.ok) throw new Error(`Could not read library track (${response.status})`);
    return api.uploadMusic(id, new File([await response.blob()], filename));
  },
  musicPreviewUrl(id: string, filename?: string) {
    return `${BASE}/jobs/${id}/music/preview${filename ? `?filename=${encodeURIComponent(filename)}` : ""}`;
  },
  // Background music mixed into the render
  async getMusicStatus(id: string, signal?: AbortSignal): Promise<MusicStatus> {
    return j(await authFetch(`${BASE}/jobs/${id}/music/status`, { signal }));
  },
  attachMusic(id: string, file: File, onProgress?: (percent: number) => void): Promise<MusicStatus> {
    const fd = new FormData();
    fd.append("file", file);
    return uploadWithProgress(`${BASE}/jobs/${id}/music`, fd, onProgress);
  },
  async mixMusic(id: string, settings: { volume_level: number; fade_in_seconds: number; fade_out_seconds: number }): Promise<{ status: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/music/mix`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(settings),
    }));
  },
  async removeMusic(id: string): Promise<{ ok: boolean }> {
    return j(await authFetch(`${BASE}/jobs/${id}/music`, { method: "DELETE" }));
  },
  musicMixPreviewUrl(id: string, settings: { volume_level: number; fade_in_seconds: number; fade_out_seconds: number }, nonce: number) {
    const q = new URLSearchParams({
      volume_level: String(settings.volume_level), fade_in_seconds: String(settings.fade_in_seconds),
      fade_out_seconds: String(settings.fade_out_seconds), t: String(nonce),
    });
    return `${BASE}/jobs/${id}/music/preview?${q}`;
  },
  // ── Denoise ──
  async startDenoise(id: string, strength = 0.5): Promise<{ status: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/start`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ strength }),
    }));
  },
  async triggerDenoise(id: string, strength: "light" | "medium" | "heavy", preserveVoice: boolean): Promise<{ status: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ strength, preserve_voice: preserveVoice }),
    }));
  },
  async getDenoiseCompare(id: string): Promise<{ original_url: string; denoised_url: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/compare`));
  },
  async applyDenoise(id: string): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/apply`, { method: "POST" }));
  },
  async getDenoiseStatus(id: string): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/status`));
  },
  async getDenoiseSamples(id: string): Promise<{ original_url: string; cleaned_url: string; offset_s: number; duration_s: number }> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/samples`));
  },
  async approveDenoise(id: string): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/approve`, { method: "POST" }));
  },
  async bypassDenoise(id: string, bypass: boolean): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/bypass`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ bypass }),
    }));
  },
  async adjustDenoise(id: string, strength: number): Promise<{ status: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/denoise/adjust`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ strength }),
    }));
  },
  denoiseAudioUrl(id: string, which: "original" | "cleaned"): string {
    return `${BASE}/jobs/${id}/denoise/sample/${which}`;
  },

  rawUrl(id: string) { return `${BASE}/jobs/${id}/raw`; },
  exportUrl(id: string, fname: string) { return `${BASE}/jobs/${id}/exports/${fname}`; },
  planUrl(id: string) { return `${BASE}/jobs/${id}/plan.json`; },

  // ── Asset Library ──
  async getLibrary(): Promise<LibraryData> {
    return j(await authFetch(`${BASE}/library`));
  },
  async rescanLibrary(): Promise<{ ok: boolean; counts: Record<string, number> }> {
    return j(await authFetch(`${BASE}/library/rescan`, { method: "POST" }));
  },
  async uploadLibraryAsset(file: File, category: string, tags: string,
    mood?: string, energy?: number, description?: string): Promise<LibraryAsset> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("category", category);
    fd.append("tags", tags);
    if (mood) fd.append("mood", mood);
    if (energy != null) fd.append("energy", String(energy));
    if (description) fd.append("description", description);
    return j(await authFetch(`${BASE}/library/upload`, { method: "POST", body: fd }));
  },
  async updateLibraryAsset(category: string, filename: string,
    body: { tags?: string[]; mood?: string; energy?: number; description?: string }): Promise<LibraryAsset> {
    return j(await authFetch(`${BASE}/library/${category}/${encodeURIComponent(filename)}`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }));
  },
  async deleteLibraryAsset(category: string, filename: string): Promise<{ ok: boolean }> {
    return j(await authFetch(`${BASE}/library/${category}/${encodeURIComponent(filename)}`, { method: "DELETE" }));
  },
  libraryPreviewUrl(category: string, filename: string): string {
    return `${BASE}/library/${category}/${encodeURIComponent(filename)}/preview`;
  },
  // ── Style Learner ──
  async analyzeReference(file: File, onProgress?: (percent: number) => void): Promise<any> {
    const fd = new FormData(); fd.append("file", file);
    return uploadWithProgress(`${BASE}/style/analyze`, fd, onProgress);
  },
  async getLearnedProfile(): Promise<LearnedStyleProfile> {
    return j(await authFetch(`${BASE}/style/profile`));
  },
  async updateLearnedProfile(body: any): Promise<{ ok: boolean }> {
    return j(await authFetch(`${BASE}/style/profile`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }));
  },
  async rebuildLearnedProfile(): Promise<any> {
    return j(await authFetch(`${BASE}/style/rebuild`, { method: "POST" }));
  },
  async resetLearnedProfile(): Promise<{ ok: boolean }> {
    return j(await authFetch(`${BASE}/style/reset`, { method: "POST" }));
  },
  async getFeedbackSummary(): Promise<any> {
    return j(await authFetch(`${BASE}/style/feedback`));
  },
  async getFewShotExamples(): Promise<{ examples: any[] }> {
    return j(await authFetch(`${BASE}/style/examples`));
  },
  async postPlanFeedback(id: string, events: any[]): Promise<{ ok: boolean; logged: number }> {
    return j(await authFetch(`${BASE}/jobs/${id}/feedback`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ events }),
    }));
  },
  async listReferenceAnalyses(): Promise<{ analyses: any[] }> {
    return j(await authFetch(`${BASE}/style/analyses`));
  },
  styleReferenceVideoUrl(refId: string): string {
    return `${BASE}/style/analyses/${encodeURIComponent(refId)}/video`;
  },
  async deleteReferenceAnalysis(filename: string): Promise<{ ok: boolean }> {
    return j(await authFetch(`${BASE}/style/analyses/${encodeURIComponent(filename)}`, { method: "DELETE" }));
  },

  async matchBroll(query: string, minDuration = 0): Promise<LibraryAsset[]> {
    const fd = new FormData();
    fd.append("query", query);
    fd.append("min_duration", String(minDuration));
    return j(await authFetch(`${BASE}/library/match/broll`, { method: "POST", body: fd }));
  },

  // ── Content Creator ──
  async createContent(prompt: string, content_type: string, language: string, style: string, provider: string,
                      creative_brief: { audience?: string; goal?: string; brand?: string; avoid?: string } = {}): Promise<{ job_id: string; storyboard: { scenes?: any[]; is_fallback?: boolean; [key: string]: any } }> {
    const result = await j<{ job_id: string; storyboard: { scenes?: any[]; is_fallback?: boolean; [key: string]: any } }>(await authFetch(`${BASE}/content/create`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt, content_type, language, style, provider, creative_brief }),
    }));
    invalidateJobCache();
    return result;
  },
  async getStoryboard(id: string): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/storyboard`));
  },
  async updateStoryboard(id: string, scenes: any[]): Promise<any> {
    return j(await authFetch(`${BASE}/jobs/${id}/storyboard`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ scenes }),
    }));
  },
  async approveStoryboard(id: string, provider?: string): Promise<{ status: string }> {
    return j(await authFetch(`${BASE}/jobs/${id}/storyboard/approve`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(provider ? { provider } : {}),
    }));
  },
  async getStoryboardStatus(id: string): Promise<{ state: string; scenes_done: number; scenes_total: number; cost_so_far: number | null; error?: string; warnings?: string[] } | null> {
    return j(await authFetch(`${BASE}/jobs/${id}/storyboard/status`));
  },
  async getProviders(signal?: AbortSignal): Promise<any[]> {
    return j(await authFetch(`${BASE}/content/providers`, { signal }));
  },
  async exportImage(id: string): Promise<Blob> {
    const r = await authFetch(`${BASE}/content/export-image/${id}`, { method: "POST" });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.blob();
  },
};
