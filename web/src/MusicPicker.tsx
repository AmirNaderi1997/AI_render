import React from "react";
import { api, LibraryAsset } from "./api";
import { AuthenticatedMedia } from "./AuthenticatedMedia";
import { friendlyError } from "./ui";

export function MusicPicker({ jobId, file, onSelect }: {
  jobId: string;
  file?: string;
  onSelect: (file: string) => void;
}) {
  const [tracks, setTracks] = React.useState<LibraryAsset[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [loadingTracks, setLoadingTracks] = React.useState(true);
  const [error, setError] = React.useState("");
  const [prompt, setPrompt] = React.useState("");
  React.useEffect(() => {
    api.getLibrary().then(data => setTracks(data.assets.filter(asset => asset.category === "music")))
      .catch(e => setError(friendlyError(e, "load the music library")))
      .finally(() => setLoadingTracks(false));
  }, []);
  const selected = tracks.find(track => track.path === file || file?.endsWith(`/${track.path}`));
  const preview = selected ? api.libraryPreviewUrl("music", selected.filename)
    : file?.startsWith("music/") ? api.musicPreviewUrl(jobId, file.slice(6)) : undefined;

  async function upload(file: File) {
    setBusy(true);
    setError("");
    try {
      const result = await api.uploadMusic(jobId, file);
      onSelect(result.path);
    } catch (e: any) {
      setError(friendlyError(e, "upload the music"));
    } finally { setBusy(false); }
  }

  async function choose(path: string) {
    const track = tracks.find(track => track.path === path);
    if (!track) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.importLibraryMusic(jobId, track.filename);
      onSelect(result.path);
    } catch (e: any) {
      setError(friendlyError(e, "select the music"));
    } finally { setBusy(false); }
  }

  async function generate() {
    if (!prompt.trim()) { setError("Describe the music first."); return; }
    setBusy(true);
    setError("");
    try {
      const result = await api.generateMusic(jobId, prompt.trim());
      onSelect(result.path);
    } catch (e: any) {
      setError(friendlyError(e, "generate the music"));
    } finally { setBusy(false); }
  }

  return <div style={{ marginBottom: 12 }}>
    <div className="row" style={{ gap: 12 }}>
      <label>Music library / کتابخانه موسیقی
        <select aria-label="Music library" value={selected?.path || ""} disabled={busy || loadingTracks}
          onChange={e => { if (e.target.value) void choose(e.target.value); }}>
          <option value="">{loadingTracks ? "Loading tracks…" : "Choose a background track"}</option>
          {tracks.map(track => <option key={track.path} value={track.path}>{track.filename}</option>)}
        </select>
      </label>
      <label>Upload music / بارگذاری موسیقی
        <input type="file" accept=".mp3,.wav,.ogg,.aac,.m4a" disabled={busy}
          onChange={e => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ""; }} />
      </label>
    </div>
    <div className="row" style={{ gap: 12, alignItems: "end", marginTop: 10 }}>
      <label style={{ flex: 1 }}>Generate music with Sarovi / ساخت موسیقی با ساروی
        <input type="text" value={prompt} maxLength={4000} disabled={busy}
          placeholder="Calm instrumental piano, slow tempo, hopeful mood, no vocals"
          onChange={e => setPrompt(e.target.value)} />
      </label>
      <button type="button" disabled={busy || !prompt.trim()} title={(busy || !prompt.trim()) ? "Enter a prompt first." : undefined} onClick={() => void generate()}>
        Generate 30-second clip
      </button>
    </div>
    {busy && <p className="muted" role="status">Preparing music…</p>}
    {!loadingTracks && !tracks.length && <p className="muted">No saved tracks yet. Upload a file or generate a clip below.</p>}
    {preview && <AuthenticatedMedia as="audio" controls src={preview} style={{ width: "100%", marginTop: 8 }} />}
    <p className="muted">Save and render a preview to hear the music mixed with the video. Voiceover stays on its own track.</p>
    {error && <div className="errors" role="alert">{error}</div>}
  </div>;
}
