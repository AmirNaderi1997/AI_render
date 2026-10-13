import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, FontEntry, LibraryAsset, StyleProfile } from "./api";
import { FontLibrary } from "./FontLibrary";
import { StylePicker } from "./StyleLibrary";
import { AuthenticatedMedia } from "./AuthenticatedMedia";
import { friendlyError, JobWorkflow, NextStep, notify } from "./ui";

function fmtSize(n: number) {
  return n >= 1e9 ? (n / 1e9).toFixed(2) + " GB" : (n / 1e6).toFixed(1) + " MB";
}

export default function NewReel() {
  const nav = useNavigate();
  const [searchParams] = useSearchParams();
  const [video, setVideo] = React.useState<File | null>(null);
  const [musicFile, setMusicFile] = React.useState<File | null>(null);
  const [libraryTracks, setLibraryTracks] = React.useState<LibraryAsset[]>([]);
  const [selectedLibraryTrack, setSelectedLibraryTrack] = React.useState("");
  const [playingTrack, setPlayingTrack] = React.useState<string | null>(null);
  const musicAudioRef = React.useRef<HTMLAudioElement>(null);
  const [planFile, setPlanFile] = React.useState<File | null>(null);
  const [planText, setPlanText] = React.useState("");
  const [style, setStyle] = React.useState("rafiei_reel");
  const [styleProfile, setStyleProfile] = React.useState<StyleProfile | null>(null);
  const [planStyleLoading, setPlanStyleLoading] = React.useState(true);
  const [learnedProfile, setLearnedProfile] = React.useState<any>(null);
  const [fonts, setFonts] = React.useState<string[]>([]);
  const [optionsLoading, setOptionsLoading] = React.useState(true);
  const [optionsError, setOptionsError] = React.useState("");
  const [captionFont, setCaptionFont] = React.useState("");
  const [captionFontId, setCaptionFontId] = React.useState("");
  const [instruction, setInstruction] = React.useState("");
  const [outputKind, setOutputKind] = React.useState<"reel" | "story" | "post">("reel");
  const [transitionStyle, setTransitionStyle] =
    React.useState<"auto" | "none" | "crossfade" | "directional">("auto");
  const [transitionRequest, setTransitionRequest] = React.useState("");
  const [language, setLanguage] = React.useState("fa");
  const [whisperModel, setWhisperModel] = React.useState("base");
  const [asrEngine, setAsrEngine] = React.useState("auto");
  const [transcriptionHint, setTranscriptionHint] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [uploadPct, setUploadPct] = React.useState<number | null>(null);
  const [uploadFailed, setUploadFailed] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [videoError, setVideoError] = React.useState("");
  const [over, setOver] = React.useState(false);
  const uploadController = React.useRef<AbortController | null>(null);
  const planJsonError = React.useMemo(() => {
    if (!planText.trim() || planFile) return false;
    try { JSON.parse(planText); return false; } catch { return true; }
  }, [planText, planFile]);

  const inputRef = React.useRef<HTMLInputElement>(null);

  const refreshFonts = React.useCallback(() => {
    api.listFonts().then(setFonts).catch(e => setOptionsError(friendlyError(e, "load available fonts")));
  }, []);
  React.useEffect(() => { refreshFonts(); }, [refreshFonts]);

  React.useEffect(() => {
    api.getLibrary().then(lib => {
      setLibraryTracks(lib.assets.filter(a => a.category === "music"));
    }).catch(e => setOptionsError(friendlyError(e, "load saved music"))).finally(() => setOptionsLoading(false));
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    const requestedStyleId = searchParams.get("style_id");
    const requestedVersion = Number(searchParams.get("style_version"));
    Promise.all([api.getStyleLibrary(), api.getPlanStyleSelection()]).then(([library, saved]) => {
      if (cancelled) return;
      const styleId = requestedStyleId || saved.style_id;
      const version = requestedStyleId ? requestedVersion : saved.version;
      const selected = styleId && version != null
        ? library.profiles.find(p => p.style_id === styleId && p.version === version)
        : null;
      if (selected) setStyleProfile(selected);
      else if (requestedStyleId || saved.style_id) setOptionsError("The saved plan style is no longer available. Choose another approved style or use the learned profile.");
    }).catch(e => { if (!cancelled) setOptionsError(friendlyError(e, "load the saved plan style")); })
      .finally(() => { if (!cancelled) setPlanStyleLoading(false); });
    return () => { cancelled = true; };
  }, [searchParams]);

  React.useEffect(() => {
    api.getLearnedProfile().then(setLearnedProfile)
      .catch(e => setOptionsError(current => current || friendlyError(e, "load the learned style status")));
  }, []);

  React.useEffect(() => {
    const stop = (e: DragEvent) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => { window.removeEventListener("dragover", stop); window.removeEventListener("drop", stop); };
  }, []);


  function pick(f?: File | null) {
    if (!f) return;
    if (!(f.type.startsWith("video/") || /\.(mp4|mov)$/i.test(f.name))) {
      setVideoError(`"${f.name}" is not a video file (.mp4 / .mov).`); return;
    }
    setErr(null); setVideoError(""); setVideo(f);
  }

  async function uploadMusicToJob(jobId: string) {
    if (musicFile) {
      await api.uploadMusic(jobId, musicFile);
    } else if (selectedLibraryTrack) {
      const mediaUrl = await api.authenticatedObjectUrl(api.libraryPreviewUrl("music", selectedLibraryTrack));
      let blob: Blob;
      try { blob = await (await fetch(mediaUrl)).blob(); }
      finally { URL.revokeObjectURL(mediaUrl); }
      const file = new File([blob], selectedLibraryTrack, { type: blob.type });
      await api.uploadMusic(jobId, file);
    }
  }

  async function onCreate() {
    if (!video) { setVideoError("Select a raw video first."); return; }
    setBusy(true); setErr(null); setUploadFailed(false); setUploadPct(0);
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      const plan = planFile ?? (planText.trim() ? planText : undefined);
      let result;
      try {
        result = await api.createJob(video, plan, setUploadPct, controller.signal);
      } catch (e) {
        setUploadFailed(true);
        throw e;
      } finally {
        if (uploadController.current === controller) uploadController.current = null;
        setUploadPct(null);
      }
      const { job, errors } = result;
      if (errors.length) setErr("Plan warnings: " + errors.join("; "));
      await uploadMusicToJob(job.id);
      nav(`/jobs/${job.id}`);
    } catch (e: any) {
      setErr(friendlyError(e, "upload the video and plan"));
    } finally { setBusy(false); }
  }

  async function onGenerate() {
    if (!video) { setVideoError("Select a raw video first."); return; }
    if (planStyleLoading) return;
    setBusy(true); setErr(null); setUploadFailed(false); setUploadPct(0);
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      let result;
      try {
        result = await api.createJob(video, undefined, setUploadPct, controller.signal);
      } catch (e) {
        setUploadFailed(true);
        throw e;
      } finally {
        if (uploadController.current === controller) uploadController.current = null;
        setUploadPct(null);
      }
      const { job } = result;
      // The upload is done, but the plan task has not been requested yet
      // (music upload + generate request + navigation still ahead). Give the
      // user a visible signal for that gap so the screen never looks frozen
      // between "upload 100%" and the "Generating plan…" view.
      notify("Upload complete — starting plan generation…");
      await uploadMusicToJob(job.id);
      await api.generatePlan(job.id, {
        style, instruction: instruction.trim(), whisper_model: whisperModel,
        language: language === "auto" ? null : language,
        transcription_hint: transcriptionHint.trim(),
        asr_engine: asrEngine === "auto" ? undefined : asrEngine,
        caption_font: captionFont || undefined,
        caption_font_id: captionFontId || undefined,
        style_id: styleProfile?.style_id,
        style_version: styleProfile?.version,
        output_kind: outputKind,
        transition_style: transitionStyle,
        transition_request: transitionRequest.trim(),
      });
      nav(`/jobs/${job.id}`);
    } catch (e: any) {
      setErr(friendlyError(e, "start plan generation"));
    } finally { setBusy(false); }
  }

  return (
    <div>
      <h1>New Reel</h1>
      <JobWorkflow current={0} />
      {optionsLoading && <div className="ui-skeleton" role="status" aria-label="Loading fonts and saved music"><span /><span /></div>}
      {optionsError && <p className="errors" role="alert">{optionsError}</p>}
      {video && <NextStep>Choose a style and either generate a plan or upload one below.</NextStep>}

      {/* Step 1 - Video */}
      <div className="card">
        <div className="section-header">
          <h2>Raw Video</h2>
          <span className="muted">Step 1</span>
        </div>
        <label
          htmlFor="vid"
          className={`dropzone ${over ? "over" : ""}`}
          role="button" tabIndex={0} aria-label={video ? `Replace video ${video.name}` : "Choose a raw video"}
          onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); } }}
          style={{ display: "block", cursor: "pointer" }}
          onDragEnter={e => { e.preventDefault(); setOver(true); }}
          onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={e => {
            e.preventDefault(); setOver(false);
            pick(e.dataTransfer.files[0]);
          }}
        >
          {video ? (
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text)", marginBottom: 4 }}>{video.name}</div>
              <div style={{ color: "var(--text-secondary)" }}>{fmtSize(video.size)}</div>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.4 }}>&#128249;</div>
              <div style={{ fontWeight: 500 }}>Drag & drop a video here, or click to browse</div>
              <div className="muted" style={{ marginTop: 4 }}>Supports .mp4 and .mov files</div>
            </div>
          )}
        </label>
        <input id="vid" ref={inputRef} type="file" tabIndex={-1}
          aria-invalid={!!videoError} aria-describedby={videoError ? "video-error" : undefined}
          style={{ position: "absolute", width: 1, height: 1, opacity: 0, overflow: "hidden" }}
          onChange={e => { pick(e.target.files?.[0]); e.target.value = ""; }} />
        {videoError && <p id="video-error" className="errors" role="alert">{videoError}</p>}
      </div>

      {/* Step 2 - Style */}
      <div className="card">
        <div className="section-header">
          <h2>Plan style &amp; speech</h2>
          <span className="muted">Step 2</span>
        </div>
        <div className="row" style={{ gap: 16, marginBottom: 12 }}>
          <label>Preset
            <select value={style} onChange={e => setStyle(e.target.value)}>
              <option value="rafiei_reel">Rafiei Reel Style</option>
            </select>
          </label>
        </div>
        <div style={{ padding: 14, border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", background: "var(--bg-elevated)" }}>
          <StylePicker value={styleProfile} onChange={setStyleProfile} />
          <p className="muted" role="status" style={{ margin: "8px 0 0" }}>
            {styleProfile
              ? `This plan will use ${styleProfile.name} · v${styleProfile.version}. Its pinned style takes priority over your learned reel profile.`
              : learnedProfile?.active && learnedProfile?.enabled
                ? `No imported plan style selected. Your learned profile (${learnedProfile.sample_count} reels) will be applied automatically.`
                : "No imported plan style selected. The Rafiei Reel defaults will be used unless your learned profile is active."}
          </p>
        </div>
        <p className="muted" style={{ marginTop: 8 }}>Choose a one-time override here, or set a default in <a href="/my-effects">My Effects → Plan styles</a>. Manage approved styles in <a href="/style-library">Styles &amp; Fonts Library</a>.</p>

        <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
          <label style={{ display: "block", marginBottom: 12 }}>Caption font
            <select value={captionFontId ? "" : captionFont}
              onChange={e => { setCaptionFont(e.target.value); setCaptionFontId(""); }}>
              <option value="">Style default</option>
              {fonts.map(font => <option key={font} value={font}>{font}</option>)}
            </select>
          </label>
          <div className="row" style={{ gap: 16, marginBottom: 12 }}>
            <label>Speech language
              <select value={language} onChange={e => setLanguage(e.target.value)}>
                <option value="fa">Persian</option><option value="en">English</option>
                <option value="auto">Auto detect</option>
              </select>
            </label>
            <label>ASR engine
              <select value={asrEngine} onChange={e => setAsrEngine(e.target.value)}>
                <option value="auto">Auto (ElevenLabs → Sarovi → Whisper)</option>
                <option value="elevenlabs">ElevenLabs (best Persian)</option>
                <option value="sarovi">Sarovi (hosted Whisper, approx. timing)</option>
                <option value="whisper">Whisper (offline)</option>
              </select>
            </label>
            {(asrEngine === "whisper" || asrEngine === "auto") && <label>Whisper model
              <select value={whisperModel} onChange={e => setWhisperModel(e.target.value)}>
                <option value="base">base (default, faster download)</option>
                <option value="medium">medium (higher accuracy)</option>
                <option value="small">small (faster)</option>
                <option value="large-v3">large-v3 (slower)</option>
              </select>
            </label>}
          </div>
          <label style={{ display: "block" }}>Speech terms or names
            <input type="text" value={transcriptionHint} onChange={e => setTranscriptionHint(e.target.value)}
              placeholder="e.g. product names, brand names, technical terms"
              style={{ width: "100%", marginTop: 4 }} />
          </label>
        </div>

        <FontLibrary selectedId={captionFontId || undefined} onLibraryChange={refreshFonts}
          onSelect={(font: FontEntry | null) => {
            setCaptionFontId(font?.id || ""); setCaptionFont(font?.family || "");
          }} />
      </div>

      {/* Step 3 - Instruction */}
      <div className="card">
        <div className="section-header">
          <h2>Instruction</h2>
          <span className="muted">Step 3 (optional)</span>
        </div>
        <input
          aria-label="Additional editing instruction"
          type="text"
          placeholder="e.g. Make the CTA stronger, add more punch-ins..."
          value={instruction}
          onChange={e => setInstruction(e.target.value)}
          style={{ width: "100%" }}
        />
      </div>

      {/* Transitions */}
      <div className="card">
        <h2>Transitions</h2>
        <div className="row" style={{ gap: 16, marginBottom: 8 }}>
          <label>Format
            <select value={outputKind} onChange={e => setOutputKind(e.target.value as any)}>
              <option value="reel">Reel</option>
              <option value="story">Story</option>
              <option value="post">Post</option>
            </select>
          </label>
          <label>Style
            <select value={transitionStyle} onChange={e => setTransitionStyle(e.target.value as any)}>
              <option value="auto">Auto (AI decides)</option>
              <option value="none">None (hard cuts)</option>
              <option value="crossfade">Crossfade</option>
              <option value="directional">Directional</option>
              <option value="zoom">Boundary zoom</option>
            </select>
          </label>
        </div>
        <input type="text" aria-label="Transition note" placeholder="Optional note, e.g. only transition at topic changes"
          value={transitionRequest} onChange={e => setTransitionRequest(e.target.value)}
          style={{ width: "100%" }} />
      </div>

      {/* Music */}
      <div className="card">
        <div className="section-header">
          <h2>Music (optional)</h2>
        </div>
        <div style={{ marginBottom: 12 }}>
          <label>Upload custom music
            <input type="file" accept="audio/mp3,audio/wav,audio/aac,audio/m4a,audio/*"
              onChange={e => { const f = e.target.files?.[0]; if (f) { setMusicFile(f); setSelectedLibraryTrack(""); } }} />
          </label>
          {musicFile && <span className="muted" style={{ marginLeft: 8 }}>{musicFile.name} ({fmtSize(musicFile.size)})</span>}
        </div>
        {libraryTracks.length > 0 && (
          <div>
            <label>Or pick from library
              <select value={selectedLibraryTrack}
                onChange={e => { setSelectedLibraryTrack(e.target.value); if (e.target.value) setMusicFile(null); }}>
                <option value="">None</option>
                {libraryTracks.map(t => (
                  <option key={t.filename} value={t.filename}>
                    {t.filename} {t.mood ? `(${t.mood})` : ""} {t.duration_sec ? `${t.duration_sec.toFixed(0)}s` : ""}
                  </option>
                ))}
              </select>
            </label>
            {selectedLibraryTrack && (
              <button className="secondary" style={{ marginLeft: 8, fontSize: 12, padding: "4px 10px" }}
                onClick={() => {
                  if (playingTrack === selectedLibraryTrack && musicAudioRef.current) {
                    musicAudioRef.current.pause(); setPlayingTrack(null);
                  } else {
                    setPlayingTrack(selectedLibraryTrack);
                  }
                }}>
                {playingTrack === selectedLibraryTrack ? "Stop" : "Preview"}
              </button>
            )}
            {playingTrack && (
              <AuthenticatedMedia as="audio" ref={musicAudioRef} src={api.libraryPreviewUrl("music", playingTrack)}
                autoPlay onEnded={() => setPlayingTrack(null)} style={{ display: "none" }} />
            )}
          </div>
        )}
      </div>

      {/* Step 4 - Generate */}
      <div className="card">
        <div className="section-header">
          <h2>Generate or Upload Plan</h2>
          <span className="muted">Step 4</span>
        </div>
        <div className="row" style={{ gap: 12, alignItems: "center", marginBottom: 16 }}>
          <button onClick={onGenerate} disabled={busy || planStyleLoading || !video} title={planStyleLoading ? "Loading your saved plan style…" : (busy || !video) ? "Choose a video and complete the required plan fields first." : undefined}>
            {busy ? "Uploading..." : uploadFailed ? "Retry upload" : "Generate Edit Plan"}
          </button>
          <span className="muted">or upload a manual plan.json</span>
        </div>


        <div>
          <input type="file" aria-label="Upload a plan JSON file" accept="application/json" onChange={e => setPlanFile(e.target.files?.[0] || null)} />
          <textarea rows={6} aria-label="Paste edit plan JSON" placeholder='{"canvas": ..., "segments": [...], ...}'
            value={planText} onChange={e => setPlanText(e.target.value)}
            style={{ marginTop: 10 }} />
          {planJsonError && <p className="errors" role="alert">The pasted plan is not valid JSON. Check its formatting before creating the job.</p>}
        </div>
      </div>

      {err && <div className="errors" role="alert">{err}</div>}

      {uploadPct !== null && (
        <div role="status" aria-live="polite" style={{ marginTop: 12 }}>
          Uploading video… {uploadPct}%
          <button type="button" className="secondary" onClick={() => uploadController.current?.abort()}>
            Cancel upload
          </button>
          <div role="progressbar" aria-label="Video upload progress" aria-valuemin={0}
            aria-valuemax={100} aria-valuenow={uploadPct}
            style={{ height: 6, marginTop: 6, borderRadius: 99, background: "var(--border, #ddd)", overflow: "hidden" }}>
            <div style={{ width: `${uploadPct}%`, height: "100%", background: "var(--accent)", transition: "width .2s" }} />
          </div>
        </div>
      )}

      <div className="action-bar">
        <button onClick={onCreate} disabled={busy || !video || planJsonError} title={(busy || !video || planJsonError) ? "Choose a video and complete the required plan fields first." : undefined} className="secondary">
          {busy ? "Creating..." : uploadFailed ? "Retry upload" : "Create (with manual plan)"}
        </button>
      </div>
    </div>
  );
}
