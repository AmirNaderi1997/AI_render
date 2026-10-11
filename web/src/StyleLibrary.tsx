import React from "react";
import { api, StyleDraft, StyleLibraryData, StyleProfile } from "./api";
import { useSearchParams } from "react-router-dom";
import { FontLibrary } from "./FontLibrary";
import { AuthenticatedMedia } from "./AuthenticatedMedia";
import { EmptyState, LoadingState, friendlyError } from "./ui";

export function StylePicker({ value, onChange }: { value: StyleProfile | null; onChange: (style: StyleProfile | null) => void }) {
  const [profiles, setProfiles] = React.useState<StyleProfile[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  React.useEffect(() => { api.getStyleLibrary().then(d => setProfiles([...d.profiles].sort((a, b) => a.name.localeCompare(b.name))))
    .catch(e => setError(friendlyError(e, "load visual styles"))).finally(() => setLoading(false)); }, []);
  return <label style={{ display: "block", marginTop: 10 }}>Plan style profile
    <select
      value={value ? `${value.style_id}@${value.version}` : "default"}
      onChange={e => {
        if (e.target.value === "default") return onChange(null);
        const found = profiles.find(p => `${p.style_id}@${p.version}` === e.target.value);
        onChange(found || null);
      }}>
      <option value="default">{loading ? "Loading styles…" : "Learned style when active (otherwise Rafiei Reel)"}</option>
      {profiles.map(p => <option key={`${p.style_id}@${p.version}`} value={`${p.style_id}@${p.version}`}>{p.name} · v{p.version}</option>)}
    </select>
    {error && <span className="errors" role="alert">{error}</span>}
  </label>;
}

export default function StyleLibrary() {
  const [data, setData] = React.useState<StyleLibraryData>({ drafts: [], profiles: [] });
  const [kind, setKind] = React.useState("snapshots");
  const [files, setFiles] = React.useState<File[]>([]);
  const [name, setName] = React.useState("");
  const [draft, setDraft] = React.useState<StyleDraft | null>(null);
  const [profileText, setProfileText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [searchParams] = useSearchParams();

  const refresh = React.useCallback(async () => setData(await api.getStyleLibrary()), []);
  React.useEffect(() => { refresh().catch(e => setError(friendlyError(e, "load the style library"))).finally(() => setLoading(false)); }, [refresh]);
  React.useEffect(() => {
    if (window.location.hash === "#fonts") {
      window.requestAnimationFrame(() => document.getElementById("fonts")?.scrollIntoView({ block: "start" }));
    }
  }, []);
  React.useEffect(() => {
    const id = searchParams.get("draft");
    if (id) api.getStyleLibrary().then(library => {
      const found = library.drafts.find(item => item.id === id);
      if (found) openDraft(found);
    }).catch(e => setError(friendlyError(e, "open this style draft")));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  function openDraft(d: StyleDraft) { setDraft(d); setName(d.name); setProfileText(JSON.stringify(d.profile, null, 2)); }
  async function importStyle() {
    if (!files.length) return;
    setBusy(true); setError("");
    try {
      const d = kind === "snapshots" ? await api.addStyleSnapshots(files, name || "Snapshot style")
        : kind === "video" ? await api.addStyleVideo(files[0], name || "Video reference")
          : await api.addStyleFile(files[0], name || files[0].name.replace(/\.[^.]+$/, ""));
      await refresh(); openDraft(d); setFiles([]);
    } catch (e: any) { setError(friendlyError(e, "import this style")); }
    finally { setBusy(false); }
  }
  async function saveDraft(approve = false) {
    if (!draft) return;
    setBusy(true); setError("");
    try {
      const profile = JSON.parse(profileText);
      const updated = await api.updateStyleDraft(draft.id, { name, profile });
      if (approve) {
        await api.approveStyleDraft(updated.id); setDraft(null); await refresh();
      } else { openDraft(updated); await refresh(); }
    } catch (e: any) { setError(friendlyError(e, approve ? "approve this style" : "save this draft")); }
    finally { setBusy(false); }
  }
  async function removeDraft(item: StyleDraft) {
    if (!window.confirm(`Delete the draft "${item.name}"?`)) return;
    setBusy(true); setError("");
    const snapshot = data;
    setData(current => ({ ...current, drafts: current.drafts.filter(draftItem => draftItem.id !== item.id) }));
    try { await api.deleteStyleDraft(item.id); if (draft?.id === item.id) setDraft(null); await refresh(); }
    catch (e: any) { setData(snapshot); setError(friendlyError(e, "delete this draft")); }
    finally { setBusy(false); }
  }
  async function removeProfile(item: StyleProfile) {
    if (!window.confirm(`Remove "${item.name} · v${item.version}" from the active style library? Existing jobs will keep their pinned version.`)) return;
    setBusy(true); setError("");
    const snapshot = data;
    setData(current => ({ ...current, profiles: current.profiles.filter(profile => profile.style_id !== item.style_id || profile.version !== item.version) }));
    try { await api.deleteStyleProfile(item.style_id, item.version); await refresh(); }
    catch (e: any) { setData(snapshot); setError(friendlyError(e, "remove this style")); }
    finally { setBusy(false); }
  }
  async function forkProfile(item: StyleProfile) {
    setBusy(true); setError("");
    try { const next = await api.forkStyleProfile(item.style_id, item.version); await refresh(); openDraft(next); }
    catch (e) { setError(friendlyError(e, "create the next style version")); }
    finally { setBusy(false); }
  }
  return <div>
    <h1>Styles & Fonts Library</h1>
    <p className="muted" style={{ marginBottom: 24 }}>Import and review reusable visual styles and fonts. Only approved items appear on New Reel.</p>
    {loading && <LoadingState label="Loading styles and drafts…" />}
    {busy && <p className="muted" role="status">Updating style library…</p>}

    <section className="card">
      <h2>Import a Style</h2>
      <div className="row" style={{ gap: 16, marginBottom: 12 }}>
        <label>Import type <select value={kind} onChange={e => { setKind(e.target.value); setFiles([]); }}>
          <option value="snapshots">Snapshots</option><option value="video">Reference video</option><option value="file">Style file (YAML / JSON)</option>
        </select></label>
        <label>Draft name <input value={name} onChange={e => setName(e.target.value)} placeholder="Optional" /></label>
      </div>
      <div style={{
        padding: "16px", background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border)", marginBottom: 12
      }}>
        <input type="file" aria-label="Files for new style draft" multiple={kind === "snapshots"}
          accept={kind === "snapshots" ? "image/*" : kind === "video" ? "video/*" : ".yaml,.yml,.json,text/yaml,application/json"}
          onChange={e => setFiles(Array.from(e.target.files || []))} />
        {files.length > 0 && <p className="muted" style={{ marginTop: 6 }}>{files.map(f => f.name).join(", ")}</p>}
      </div>
      <button disabled={busy || !files.length} title={(busy || !files.length) ? "Add a file first." : undefined} onClick={importStyle}>
        {busy ? "Analyzing..." : "Create editable draft"}
      </button>
    </section>

    {draft && <section className="card" style={{ borderLeft: "3px solid var(--accent)" }}>
      <h2>Review Draft &middot; {draft.source.type}</h2>
      <label style={{ display: "block", marginBottom: 8 }}>Style name <input value={name} onChange={e => setName(e.target.value)} style={{ width: "100%" }} /></label>
      <p className="muted">Source: {draft.source.source_name || draft.source.type} &middot; {draft.source.sha256 || draft.source.sha256?.join(", ")}</p>
      {draft.source.original && <details style={{ margin: "8px 0" }}><summary style={{ cursor: "pointer", color: "var(--text-secondary)", fontSize: 13 }}>Imported style file contents</summary>
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, padding: 12, background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)", marginTop: 8 }}>{JSON.stringify(draft.source.original, null, 2)}</pre>
      </details>}
      <div className="row" style={{ overflowX: "auto", gap: 8, margin: "12px 0" }}>
        {draft.evidence.map((ev: any, i: number) => ev.asset && <figure key={i} style={{ margin: 0, minWidth: 150 }}>
          <AuthenticatedMedia as="img" src={api.styleEvidenceUrl(ev.asset)} alt={`Evidence ${i + 1}`} style={{
            height: 145, maxWidth: 250, objectFit: "contain", background: "var(--bg-deep)",
            borderRadius: "var(--radius-sm)", border: "1px solid var(--border)"
          }} />
          <figcaption className="muted" style={{ fontSize: 11, marginTop: 4 }}>{ev.at_seconds != null ? `${ev.at_seconds}s · ` : ""}{(ev.supports || []).join(", ")}</figcaption>
        </figure>)}
      </div>
      {draft.profile.learned?.timing?.status === "unknown" && <p className="muted">Timing: unknown from still images.</p>}
      {draft.profile.learned?.motion?.status === "unknown" && <p className="muted">Motion: unknown from still images.</p>}
      <label style={{ display: "block", marginTop: 14 }}>Editable profile JSON
        <textarea rows={18} value={profileText} onChange={e => setProfileText(e.target.value)} style={{ width: "100%" }} />
      </label>
      <div className="row" style={{ marginTop: 12 }}>
        <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} className="secondary" onClick={() => saveDraft(false)}>Save draft</button>
        <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={() => saveDraft(true)}>Approve version</button>
      </div>
    </section>}

    <section className="card">
      <h2>Approved Styles</h2>
      {!loading && data.profiles.length === 0 && <EmptyState title="No approved styles yet" description="Import a style above, review the draft, then approve it for new reels." />}
      {data.profiles.map(p => <div key={`${p.style_id}-${p.version}`} style={{
        padding: "12px 16px", background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)",
        border: "1px solid var(--border)", marginBottom: 8
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div>
            <b>{p.name} &middot; v{p.version}</b>
            <span className="muted" style={{ marginLeft: 8 }}>approved &middot; {p.source.type}</span>
          </div>
        </div>
        <div className="row">
          <button className="secondary" disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} style={{ fontSize: 12 }} onClick={() => void forkProfile(p)}>Create next version</button>
          <button className="danger-sm" disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={() => void removeProfile(p)}>Remove</button>
        </div>
        <details style={{ marginTop: 8 }}><summary style={{ cursor: "pointer", color: "var(--text-secondary)", fontSize: 12 }}>Profile and provenance</summary>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, padding: 10, background: "var(--bg-deep)", borderRadius: "var(--radius-sm)", marginTop: 6 }}>{JSON.stringify({ source: p.source, evidence: p.evidence, profile: p.profile }, null, 2)}</pre>
        </details>
      </div>)}
    </section>

    <section className="card">
      <h2>Drafts</h2>
      {!loading && data.drafts.filter(d => d.state === "draft").length === 0 && <EmptyState title="No pending drafts" description="Import images, a video, or a style file above to create one." />}
      {data.drafts.filter(d => d.state === "draft").map(d => <div className="row" key={d.id} style={{ marginBottom: 8 }}>
        <button className="secondary" onClick={() => openDraft(d)}>{d.name} &middot; {d.source.type}</button>
        <button className="danger-sm" disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={() => void removeDraft(d)}>Remove</button>
      </div>)}
    </section>

    <section id="fonts" className="card">
      <FontLibrary selectable={false} manage />
    </section>

    {error && <div className="errors" role="alert" style={{ marginTop: 16 }}>{error} <button className="secondary" onClick={() => void refresh().then(() => setError("")).catch(e => setError(friendlyError(e, "load the style library")))}>Try again</button></div>}
  </div>;
}
