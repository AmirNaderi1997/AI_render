const BASE = "/api";

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

export interface Transcript {
  file_hash: string;
  language: string;
  duration: number;
  words: { w: string; start: number; end: number; prob: number }[];
  sentences: { text: string; start: number; end: number }[];
}

export interface GenerateStatus {
  status: string; stage: string; message: string;
  cost_usd: number; input_tokens: number; output_tokens: number; model: string;
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const t = await r.text();
    let msg = t;
    try { const d = JSON.parse(t).detail; msg = typeof d === "string" ? d : JSON.stringify(d); } catch { /* raw text */ }
    throw new Error(`${r.status} ${msg}`);
  }
  return r.json();
}

export const api = {
  async createJob(video: File, plan?: File | string): Promise<{ job: Job; errors: string[] }> {
    const fd = new FormData();
    fd.append("video", video);
    if (plan instanceof File) fd.append("plan", plan);
    else if (typeof plan === "string") fd.append("plan_text", plan);
    return j(await fetch(`${BASE}/jobs`, { method: "POST", body: fd }));
  },
  async getJob(id: string): Promise<Job> {
    return j(await fetch(`${BASE}/jobs/${id}`));
  },
  async listJobs(): Promise<Job[]> {
    return j(await fetch(`${BASE}/jobs`));
  },
  async putPlan(id: string, plan: any): Promise<{ ok: boolean; errors?: string[] }> {
    const r = await fetch(`${BASE}/jobs/${id}/plan`, {
      method: "PUT", headers: { "content-type": "application/json" },
      body: JSON.stringify({ plan }),
    });
    if (r.status === 422) return r.json();
    return j(r);
  },
  async validate(id: string, plan: any): Promise<{ ok: boolean; errors: string[] }> {
    return j(await fetch(`${BASE}/jobs/${id}/validate`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ plan }),
    }));
  },
  async generatePlan(id: string, opts?: {
    style?: string; instruction?: string;
    whisper_model?: string; language?: string;
  }): Promise<{ status: string; stage: string }> {
    return j(await fetch(`${BASE}/jobs/${id}/generate-plan`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(opts || {}),
    }));
  },
  async generateStatus(id: string): Promise<GenerateStatus> {
    return j(await fetch(`${BASE}/jobs/${id}/generate-plan/status`));
  },
  async getTranscript(id: string): Promise<Transcript> {
    return j(await fetch(`${BASE}/jobs/${id}/transcript`));
  },
  async render(id: string, preview: boolean): Promise<{ status: string }> {
    return j(await fetch(`${BASE}/jobs/${id}/render?preview=${preview}`, { method: "POST" }));
  },
  async renderStatus(id: string) {
    return j<{
      status: string; progress: number; message: string;
      output?: string; preview: boolean; versions: string[];
    }>(await fetch(`${BASE}/jobs/${id}/render/status`));
  },
  async openKdenlive(id: string) {
    return j<{ ok: boolean; path: string }>(await fetch(`${BASE}/jobs/${id}/open-kdenlive`, { method: "POST" }));
  },
  rawUrl(id: string) { return `${BASE}/jobs/${id}/raw`; },
  exportUrl(id: string, fname: string) { return `${BASE}/jobs/${id}/exports/${fname}`; },
  planUrl(id: string) { return `${BASE}/jobs/${id}/plan.json`; },
};
