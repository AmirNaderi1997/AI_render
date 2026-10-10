import React from "react";
import { api, FontEntry, FontLibrary as FontLibraryData } from "./api";
import { useAuthenticatedMediaUrl } from "./AuthenticatedMedia";
import { LoadingState, friendlyError } from "./ui";

type Props = {
  selectedId?: string;
  onSelect?: (font: FontEntry | null) => void;
  onLibraryChange?: () => void;
  selectable?: boolean;
  manage?: boolean;
};

const compareFonts = (left: FontEntry, right: FontEntry) =>
  (left.family || left.metadata?.family || left.name || left.id).localeCompare(
    right.family || right.metadata?.family || right.name || right.id,
    undefined, { numeric: true, sensitivity: "base" },
  ) || (left.metadata?.weight || 400) - (right.metadata?.weight || 400);

const CANDIDATE_RANK: Record<string, number> = { font_file: 0, image_reference: 1, text_reference: 2 };
const candidateRank = (font: FontEntry) => CANDIDATE_RANK[font.kind] ?? 3;

export function FontLibrary({ selectedId, onSelect, onLibraryChange, selectable = true, manage = false }: Props) {
  const [library, setLibrary] = React.useState<FontLibraryData>({ version: 1, candidates: [], approved: [] });
  const [name, setName] = React.useState("");
  const [copiedText, setCopiedText] = React.useState("");
  const [fontName, setFontName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [message, setMessage] = React.useState("");
  const [isError, setIsError] = React.useState(false);

  const refresh = React.useCallback(async () => setLibrary(await api.getFontLibrary()), []);
  React.useEffect(() => { refresh().catch(e => { setMessage(friendlyError(e, "load imported fonts")); setIsError(true); }).finally(() => setLoading(false)); }, [refresh]);
  async function run(action: () => Promise<any>, done: string) {
    setBusy(true); setMessage(""); setIsError(false);
    try { await action(); await refresh(); onLibraryChange?.(); setMessage(done); }
    catch (e: any) { setMessage(friendlyError(e, "update the font library")); setIsError(true); }
    finally { setBusy(false); }
  }

  async function removeFont(font: FontEntry) {
    const label = font.family || font.metadata?.family || font.name || "this font";
    if (!window.confirm(`Remove ${label} from the active font library? Existing jobs will keep their saved font.`)) return;
    await run(async () => {
      await api.deleteFont(font.id);
      if (selectedId === font.id) onSelect?.(null);
    }, `${label} removed. Re-import the same file to restore it.`);
  }

  const candidates = [...library.candidates].sort((a, b) => candidateRank(a) - candidateRank(b) || compareFonts(a, b));
  const approved = library.approved.filter(font => font.kind === "font_file").sort(compareFonts);

  return <section className={manage ? "font-library-manager" : "font-picker"} aria-label="Font Library">
    <div className="library-heading">
      <div><h2>{manage ? "Fonts" : "Imported fonts"}</h2>
        <p className="muted">{manage ? "Import, review, and approve fonts before they appear on New Reel." : "Choose an approved imported font for captions and cover titles."}</p></div>
      {!manage && <a href="/style-library#fonts">Manage fonts</a>}
    </div>
    {manage && <>
      <p className="muted">Text characters alone cannot identify a typeface. For an exact render font, import its TTF or OTF file.</p>
      <div className="font-import-grid">
        <div className="import-option import-option-primary">
          <span className="import-step">1 · Recommended</span><h3>Font files</h3>
          <input aria-label="TTF or OTF font files" type="file" multiple accept=".ttf,.otf,font/ttf,font/otf" disabled={busy}
            onChange={e => { const input = e.currentTarget; const files = Array.from(input.files || []).sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
              if (files.length) void run(async () => { for (const file of files) await api.addFontFile(file); },
                `${files.length} font file${files.length === 1 ? "" : "s"} inspected. Review the samples below.`);
              input.value = ""; }} />
          <p className="muted">Select one or several .ttf/.otf files. Families are sorted automatically after metadata inspection.</p>
        </div>
        <div className="import-option">
          <span className="import-step">2 · Visual reference</span><h3>Image with text</h3>
          <input aria-label="Image containing text" type="file" accept="image/*" disabled={busy}
            onChange={e => { const input = e.currentTarget; const file = input.files?.[0]; if (file) void run(() => api.addFontImage(file), "Image text extracted; font matches are approximate."); input.value = ""; }} />
          <p className="muted">Useful for comparison, but pixels cannot prove a font's exact identity.</p>
        </div>
        <div className="import-option">
          <span className="import-step">3 · Note only</span><h3>Copied text reference</h3>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Reference name" aria-label="Typography reference name" />
          <input value={fontName} onChange={e => setFontName(e.target.value)} placeholder="Font name (if known)" aria-label="Font name" style={{ marginTop: 6 }} />
          <textarea rows={3} value={copiedText} onChange={e => setCopiedText(e.target.value)} placeholder="Paste sample text" aria-label="Copied typography sample" style={{ marginTop: 6 }} />
          <button disabled={busy || !name.trim() || !copiedText.trim()} title={(busy || !name.trim() || !copiedText.trim()) ? "Complete the font name and source text first." : undefined} onClick={() => void run(
            () => api.addFontTextReference({ name, copied_text: copiedText, font_name: fontName }), "Typography reference saved as a candidate.")}>Save reference</button>
        </div>
      </div>
    </>}
    {loading && <LoadingState label="Loading imported fonts…" rows={2} />}
    {busy && <p className="muted" role="status">Updating fonts…</p>}
    {message && <p className={isError ? "errors" : "muted"} role={isError ? "alert" : "status"}>{message} {isError && <button className="secondary" onClick={() => void refresh().then(() => { setMessage(""); setIsError(false); }).catch(e => setMessage(friendlyError(e, "load imported fonts")))}>Try again</button>}</p>}

    {manage && candidates.length > 0 && <>
      <h3>Imported candidates</h3>
      {candidates.map(c => <Candidate key={c.id} candidate={c} busy={busy} onApprove={() => void run(
        () => api.approveFont(c.id), "Font approved and added to New Reel.")} onRemove={() => void removeFont(c)} />)}
    </>}

    <h3>{manage ? "Approved fonts on New Reel" : "Available imported fonts"}</h3>
    {!loading && approved.length === 0 && <p className="muted">No approved imported fonts yet. <a href="/style-library#fonts">Add fonts in Styles &amp; Fonts Library.</a></p>}
    {approved.map(font => <div key={font.id} className={`font-row ${selectedId === font.id ? "font-row-selected" : ""}`}>
      <div className="font-row-title">
        {selectable ? <label><input type="radio" name="selected-caption-font" checked={selectedId === font.id}
          onChange={() => onSelect?.(font)} /> <b>{font.family} · {font.style}</b></label> : <b>{font.family} · {font.style}</b>}
        <button type="button" className="danger-sm" disabled={busy} onClick={() => void removeFont(font)} aria-label={`Remove ${font.family || "font"}`} title="Remove imported font">✕</button>
      </div>
      <span className="muted">{font.metadata?.persian_coverage.supported ? "Persian ✓" : "Persian glyphs missing"} · {font.metadata?.latin_coverage.supported ? "Latin ✓" : "Latin glyphs missing"} · weight {font.metadata?.weight || "—"}</span>
      <SamplePreview font={font} />
    </div>)}
    {selectable && selectedId && <button type="button" className="secondary" onClick={() => onSelect?.(null)}>Use style default</button>}
  </section>;
}

function Candidate({ candidate: c, busy, onApprove, onRemove }: { candidate: FontEntry; busy: boolean; onApprove: () => void; onRemove: () => void }) {
  const family = c.metadata?.family;
  const fontUrl = useAuthenticatedMediaUrl(c.kind === "font_file" && family
    ? api.fontFileUrl(c.id, true) : undefined);
  const fontFace = fontUrl ? `@font-face{font-family:'candidate-${c.id}';src:url('${fontUrl}')}` : "";
  return <div className="font-row">
    <style>{fontFace}</style>
    <div style={{ minWidth: 180, flex: "1 1 260px" }}>
      <div className="font-row-title"><b>{c.name || c.id}</b>
        <button type="button" className="danger-sm" disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={onRemove} aria-label={`Remove ${c.name || "candidate"}`}>✕</button></div>
      <div className="muted">{c.kind.replace(/_/g, " ")} · candidate, not approved</div>
      {c.kind === "font_file" && <>
        <div className="muted">{family} · {c.metadata?.style} · weight {c.metadata?.weight}</div>
        <div className="muted">Persian: {c.metadata?.persian_coverage.supported ? "full checked set" : `missing ${c.metadata?.persian_coverage.missing.slice(0, 8).join(", ")}`}; Latin: {c.metadata?.latin_coverage.supported ? "basic coverage" : "some basic glyphs missing"}</div>
        {c.metadata?.license && <div className="muted">License metadata: {c.metadata.license}</div>}
        <div style={{ fontFamily: `'candidate-${c.id}', sans-serif`, fontSize: 20, direction: "rtl", textAlign: "right", margin: "8px 0" }}>
          <div>فارسی؛ English 123۴۵۶ — نمونه‌ی قلم · regular</div>
          <div style={{ fontWeight: 700 }}>فارسی؛ English 123۴۵۶ — نمونه‌ی قلم · bold</div>
        </div>
        <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={onApprove}>Approve font</button>
      </>}
      {c.kind === "text_reference" && <>
        <div className="muted">Font name: {c.font_name || "not supplied"}</div>
        <div dir="auto">{c.copied_text}</div>
      </>}
      {c.kind === "image_reference" && <>
        <div className="muted">{c.ocr_note}</div><div dir="auto">Extracted text: {c.extracted_text || "No text extracted; you can still inspect the image offline."}</div>
        {(c.font_candidates || []).map((f, i) => <div key={i} className="muted">Approximate candidate: {f.family} — human review required</div>)}
        <p className="muted">No candidate here is an exact identification.</p>
      </>}
    </div>
  </div>;
}

function SamplePreview({ font }: { font: FontEntry }) {
  const family = `approved-${font.id}`;
  const fontUrl = useAuthenticatedMediaUrl(api.fontFileUrl(font.id));
  return <>
    {fontUrl && <style>{`@font-face{font-family:'${family}';src:url('${fontUrl}')}`}</style>}
    <div style={{ width: "100%", fontFamily: `'${family}', sans-serif`, fontSize: 18, direction: "rtl", textAlign: "right" }}>
      <div>فارسی؛ English 123۴۵۶ — regular</div>
      <div style={{ fontWeight: 700 }}>فارسی؛ English 123۴۵۶ — bold</div>
    </div>
  </>;
}
