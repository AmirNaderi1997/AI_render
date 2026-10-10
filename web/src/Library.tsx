import React from "react";
import { api, LibraryAsset, LibraryData } from "./api";
import { AuthenticatedMedia } from "./AuthenticatedMedia";
import { LoadingState, friendlyError } from "./ui";

type Category = "broll" | "music" | "sfx";
const CATEGORIES: Category[] = ["broll", "music", "sfx"];
const CATEGORY_LABELS: Record<Category, string> = {
  broll: "B-Roll / ب‌رول",
  music: "Music / موزیک",
  sfx: "SFX / افکت صوتی",
};

export default function Library() {
  const [data, setData] = React.useState<LibraryData | null>(null);
  const [activeTab, setActiveTab] = React.useState<Category>("broll");
  const [uploading, setUploading] = React.useState(false);
  const [rescanning, setRescanning] = React.useState(false);
  const [mutating, setMutating] = React.useState(false);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [editAsset, setEditAsset] = React.useState<LibraryAsset | null>(null);
  const [editTags, setEditTags] = React.useState("");
  const [editMood, setEditMood] = React.useState("");
  const [editEnergy, setEditEnergy] = React.useState<number | "">("");
  const [editDesc, setEditDesc] = React.useState("");

  // Upload form state
  const [uploadTags, setUploadTags] = React.useState("");
  const [uploadMood, setUploadMood] = React.useState("");
  const [uploadEnergy, setUploadEnergy] = React.useState<number | "">("");
  const [uploadDesc, setUploadDesc] = React.useState("");

  const fileRef = React.useRef<HTMLInputElement>(null);
  const modalRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!editAsset) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const handleKeys = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setEditAsset(null); return; }
      if (event.key !== "Tab" || !modalRef.current) return;
      const controls = Array.from(modalRef.current.querySelectorAll<HTMLElement>("input:not([disabled]), button:not([disabled])"));
      if (!controls.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeys);
    return () => { document.removeEventListener("keydown", handleKeys); previousFocus?.focus(); };
  }, [editAsset]);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.getLibrary();
      setData(d);
      setError("");
    } catch (e: any) {
      setError(friendlyError(e, "load the asset library"));
    } finally { setLoading(false); }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const filtered = React.useMemo(() =>
    data?.assets.filter(a => a.category === activeTab) ?? [],
  [data, activeTab]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files?.length) return;
    setUploading(true);
    setError("");
    try {
      for (const file of Array.from(files)) {
        await api.uploadLibraryAsset(file, activeTab, uploadTags,
          uploadMood || undefined, uploadEnergy || undefined,
          uploadDesc || undefined);
      }
      setUploadTags(""); setUploadMood(""); setUploadEnergy(""); setUploadDesc("");
      await load();
    } catch (e: any) {
      setError(friendlyError(e, "upload these assets"));
    }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  async function handleRescan() {
    setRescanning(true);
    try {
      await api.rescanLibrary();
      await load();
    } catch (e: any) {
      setError(friendlyError(e, "rescan the asset folders"));
    }
    setRescanning(false);
  }

  async function handleDelete(asset: LibraryAsset) {
    if (!confirm(`Delete ${asset.filename}?`)) return;
    setMutating(true);
    const snapshot = data;
    setData(current => current ? { ...current, counts: { ...current.counts, [asset.category]: Math.max(0, current.counts[asset.category] - 1) }, assets: current.assets.filter(item => !(item.category === asset.category && item.filename === asset.filename)) } : current);
    try {
      await api.deleteLibraryAsset(asset.category, asset.filename);
      await load();
    } catch (e: any) {
      setData(snapshot);
      setError(friendlyError(e, "delete this asset"));
    } finally { setMutating(false); }
  }

  function openEdit(asset: LibraryAsset) {
    setEditAsset(asset);
    setEditTags(asset.tags.join(", "));
    setEditMood(asset.mood || "");
    setEditEnergy(asset.energy ?? "");
    setEditDesc(asset.description || "");
  }

  async function saveEdit() {
    if (!editAsset) return;
    setMutating(true);
    try {
      await api.updateLibraryAsset(editAsset.category, editAsset.filename, {
        tags: editTags.split(",").map(t => t.trim()).filter(Boolean),
        mood: editMood || undefined,
        energy: editEnergy ? Number(editEnergy) : undefined,
        description: editDesc || undefined,
      });
      setEditAsset(null);
      await load();
    } catch (e: any) {
      setError(friendlyError(e, "save these asset details"));
    } finally { setMutating(false); }
  }

  if (!data) return loading ? <LoadingState label="Loading asset library…" /> : <div className="errors" role="alert">{error} <button className="secondary" onClick={() => void load()}>Try again</button></div>;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <h1 style={{ margin: 0 }}>Asset Library / <span dir="rtl" lang="fa">کتابخانه</span></h1>
        <button onClick={handleRescan} disabled={rescanning || loading || mutating || uploading} title={rescanning ? "Rescan in progress" : loading || mutating || uploading ? "Wait for the current library operation" : undefined}
          className="btn-secondary" style={{ marginLeft: "auto" }}>
          {rescanning ? "Rescanning..." : "Rescan folders"}
        </button>
      </div>

      {error && <div className="error-box" role="alert">{error} <button className="secondary" onClick={() => { setError(""); void load(); }}>Retry loading</button></div>}
      {loading && <LoadingState label="Refreshing asset library…" rows={1} />}
      {mutating && <p className="muted" role="status">Updating asset library…</p>}

      {/* Category counts */}
      <div className="library-counts">
        {CATEGORIES.map(cat => (
          <button key={cat}
            className={`library-tab ${activeTab === cat ? "active" : ""}`}
            aria-pressed={activeTab === cat} onClick={() => setActiveTab(cat)}>
            <span className="library-tab-label" dir="auto">{CATEGORY_LABELS[cat]}</span>
            <span className="library-tab-count" dir="ltr">{data.counts[cat]}</span>
          </button>
        ))}
      </div>

      {/* Upload area */}
      <div className="library-upload-area">
        <div className="library-upload-fields">
          <input aria-label="Asset tags" placeholder="Tags (comma-separated)" value={uploadTags}
            onChange={e => setUploadTags(e.target.value)} />
          <input aria-label="Asset mood" placeholder="Mood (e.g. happy, tense)" value={uploadMood}
            onChange={e => setUploadMood(e.target.value)} />
          <input aria-label="Asset energy from 1 to 5" type="number" placeholder="Energy 1-5" min={1} max={5}
            value={uploadEnergy} onChange={e => setUploadEnergy(e.target.value ? Number(e.target.value) : "")} />
          <input aria-label="Asset description" placeholder="Description" value={uploadDesc}
            onChange={e => setUploadDesc(e.target.value)} />
        </div>
        <label className="btn-primary upload-btn" role="button" tabIndex={uploading ? -1 : 0} aria-disabled={uploading} title={uploading ? "Upload in progress" : undefined}
          aria-label={`Upload ${CATEGORY_LABELS[activeTab].split(" /")[0]} assets`}
          onKeyDown={e => { if (!uploading && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); fileRef.current?.click(); } }}>
          {uploading ? "Uploading..." : `Upload ${CATEGORY_LABELS[activeTab].split(" /")[0]}`}
          <input ref={fileRef} type="file" multiple hidden tabIndex={-1} onChange={handleUpload} disabled={uploading} aria-label="Choose library assets to upload"
            accept={activeTab === "broll" ? "video/*,image/*" : "audio/*"} />
        </label>
      </div>

      {/* Asset grid */}
      {filtered.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">
            {activeTab === "broll" ? "🎬" : activeTab === "music" ? "🎵" : "🔊"}
          </div>
          <strong>No {activeTab} assets yet</strong>
          <p>Use the upload control above to add your first {activeTab} file.</p>
        </div>
      ) : (
        <div className="library-grid">
          {filtered.map(asset => (
            <div key={asset.filename} className="library-card">
              <div className="library-card-preview">
                {activeTab === "broll" ? (
                  <AuthenticatedMedia as="video" src={api.libraryPreviewUrl(asset.category, asset.filename)}
                    muted preload="metadata"
                    onMouseOver={(e: React.MouseEvent<HTMLVideoElement>) => e.currentTarget.play()}
                    onMouseOut={(e: React.MouseEvent<HTMLVideoElement>) => { e.currentTarget.pause(); e.currentTarget.currentTime = 0; }}
                    style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                ) : (
                  <AuthenticatedMedia as="audio" src={api.libraryPreviewUrl(asset.category, asset.filename)}
                    controls preload="metadata" style={{ width: "100%" }} />
                )}
              </div>
              <div className="library-card-body">
                <div className="library-card-name" title={asset.filename} dir="auto">
                  {asset.filename}
                </div>
                {asset.duration_sec != null && (
                  <span className="library-card-meta">{asset.duration_sec.toFixed(1)}s</span>
                )}
                {asset.tags.length > 0 && (
                  <div className="library-card-tags">
                    {asset.tags.map(t => <span key={t} className="tag">{t}</span>)}
                  </div>
                )}
                {asset.mood && <span className="tag tag-mood">{asset.mood}</span>}
                {asset.energy && <span className="tag tag-energy">E{asset.energy}</span>}
                <div className="library-card-actions">
                  <button className="btn-sm" onClick={() => openEdit(asset)} disabled={mutating} title={mutating ? "Wait for the current library operation" : undefined}>Edit tags</button>
                  <button className="btn-sm btn-danger" onClick={() => handleDelete(asset)} disabled={mutating} title={mutating ? "Wait for the current library operation" : undefined}>Delete</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Edit modal */}
      {editAsset && (
        <div className="modal-overlay" onClick={() => setEditAsset(null)} onKeyDown={e => { if (e.key === "Escape") setEditAsset(null); }}>
          <div className="modal" ref={modalRef} role="dialog" aria-modal="true" aria-labelledby="asset-edit-title" onClick={e => e.stopPropagation()}>
            <button type="button" className="modal-close secondary" onClick={() => setEditAsset(null)} aria-label="Close editor">×</button>
            <h3 id="asset-edit-title">Edit: {editAsset.filename}</h3>
            <label htmlFor="asset-edit-tags">Tags (comma-separated)</label>
            <input id="asset-edit-tags" autoFocus value={editTags} onChange={e => setEditTags(e.target.value)} />
            <label htmlFor="asset-edit-mood">Mood</label>
            <input id="asset-edit-mood" value={editMood} onChange={e => setEditMood(e.target.value)} />
            <label htmlFor="asset-edit-energy">Energy (1-5)</label>
            <input id="asset-edit-energy" type="number" min={1} max={5} value={editEnergy}
              onChange={e => setEditEnergy(e.target.value ? Math.max(1, Math.min(5, Number(e.target.value))) : "")} />
            <label htmlFor="asset-edit-description">Description</label>
            <input id="asset-edit-description" value={editDesc} onChange={e => setEditDesc(e.target.value)} />
            <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
              <button className="btn-primary" onClick={saveEdit} disabled={mutating} title={mutating ? "Saving asset details" : undefined}>{mutating ? "Saving…" : "Save"}</button>
              <button className="btn-secondary" onClick={() => setEditAsset(null)} disabled={mutating} title={mutating ? "Saving asset details" : undefined}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
