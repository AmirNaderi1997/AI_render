import React from "react";
import { api, PremiereMode, PremiereStatus } from "./api";
import { friendlyError } from "./ui";

export function PremiereCard({ id, savePlan, renderDone = false }: { id: string; savePlan?: () => Promise<boolean>; renderDone?: boolean }) {
  const [state, setState] = React.useState<PremiereStatus | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [message, setMessage] = React.useState("");
  const [statusError, setStatusError] = React.useState("");
  const [pairingCode, setPairingCode] = React.useState("");
  const [steps, setSteps] = React.useState<string[] | null>(null);
  const [downloadProgress, setDownloadProgress] = React.useState<number | null>(null);
  const [downloading, setDownloading] = React.useState(false);
  const [downloaded, setDownloaded] = React.useState(false);
  const polling = React.useRef(false);
  const refresh = React.useCallback(async () => {
    if (polling.current) return;
    polling.current = true;
    try {
      const next = await api.premiereStatus(id);
      setState(next);
      setStatusError("");
      if (next.bridge && next.bridge.state !== "waiting_for_premiere") setPairingCode("");
    } catch (e) { setStatusError(friendlyError(e, "refresh Premiere status")); }
    finally { polling.current = false; }
  }, [id]);
  React.useEffect(() => { void refresh(); }, [refresh]);
  React.useEffect(() => {
    const bridgeActive = state?.bridge && ["waiting_for_premiere", "paired"].includes(state.bridge.state);
    if (!bridgeActive && !pairingCode) return;
    const timer = window.setInterval(() => void refresh(), 1500);
    return () => window.clearInterval(timer);
  }, [refresh, state?.bridge?.state, pairingCode]);

  async function act(mode: PremiereMode) {
    setBusy(true); setMessage(""); setSteps(null);
    try {
      if (savePlan && !(await savePlan())) return;
      let confirmPreview = false;
      if ((mode === "rendered_video" || mode === "plan_and_render") && state?.final_render === "preview_only") {
        confirmPreview = window.confirm("Only a preview is available. Send this labeled preview to Premiere?");
        if (!confirmPreview) return;
      }
      const response = await api.openPremiere(id, mode, confirmPreview) as any;
      setMessage(response.message);
      if (response.steps) setSteps(response.steps);
      await refresh();
    } catch (e) { setMessage(friendlyError(e, "open the item in Premiere")); }
    finally { setBusy(false); }
  }

  async function link() {
    setBusy(true); setMessage("");
    try {
      if (savePlan && !(await savePlan())) return;
      const response = await api.linkPremiereProject(id);
      if (response.status === "setup_started") {
        setMessage(response.message ?? "Premiere project setup has started.");
      } else {
        setMessage(`Linked ${response.project_name}. Later AI Render edits are not added to it automatically.`);
      }
      await refresh();
    } catch (e) { setMessage(friendlyError(e, "link the Premiere project")); }
    finally { setBusy(false); }
  }

  async function connectBridge(forceRefresh = false) {
    setBusy(true); setMessage(""); setPairingCode("");
    try {
      if (savePlan && !(await savePlan())) return;
      const response = await api.startPremiereBridge(id, forceRefresh);
      setPairingCode(response.pairing_code);

      // NOTE: The CEP panel inside Premiere has its own CEF browser with a separate
      // origin — it reads the backend port from its own index.html port input field,
      // not from this web UI's localStorage.

      setMessage("Open Window → Extensions → AI Render Bridge in Premiere and enter this one-time code. The code expires in 15 minutes and can only be used once.");
      await refresh();
    } catch (e) { setMessage(friendlyError(e, "connect to Premiere")); }
    finally { setBusy(false); }
  }

  async function transfer(url: string, filename: string, open = false) {
    setBusy(true); setMessage("");
    if (filename.endsWith(".zip")) { setDownloaded(false); setDownloadProgress(null); setDownloading(true); }
    try {
      await api.downloadAuthenticated(url, filename, open,
        filename.endsWith(".zip") ? setDownloadProgress : undefined);
      if (filename.endsWith(".zip")) setDownloaded(true);
    }
    catch (e) { setMessage(friendlyError(e, "download this Premiere file")); }
    finally { setBusy(false); setDownloading(false); }
  }

  const local = !!state?.capability.local_launch_supported;
  const app = state?.available ?? !!state?.capability.available;
  const renderReady = state?.final_render === "final" || state?.final_render === "preview_only";
  const renderLabel = state?.final_render === "preview_only" ? "Preview only — confirmation required" : state?.final_render;
  return <section className="card" dir="auto" aria-label="Premiere Pro desktop integration">
    <h2>Premiere Pro</h2>
    {!state && !statusError && <p className="muted" role="status">Checking Premiere availability…</p>}
    {busy && <p className="muted" role="status">Working with Premiere…</p>}
    <p>{!state ? <>Version: <b>checking</b></> : app ? <>Version: <b>{state.capability.version}</b></> : <b>Premiere Pro not detected — XML/ZIP export still works</b>} · Editable plan (FCP7 XML): <b>{state?.editable_plan || "checking"}</b> · Final render: <b>{renderLabel || "checking"}</b> · Saved .prproj: <b>{state?.saved_project || "checking"}</b></p>
    <p>Premiere control bridge: <b>{state?.bridge?.state === "completed" ? "Receipt completed — inspect Timeline in Premiere" : state?.bridge?.state || "checking"}</b></p>
    {!local && <p className="errors">Desktop launch requires the local AI Render backend. Download and import manually. / باز کردن پریمیر فقط روی همین دستگاه ممکن است.</p>}
    {state?.project_state === "not_linked" && <div className="muted">
      <p>Create a clean Premiere project dedicated to this AI Render job. Import in this order:</p>
      <ol><li>project_premiere.xml</li><li>{state.render_name || "final MP4"} as <b>AI Render — Rendered Reference</b></li><li>premiere_captions.srt, then place it on the imported sequence as a caption track</li></ol>
      <p>Save as <b>ai-render-{id}-clean.prproj</b>. Premiere import and caption placement are manual; AI Render will not claim setup is automatic.</p>
    </div>}
    {state?.project_state === "linked_outdated" && <div className="errors">
      <p>Linked project is outdated. What changed:</p>
      <ul>{Object.entries(state.changed_hashes || {}).map(([key, values]) => {
        const label: Record<string, string> = { plan_sha256: "Edit plan", xml_sha256: "Premiere XML", srt_sha256: "Captions", render_sha256: "Rendered video" };
        const changed = !values.linked ? "(new)" : !values.current ? "(removed)" : "updated";
        return <li key={key}>{label[key] || key}: {changed}</li>;
      })}</ul>
      <p>Updated files: {state.xml_name}, {state.render_name || "render missing"}, {state.srt_name}. Reveal files, replace/import them explicitly in Premiere, save there, and link again.</p>
    </div>}
    {!!state?.warnings.length && <ul>{state.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}
    {state?.bridge?.receipt?.music && <p className="muted">Music: {state.bridge.receipt.music.imported ? "imported" : "not imported"}{state.bridge.receipt.music.placed_on_timeline ? " · on timeline" : ""} · {state.bridge.receipt.music.media_path?.split("/").pop()}</p>}
    {state?.bridge?.state === "partial" && <p className="errors">Premiere completed only part of the operation. {(state.bridge.receipt?.warnings || []).join(" ")} {(state.bridge.receipt?.verification?.false_required_observations || []).join(", ")}</p>}
    {state?.bridge?.receipt?.caption_api_available === false && state?.bridge?.state && state.bridge.state !== "not_connected" && <p className="errors">Premiere's createCaptionTrack API is not available. Import premiere_captions.srt manually: drag it from the AI Render bin onto a Caption track in the Timeline.</p>}
    {state?.bridge?.state === "failed" && <p className="errors">Premiere bridge failed. {(state.bridge.receipt?.errors || []).join(" ")}</p>}
    {state?.bridge?.state === "stale" && <p className="errors">The last Premiere confirmation is stale because the project or AI Render artifacts changed. Connect again to verify the current state.</p>}
    {state?.project_state === "linked_outdated" && <p className="errors">Save the updated XML, render, and captions in Premiere, then click “Link clean Premiere project” again. The bridge stays unavailable until the saved project is relinked.</p>}
    {pairingCode && <div className="premiere-pairing" role="status">
      <p>One-time Premiere pairing code:</p><strong>{pairingCode}</strong>
      <p className="muted">Expires in fifteen minutes and can be used once.</p>
    </div>}
    <div className="premiere-actions">
      <button disabled={busy || !local || !app || state?.project_state !== "linked_current" || !renderReady} title={(busy || !local || !app || state?.project_state !== "linked_current" || !renderReady) ? "Premiere must be available locally with the required project files." : undefined} onClick={() => void connectBridge()}>Connect inside Premiere</button>
      <button disabled={busy || !local || !app || state?.editable_plan === "missing"} title={(busy || !local || !app || state?.editable_plan === "missing") ? "Premiere must be available locally with the required project files." : undefined} onClick={() => void act("editable_plan")}>Open editable plan in Premiere</button>
      <button disabled={busy || !local || !app || !renderReady} title={(busy || !local || !app || !renderReady) ? "Premiere must be available locally with the required project files." : undefined} onClick={() => void act("rendered_video")}>Open rendered video in Premiere</button>
      <button disabled={busy || !local || !app || !renderReady} title={(busy || !local || !app || !renderReady) ? "Premiere must be available locally with the required project files." : undefined} onClick={() => void act("plan_and_render")}>
        {state?.project_state === "not_linked" ? "Set up Premiere project (manual)" : state?.project_state === "linked_outdated" ? "Reveal updated files in Finder" : "Open linked Premiere project"}
      </button>
      <button className="secondary" disabled={busy || !local || state?.editable_plan === "missing"} title={(busy || !local || state?.editable_plan === "missing") ? "Premiere must be available locally with the required project files." : undefined} onClick={() => void act("reveal")}>Reveal import files</button>
      <button className="secondary" disabled={busy || !local || state?.editable_plan === "missing"} title={(busy || !local || state?.editable_plan === "missing") ? "Premiere must be available locally with the required project files." : undefined} onClick={() => void link()}>Link clean Premiere project</button>
    </div>
    {steps && <ol className="muted">{steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
    {message && <p role="status" dir="auto">{message}</p>}
    {statusError && <p role="alert" className="errors">{statusError} <button className="secondary" onClick={() => void refresh()}>Try again</button></p>}
    <p className="muted">The bridge controls and verifies Premiere from inside the app. The other Open/Reveal buttons are macOS file handoffs only and never claim Timeline or caption success.</p>
    {renderDone && <div className="premiere-export">
      <p>Includes: Video + Audio + Narration + Music + Captions (when present in this job).</p>
      <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={() => void transfer(api.premiereUrl(id), `ai-render-${id}-premiere.zip`)}>Export to Premiere Pro · Download ZIP</button>
      {downloading && <progress aria-label="Premiere ZIP download progress" value={downloadProgress ?? undefined} max={100} />}
      {downloading && <span role="status">{downloadProgress === null ? "Downloading…" : `Downloading ${downloadProgress}%`}</span>}
      {downloaded && <p role="status">Download started. Unzip → In Premiere Pro, create a project and import project_premiere.xml (File → Import). Then import premiere_captions.srt and save the project as .prproj.</p>}
    </div>}
    <div className="premiere-actions">
      <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={() => void transfer(api.premiereXmlUrl(id), "project_premiere.xml")}>Download XML</button>
      <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={() => void transfer(api.premiereCaptionsUrl(id), "premiere_captions.srt")}>Download SRT</button>
      <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={() => void transfer(api.premiereReportUrl(id), "premiere_transition_report.json", true)}>Compatibility report</button>
    </div>
    <details className="premiere-guide" dir="rtl">
      <summary>راهنمای قدم‌به‌قدم اتصال به پریمیر</summary>
      <div className="guide-content">
        <h3>۱. آماده‌سازی اولیه (فقط یک‌بار)</h3>
        <ol>
          <li>مطمئن شوید Adobe Premiere Pro 2025 (نسخه ۲۵) نصب است.</li>
          <li>در ترمینال دستور زیر را بزنید تا افزونه‌های بدون امضا فعال شوند:
            <code dir="ltr">defaults write com.adobe.CSXS.12 PlayerDebugMode 1</code>
          </li>
          <li>پوشه <code dir="ltr">premiere-bridge</code> را به مسیر افزونه‌ها لینک کنید:
            <code dir="ltr">ln -s "$(pwd)/premiere-bridge" "$HOME/Library/Application Support/Adobe/CEP/extensions/ir.airender.premiere.bridge"</code>
          </li>
          <li>پریمیر را ری‌استارت کنید.</li>
        </ol>

        <h3>۲. ساخت پروژه پریمیر</h3>
        <ol>
          <li>یک پروژه خالی در پریمیر بسازید و فایل XML را از پوشه جاب با File → Import وارد کنید.</li>
          <li>در پریمیر فایل MP4 رندر شده را ایمپورت کنید و نام آن را به <b dir="ltr">AI Render — Rendered Reference</b> تغییر دهید.</li>
          <li>فایل <b dir="ltr">premiere_captions.srt</b> را ایمپورت کنید و روی تایم‌لاین به‌عنوان Caption Track بکشید.</li>
          <li>پروژه را با نام <b dir="ltr">ai-render-{id}-clean.prproj</b> در پوشه جاب ذخیره کنید.</li>
          <li>دوباره دکمه <b>«Link clean Premiere project»</b> را بزنید تا پروژه لینک شود.</li>
        </ol>

        <h3>۳. اتصال Bridge (کنترل از راه دور)</h3>
        <ol>
          <li>دکمه <b>«Connect inside Premiere»</b> را بزنید. یک کد جفت‌سازی نمایش داده می‌شود.</li>
          <li>در پریمیر به <b dir="ltr">Window → Extensions → AI Render Bridge</b> بروید.</li>
          <li>کد را وارد کنید. نتیجه وارد کردن سکانس، ویدیو و زیرنویس را در پنل و تایم‌لاین بررسی کنید.</li>
        </ol>

        <h3>۴. دکمه‌های دیگر</h3>
        <ul>
          <li><b>Open editable plan in Premiere</b> — فایل XML ادیت‌پلن را در پریمیر باز می‌کند.</li>
          <li><b>Open rendered video in Premiere</b> — ویدیوی رندر شده را در پریمیر باز می‌کند.</li>
          <li><b>Open linked Premiere project</b> — پروژه لینک‌شده را مستقیماً باز می‌کند.</li>
          <li><b>Reveal import files</b> — پوشه فایل‌ها را در Finder نشان می‌دهد.</li>
          <li><b>Download ZIP / XML / SRT</b> — فایل‌ها را مستقیماً دانلود می‌کند.</li>
        </ul>

        <h3>۵. اگر زیرنویس خودکار کار نکرد</h3>
        <p>اگر پیام <b dir="ltr">createCaptionTrack API is not available</b> نمایش داده شد، فایل SRT را دستی ایمپورت کنید: از پوشه AI Render روی یک Caption Track در تایم‌لاین بکشید.</p>

        <h3>۶. به‌روزرسانی پروژه</h3>
        <p>اگر پلن یا رندر تغییر کرد، فایل‌های جدید را در پریمیر وارد و پروژه را ذخیره کنید. سپس دوباره <b>«Link clean Premiere project»</b> را بزنید.</p>
      </div>
    </details>
  </section>;
}
