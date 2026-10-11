import React from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";
import { LoadingState, friendlyError } from "./ui";

interface Scene {
  index: number;
  description: string;
  duration_s: number;
  text_overlay: string;
  narration_text?: string;
  narration_voice?: string;
  media_method: "generate" | "library" | "upload";
  media_prompt: string;
  estimated_cost: number;
}

const CONTENT_TYPES = [
  { id: "reel", label: "Reel", aspect: "9:16", maxDur: "90s", w: 27, h: 48 },
  { id: "post", label: "Post", aspect: "1:1", maxDur: "Static", w: 40, h: 40 },
  { id: "story", label: "Story", aspect: "9:16", maxDur: "15s", w: 27, h: 48 },
] as const;

export default function ContentCreator() {
  const nav = useNavigate();
  const [prompt, setPrompt] = React.useState("");
  const [creativeBrief, setCreativeBrief] = React.useState({ audience: "", goal: "", brand: "", avoid: "" });
  const [contentType, setContentType] = React.useState("reel");
  const [language, setLanguage] = React.useState("fa");
  const [style, setStyle] = React.useState("rafiei_reel");
  const [provider, setProvider] = React.useState("");
  const [providers, setProviders] = React.useState<any[]>([]);
  const [providersLoading, setProvidersLoading] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);

  const [jobId, setJobId] = React.useState<string | null>(null);
  const [scenes, setScenes] = React.useState<Scene[]>([]);
  const [usingTemplate, setUsingTemplate] = React.useState(false);
  const [generating, setGenerating] = React.useState(false);
  const [genStatus, setGenStatus] = React.useState<{
    state: string; scenes_done: number; scenes_total: number; cost_so_far: number | null;
    cost_status?: string; error?: string;
  } | null>(null);

  const [providerError, setProviderError] = React.useState(false);
  const [providerReload, setProviderReload] = React.useState(0);

  React.useEffect(() => {
    const ctrl = new AbortController();
    let cancelled = false;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; ctrl.abort(); }, 10000);
    setProvidersLoading(true);
    setProviderError(false);
    setErr(null);
    api.getProviders(ctrl.signal).then(items => {
      const list = Array.isArray(items) ? items : [];
      setProviders(list);
      setProvider(current => current || (
        list.find((p: any) => p.name === "sarovi_nano_banana" && p.key_configured)?.name
        || list.find((p: any) => p.name === "sarovi_seedream" && p.key_configured)?.name
        || list.find((p: any) => p.name === "jarvis_image" && p.key_configured)?.name
        || "local_fixture"
      ));
    }).catch((e: Error) => {
      if (cancelled) return;
      setProvider(current => current || "local_fixture");
      const missing = /^404\b/.test(e.message);
      setErr(missing
        ? "Provider list endpoint not found. The local demo provider is selected."
        : (timedOut ? "Loading media providers timed out." : friendlyError(e, "load media providers")) + " The local demo provider is selected.");
      setProviderError(true);
    }).finally(() => {
      clearTimeout(timeout);
      if (!cancelled) setProvidersLoading(false);
    });
    return () => { cancelled = true; clearTimeout(timeout); ctrl.abort(); };
  }, [providerReload]);

  React.useEffect(() => {
    if (!generating || !jobId) return;
    let inFlight = false;
    const tick = () =>
      {
        if (inFlight) return;
        inFlight = true;
        api.getStoryboardStatus(jobId).then(s => {
        if (!s) return;
        setGenStatus(s);
        if (s.state === "ready") {
          setGenerating(false);
          nav(`/jobs/${jobId}`);
        } else if (s.state === "failed") {
          setGenerating(false);
          setErr(friendlyError(s.error, "generate media"));
        }
        }).catch((e: Error) => setErr(friendlyError(e, "check generation progress")))
          .finally(() => { inFlight = false; });
      };
    tick();
    const iv = setInterval(tick, 2000);
    return () => clearInterval(iv);
  }, [generating, jobId, nav]);

  async function onGenerateStoryboard() {
    if (!prompt.trim()) { setErr("Enter a prompt first"); return; }
    if (!provider) { setErr("Wait for media providers to load"); return; }
    setBusy(true); setErr(null); setUsingTemplate(false);
    try {
      const res = await api.createContent(prompt, contentType, language, style, provider, creativeBrief);
      setJobId(res.job_id);
      setScenes(res.storyboard.scenes || []);
      setUsingTemplate(res.storyboard.is_fallback === true);
    } catch (e: any) {
      setErr(friendlyError(e, "create a storyboard"));
    } finally { setBusy(false); }
  }

  async function onApprove() {
    if (!jobId) return;
    setBusy(true); setErr(null);
    try {
      await api.updateStoryboard(jobId, scenes);
      await api.approveStoryboard(jobId, provider);
      setGenerating(true);
    } catch (e: any) {
      setErr(friendlyError(e, "approve the storyboard"));
    } finally { setBusy(false); }
  }

  function updateScene(idx: number, patch: Partial<Scene>) {
    setScenes(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
  }

  function moveScene(idx: number, dir: -1 | 1) {
    const target = idx + dir;
    if (target < 0 || target >= scenes.length) return;
    setScenes(prev => {
      const next = [...prev];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next.map((s, i) => ({ ...s, index: i }));
    });
  }

  function deleteScene(idx: number) {
    setScenes(prev => prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, index: i })));
  }

  const totalCost = scenes.reduce((sum, s) => sum + (s.estimated_cost || 0), 0);
  const totalDuration = scenes.reduce((sum, s) => sum + (s.duration_s || 0), 0);

  return (
    <div>
      <h1>Content Creator</h1>

      {/* Prompt */}
      <div className="card">
        <div className="section-header">
          <h2>Prompt</h2>
          <span className="muted">Step 1</span>
        </div>
        <label htmlFor="content-prompt">Describe your content</label>
        <textarea
          id="content-prompt"
          aria-label="Describe the content to create"
          rows={4}
          placeholder="Describe your content..."
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          style={{ width: "100%", fontFamily: "inherit", fontSize: 14 }}
        />
      </div>

      <div className="card">
        <div className="section-header">
          <h2>Creative brief</h2>
          <span className="muted">Optional</span>
        </div>
        <p className="muted">Add customer context so the concept, visuals, and call to action fit the brand.</p>
        <div className="grid2">
          {([
            ["audience", "Audience", "Who should watch this?"],
            ["goal", "Viewer action", "What should viewers do or feel?"],
            ["brand", "Brand identity", "Product, palette, visual references"],
            ["avoid", "Avoid", "Cliches, claims, imagery, or words to avoid"],
          ] as const).map(([key, label, placeholder]) => (
            <label key={key}>{label}
              <input value={creativeBrief[key]} maxLength={500} placeholder={placeholder}
                onChange={e => setCreativeBrief(prev => ({ ...prev, [key]: e.target.value }))} />
            </label>
          ))}
        </div>
      </div>

      {/* Content Type */}
      <div className="card">
        <div className="section-header">
          <h2>Content Type</h2>
          <span className="muted">Step 2</span>
        </div>
        <div className="content-type-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
          {CONTENT_TYPES.map(ct => (
            <button type="button"
              key={ct.id}
              aria-pressed={contentType === ct.id}
              onClick={() => setContentType(ct.id)}
              style={{
                padding: "18px 16px",
                flexDirection: "column", whiteSpace: "normal", minWidth: 0,
                borderRadius: "var(--radius-md)",
                border: contentType === ct.id
                  ? "2px solid var(--accent)"
                  : "1px solid var(--border-strong)",
                background: contentType === ct.id ? "var(--accent-soft)" : "var(--bg-elevated)",
                cursor: "pointer",
                textAlign: "center",
                transition: "all 150ms",
              }}
            >
              <div style={{
                width: ct.w, height: ct.h,
                border: "2px solid " + (contentType === ct.id ? "var(--accent)" : "var(--text-tertiary)"),
                borderRadius: 4,
                margin: "0 auto 10px",
              }} />
              <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>{ct.label}</div>
              <div className="muted">{ct.aspect} &middot; {ct.maxDur}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Settings */}
      <div className="card">
        <div className="section-header">
          <h2>Settings</h2>
          <span className="muted">Step 3</span>
        </div>
        <div className="row" style={{ gap: 16 }}>
          <label>Language
            <select value={language} onChange={e => setLanguage(e.target.value)}>
              <option value="fa">Persian</option>
              <option value="en">English</option>
            </select>
          </label>
          <label>Style
            <select value={style} onChange={e => setStyle(e.target.value)}>
              <option value="rafiei_reel">Rafiei Reel</option>
            </select>
          </label>
          <label>Provider
            <select value={provider} onChange={e => setProvider(e.target.value)} disabled={providersLoading} title={providersLoading ? "Loading media providers" : undefined}>
              {!provider && <option value="">Loading providers...</option>}
              {provider && !providers.some((p: any) => p.name === provider) && <option value={provider}>Local demo provider</option>}
              {providers.map((p: any) => (
                <option key={p.name} value={p.name}>
                  {{
                    local_fixture: "Local Fixture — placeholder demo",
                    jarvis_image: "Generated visuals — Jarvis Image",
                    sarovi_seedream: "Sarovi Seedream 5.0 Lite — visual concepts",
                    sarovi_nano_banana: "Sarovi Nano Banana — content visuals",
                  }[p.name as "local_fixture" | "jarvis_image" | "sarovi_seedream" | "sarovi_nano_banana"] || p.name}
                  {p.name !== "local_fixture" && !p.key_configured ? " (not configured)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        {provider === "local_fixture" && (
          <p className="errors" role="status" style={{ marginTop: 12 }}>
            Demo visuals: this provider creates solid color placeholder clips. Use a configured image provider for customer-facing video.
          </p>
        )}
        {provider && provider !== "local_fixture" && providers.find((p: any) => p.name === provider && !p.key_configured) && (
          <p className="errors" role="status" style={{ marginTop: 12 }}>
            This provider is not configured. Choose a configured provider before generating media.
          </p>
        )}
        {!providersLoading && !providerError && providers.length === 0 && <p className="muted" role="status">No configured media providers yet. The local demo provider is available for a placeholder storyboard.</p>}
      </div>

      {/* Generate Button */}
      <p className="muted">Background music is selected from your music library. After generation, preview the mix and change or upload a track in the plan editor. Voiceover uses the script for each scene.</p>
      {!scenes.length && (
        <div style={{ marginBottom: 16 }}>
          <button onClick={onGenerateStoryboard} disabled={busy || providersLoading || !prompt.trim() || !provider} title={busy ? "Creating storyboard" : providersLoading ? "Loading media providers" : !prompt.trim() ? "Enter a prompt first" : !provider ? "Choose a media provider" : undefined}>
            {busy ? "Generating..." : "Generate Storyboard"}
          </button>
        </div>
      )}

      {/* Storyboard Scene Cards */}
      {scenes.length > 0 && (
        <div className="card">
          {usingTemplate && (
            <div role="status" style={{
              marginBottom: 16,
              padding: "10px 12px",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--warning)",
              background: "var(--warning-soft)",
              color: "var(--warning)",
              fontWeight: 600,
            }}>
              Using template — edit to customize
            </div>
          )}
          <div className="section-header">
            <h2>Storyboard</h2>
            <span className="muted">
              {scenes.length} scene{scenes.length !== 1 ? "s" : ""} &middot; {totalDuration.toFixed(1)}s
            </span>
          </div>

          {scenes.map((scene, idx) => (
            <div key={idx} style={{
              padding: "14px 16px",
              marginBottom: 8,
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                <span style={{
                  fontWeight: 700, fontSize: 12, color: "var(--accent-hover)",
                  fontFamily: "SF Mono, monospace", minWidth: 28,
                }}>
                  #{idx + 1}
                </span>
                <span className="muted" style={{ flex: 1, fontSize: 13 }}>{scene.description}</span>
                <span style={{
                  padding: "2px 8px", borderRadius: 100, fontSize: 10, fontWeight: 700,
                  textTransform: "uppercase", letterSpacing: 0.5,
                  background: scene.media_method === "generate"
                    ? "var(--accent-soft)" : scene.media_method === "library"
                    ? "var(--success-soft)" : "var(--warning-soft)",
                  color: scene.media_method === "generate"
                    ? "var(--accent-hover)" : scene.media_method === "library"
                    ? "var(--success)" : "var(--warning)",
                }}>
                  {scene.media_method}
                </span>
                <span className="muted" style={{ fontSize: 12, fontFamily: "SF Mono, monospace" }}>
                  {scene.duration_s.toFixed(1)}s
                </span>
              </div>

              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>Text overlay</span>
                  <input
                    dir="auto"
                    type="text"
                    disabled={busy || generating}
                    value={scene.text_overlay}
                    onChange={e => updateScene(idx, { text_overlay: e.target.value })}
                    placeholder="No text overlay"
                    style={{ width: "100%", fontSize: 13, padding: "6px 10px" }}
                  />
                </label>
              </div>

              <label style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
                <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>Voiceover script</span>
                <textarea
                  dir="auto"
                  rows={2}
                  disabled={busy || generating}
                  value={scene.narration_text || ""}
                  onChange={e => updateScene(idx, { narration_text: e.target.value })}
                  placeholder="No narration for this scene"
                  style={{ width: "100%", fontSize: 13, padding: "6px 10px" }}
                />
              </label>

              <label>Scene duration (seconds)
                <input type="number" min={0.5} max={90} step={0.5}
                  disabled={busy || generating || contentType === "post"}
                  title={contentType === "post" ? "Static posts have no duration" : busy || generating ? "Wait for generation to finish" : undefined}
                  value={scene.duration_s}
                  onChange={e => updateScene(idx, { duration_s: Number(e.target.value) })} />
              </label>

              <div style={{ display: "flex", gap: 6, marginTop: 8, justifyContent: "flex-end" }}>
                <button className="secondary" style={{ padding: "4px 10px", fontSize: 12 }}
                  aria-label={`Move scene ${idx + 1} earlier`}
                  disabled={busy || generating || idx === 0} title={idx === 0 ? "Already the first scene" : busy || generating ? "Wait for generation to finish" : undefined} onClick={() => moveScene(idx, -1)}>
                  &#9650;
                </button>
                <button className="secondary" style={{ padding: "4px 10px", fontSize: 12 }}
                  aria-label={`Move scene ${idx + 1} later`}
                  disabled={busy || generating || idx === scenes.length - 1} title={idx === scenes.length - 1 ? "Already the last scene" : busy || generating ? "Wait for generation to finish" : undefined} onClick={() => moveScene(idx, 1)}>
                  &#9660;
                </button>
                <button className="danger-sm" aria-label={`Delete scene ${idx + 1}`} disabled={busy || generating} title={busy || generating ? "Wait for generation to finish" : undefined} onClick={() => deleteScene(idx)}>
                  &#10005;
                </button>
              </div>
            </div>
          ))}

          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "12px 0", borderTop: "1px solid var(--border)", marginTop: 8,
          }}>
            <span className="muted">
              Planning estimate: ${totalCost.toFixed(4)} (actual provider billing may differ or be unavailable)
            </span>
            {contentType === "post" && (
              <span className="muted">Static image will also be exported</span>
            )}
          </div>

          <div style={{ marginTop: 12 }}>
            <button onClick={onApprove} disabled={busy || generating || scenes.length === 0} title={busy || generating ? "Generation in progress" : scenes.length === 0 ? "Add at least one scene" : undefined}>
              {generating ? "Generating media..." : genStatus?.state === "failed" ? "Retry Generation" : "Approve & Generate"}
            </button>
          </div>
        </div>
      )}

      {/* Generation Progress */}
      {generating && !genStatus && <LoadingState label="Checking storyboard generation…" rows={1} />}
      {generating && genStatus && (
        <div className="card">
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <span className="generating-pulse" style={{
              width: 8, height: 8, borderRadius: "50%", background: "var(--accent)",
            }} />
            <span style={{ fontWeight: 600 }}>
              Generating media: {genStatus.scenes_done}/{genStatus.scenes_total} scenes
            </span>
          </div>
          <div className="progress">
            <div style={{
              width: genStatus.scenes_total > 0
                ? `${(genStatus.scenes_done / genStatus.scenes_total) * 100}%`
                : "0%",
            }} />
          </div>
          <div className="muted" style={{ marginTop: 8 }}>
            Cost so far: {genStatus.cost_so_far == null
              ? "not reported by provider"
              : `$${genStatus.cost_so_far.toFixed(4)}`}
          </div>
        </div>
      )}

      {providersLoading && <LoadingState label="Loading media providers…" rows={1} />}
      {err && <div className="errors" role="alert">{err}
        {providerError && <button style={{ marginLeft: 12 }} onClick={() => setProviderReload(n => n + 1)}>Retry</button>}
      </div>}
    </div>
  );
}
