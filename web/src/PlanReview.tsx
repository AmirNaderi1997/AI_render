import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, Correction, Corrections, EffectPreset, FontEntry, Job, Transcript } from "./api";
import { FontLibrary } from "./FontLibrary";
import { PremiereCard } from "./PremiereCard";
import { Timeline, outputToRaw, segmentOutputMarks } from "./Timeline";
import { AuthenticatedMedia } from "./AuthenticatedMedia";
import { MusicPicker } from "./MusicPicker";
import { Breadcrumbs, JobWorkflow, LoadingState, NextStep, friendlyError } from "./ui";

type Tab = "visual" | "json";
type WordEdit = { text: string; start: number; end: number };
const appendDetailError = (setErrors: React.Dispatch<React.SetStateAction<string[]>>, error: unknown, action: string) => {
  const message = friendlyError(error, action);
  setErrors(current => current.includes(message) ? current : [...current, message]);
};

export default function PlanReview() {
  const { id } = useParams();
  const nav = useNavigate();
  const [job, setJob] = React.useState<Job | null>(null);
  const [planText, setPlanText] = React.useState("");
  const [errors, setErrors] = React.useState<string[]>([]);
  const [validating, setValidating] = React.useState(false);
  const [loadError, setLoadError] = React.useState("");
  const [detailErrors, setDetailErrors] = React.useState<string[]>([]);
  const [detailsLoading, setDetailsLoading] = React.useState(true);
  const [actionBusy, setActionBusy] = React.useState(false);
  const [actionError, setActionError] = React.useState("");
  const [saved, setSaved] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [transcript, setTranscript] = React.useState<Transcript | null>(null);
  const [wordEdits, setWordEdits] = React.useState<Record<number, WordEdit>>({});
  const [effects, setEffects] = React.useState<EffectPreset[]>([]);
  const [fonts, setFonts] = React.useState<string[]>([]);
  const [corrections, setCorrections] = React.useState<Corrections | null>(null);
  const [dismissedCorrections, setDismissedCorrections] = React.useState<Set<number>>(new Set());
  const [transcriptMessage, setTranscriptMessage] = React.useState("");
  const [transcriptBusy, setTranscriptBusy] = React.useState(false);
  const [correctionBusy, setCorrectionBusy] = React.useState(false);
  const [reviewModel, setReviewModel] = React.useState("medium");
  const [reviewHint, setReviewHint] = React.useState("");
  const [reviewAcknowledged, setReviewAcknowledged] = React.useState(false);
  const [normalizeAudio, setNormalizeAudio] = React.useState(true);
  const [tab, setTab] = React.useState<Tab>("visual");
  const [genStatus, setGenStatus] = React.useState<any>(null);
  const [premiereManifest, setPremiereManifest] = React.useState<any>(null);
  const [savedPlanText, setSavedPlanText] = React.useState("");
  const [boundaryMessage, setBoundaryMessage] = React.useState("");
  const videoRef = React.useRef<HTMLVideoElement>(null);
  const renderedRef = React.useRef<HTMLVideoElement>(null);
  const currentJobId = React.useRef(id);
  currentJobId.current = id;
  const mountedRef = React.useRef(true);
  React.useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  React.useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    let active = true;
    const isCurrent = () => active && !controller.signal.aborted && currentJobId.current === id;
    setLoadError("");
    setDetailErrors([]);
    setDetailsLoading(true);
    const note = (error: unknown, action: string) => {
      if (!isCurrent()) return;
      if (action === "load the transcript" && /\b404\b|not found/i.test(error instanceof Error ? error.message : String(error))) return;
      appendDetailError(setDetailErrors, error, action);
    };
    api.getJob(id, controller.signal).then(j => {
      if (!isCurrent()) return;
      setJob(j);
      if (j.plan) {
        setPlanText(JSON.stringify(j.plan, null, 2));
        setSavedPlanText(JSON.stringify(j.plan));
        api.premiereReport(id, controller.signal).then(report => {
          if (isCurrent()) setPremiereManifest(report);
        }).catch(e => note(e, "load Premiere compatibility"));
      }
    }).catch(e => { if (isCurrent()) setLoadError(friendlyError(e, "load this job")); });
    const detailRequests = [
      api.getTranscript(id, controller.signal).then(t => { if (isCurrent()) { setTranscript(t); setWordEdits({}); } }).catch(e => note(e, "load the transcript")),
      api.listEffects(controller.signal).then(items => { if (isCurrent()) setEffects(items); }).catch(e => note(e, "load effects")),
      api.listFonts(controller.signal).then(items => { if (isCurrent()) setFonts(items); }).catch(e => note(e, "load fonts")),
      api.generateStatus(id, controller.signal).then(s => { if (isCurrent()) setGenStatus(s); }).catch(e => note(e, "load plan progress")),
      api.getCorrections(id, controller.signal).then(items => { if (isCurrent()) setCorrections(items); }).catch(e => note(e, "load speech suggestions")),
    ];
    void Promise.allSettled(detailRequests).then(() => { if (isCurrent()) setDetailsLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [id]);

  // Refreshes plan data once generation finishes. This must not share the poll
  // effect's AbortController: setting genStatus to "done" re-runs that effect and
  // its cleanup aborts in-flight requests, so the plan silently never loaded.
  const refreshGeneratedPlan = (jobId: string) => {
    const stillHere = () => mountedRef.current && currentJobId.current === jobId;
    api.getJob(jobId).then(j => {
      if (!stillHere()) return;
      setJob(j);
      if (j.plan) {
        setPlanText(JSON.stringify(j.plan, null, 2));
        setSavedPlanText(JSON.stringify(j.plan));
        api.premiereReport(jobId).then(report => { if (stillHere()) setPremiereManifest(report); })
          .catch(e => { if (stillHere()) appendDetailError(setDetailErrors, e, "load Premiere compatibility"); });
      }
    }).catch(e => { if (stillHere()) appendDetailError(setDetailErrors, e, "load the updated job"); });
    api.getTranscript(jobId).then(t => { if (stillHere()) { setTranscript(t); setWordEdits({}); } }).catch(e => { if (stillHere()) appendDetailError(setDetailErrors, e, "load the updated transcript"); });
    api.getCorrections(jobId).then(items => { if (stillHere()) setCorrections(items); }).catch(e => { if (stillHere()) appendDetailError(setDetailErrors, e, "load speech suggestions"); });
  };

  React.useEffect(() => {
    if (!id || genStatus?.status !== "running") return;
    const controller = new AbortController();
    let active = true;
    const isCurrent = () => active && !controller.signal.aborted && currentJobId.current === id;
    let inFlight = false;
    const iv = setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      api.generateStatus(id, controller.signal).then(s => {
        if (!isCurrent()) return;
        setGenStatus(s);
        if (s.status === "done") refreshGeneratedPlan(id);
      }).catch(e => { if (isCurrent()) appendDetailError(setDetailErrors, e, "check plan progress"); }).finally(() => { inFlight = false; });
    }, 1500);
    return () => { active = false; clearInterval(iv); controller.abort(); };
  }, [id, genStatus?.status]);

  const parsedPlan = React.useMemo(() => {
    try { return JSON.parse(planText); } catch { return null; }
  }, [planText]);

  React.useEffect(() => setReviewAcknowledged(false), [planText]);

  React.useEffect(() => {
    const controller = new AbortController();
    if (!id || !parsedPlan) { setErrors(planText.trim() ? ["The edit plan is not valid JSON. Check its formatting and try again."] : []); setValidating(false); return; }
    const t = setTimeout(async () => {
      if (currentJobId.current !== id || controller.signal.aborted) return;
      setValidating(true);
      try {
        const r = await api.validate(id, parsedPlan, controller.signal);
        if (!controller.signal.aborted && currentJobId.current === id) setErrors(r.errors);
      } catch (e) {
        if (!controller.signal.aborted && currentJobId.current === id) setErrors([friendlyError(e, "validate this plan")]);
      } finally {
        if (!controller.signal.aborted && currentJobId.current === id) setValidating(false);
      }
    }, 400);
    return () => { clearTimeout(t); controller.abort(); };
  }, [planText, parsedPlan, id]);

  async function save(): Promise<boolean> {
    if (!id || !parsedPlan) return false;
    setSaving(true);
    try {
      // Stage 5: capture feedback diff before saving
      const previousPlan = savedPlanText ? JSON.parse(savedPlanText) : null;

      const r = await api.putPlan(id, parsedPlan);
      if (!r.ok) { setErrors(r.errors || []); return false; }

      // Log feedback if plan changed from AI-generated version
      if (previousPlan && JSON.stringify(previousPlan) !== JSON.stringify(parsedPlan)) {
        try {
          const events = computePlanDiff(previousPlan, parsedPlan);
          if (events.length > 0) {
            api.postPlanFeedback(id, events).catch(e => appendDetailError(setDetailErrors, e, "save plan feedback"));
          }
        } catch (e) { appendDetailError(setDetailErrors, e, "prepare plan feedback"); }
      }

      setSavedPlanText(JSON.stringify(parsedPlan));
      setSaved(true); setTimeout(() => setSaved(false), 2000);
      api.premiereReport(id).then(setPremiereManifest).catch(e => appendDetailError(setDetailErrors, e, "refresh Premiere compatibility"));
      return true;
    } catch (error: any) {
      setErrors([friendlyError(error, "save the edit plan")]);
      return false;
    } finally { setSaving(false); }
  }

  async function doRender(preview: boolean) {
    if (!id) return;
    setActionBusy(true); setActionError("");
    try {
      if (!(await save())) return;
      await api.render(id, preview, normalizeAudio);
      nav(`/jobs/${id}/render`);
    } catch (e) { setActionError(friendlyError(e, "start the render")); }
    finally { setActionBusy(false); }
  }

  async function preparePremiereDownload(url: string) {
    if (!id) return;
    setActionBusy(true); setActionError("");
    try {
      if (!(await save())) return;
      const filename = url.split("/").pop() || `ai-render-${id}-premiere`;
      await api.downloadAuthenticated(url, filename);
    } catch (e) { setActionError(friendlyError(e, "download the Premiere package")); }
    finally { setActionBusy(false); }
  }

  async function downloadPlan() {
    if (!id) return;
    setActionBusy(true); setActionError("");
    try { await api.downloadAuthenticated(api.planUrl(id), "plan.json"); }
    catch (e) { setActionError(friendlyError(e, "download the edit plan")); }
    finally { setActionBusy(false); }
  }

  async function viewPremiereReport() {
    if (!id) return;
    setActionBusy(true); setActionError("");
    try { await api.downloadAuthenticated(api.premiereReportUrl(id), "premiere_transition_report.json", true); }
    catch (e) { setActionError(friendlyError(e, "open the compatibility report")); }
    finally { setActionBusy(false); }
  }

  function seekTo(t: number) {
    if (videoRef.current) { videoRef.current.currentTime = t; videoRef.current.play(); }
  }

  function updatePlanField(path: (string | number)[], value: any) {
    if (!parsedPlan) return;
    const copy = JSON.parse(JSON.stringify(parsedPlan));
    let obj: any = copy;
    for (let i = 0; i < path.length - 1; i++) obj = obj[path[i]];
    obj[path[path.length - 1]] = value;
    setPlanText(JSON.stringify(copy, null, 2));
  }

  function deleteItem(arrayPath: string[], index: number) {
    if (!parsedPlan) return;
    const copy = JSON.parse(JSON.stringify(parsedPlan));
    let arr: any = copy;
    for (const k of arrayPath) arr = arr[k];
    if (arrayPath.length === 1 && arrayPath[0] === "segments") {
      const removedId = arr[index]?.id;
      copy.transitions = (copy.transitions || []).filter((item: any) =>
        item.from_segment_id !== removedId && item.to_segment_id !== removedId);
    }
    arr.splice(index, 1);
    setPlanText(JSON.stringify(copy, null, 2));
  }

  async function saveTranscriptCorrections() {
    if (!id || !transcript) return;
    setTranscriptBusy(true);
    const words = transcript.words.flatMap((word, index) => {
      const edit = wordEdits[index];
      return (word.reviewed || edit) ? [{ index,
        text: edit?.text ?? word.w, start: edit?.start ?? word.start, end: edit?.end ?? word.end }] : [];
    });
    try {
      const updated = await api.putTranscriptCorrections(id, transcript.cache_key || transcript.file_hash, words);
      setTranscript(updated); setWordEdits({});
      setTranscriptMessage("Corrections saved. Regenerate the plan to update captions and cuts.");
    } catch (error: any) { setTranscriptMessage(friendlyError(error, "save transcript corrections")); }
    finally { setTranscriptBusy(false); }
  }

  async function regenerateFromTranscript() {
    if (!id || Object.keys(wordEdits).length) return;
    setTranscriptBusy(true);
    try {
      if (!(await save())) return;
      await api.generatePlan(id, { use_saved_transcript: true,
        caption_font: parsedPlan?.canvas?.caption_font || undefined,
        caption_font_id: parsedPlan?.canvas?.caption_font_id || undefined,
        style_id: parsedPlan?.style_profile?.style_id,
        style_version: parsedPlan?.style_profile?.version,
        output_kind: parsedPlan?.transition_context?.output_kind || "reel",
        transition_style: parsedPlan?.transition_context?.style || "auto",
        transition_request: parsedPlan?.transition_context?.request || "" });
      setGenStatus({ status: "running", stage: "planning", message: "Using reviewed transcript" });
      setTranscriptMessage("Generating a new plan from the saved transcript...");
    } catch (error: any) { setTranscriptMessage(friendlyError(error, "regenerate the plan")); }
    finally { setTranscriptBusy(false); }
  }

  async function retranscribeOnly() {
    if (!id || Object.keys(wordEdits).length) return;
    setTranscriptBusy(true);
    try {
      await api.generatePlan(id, { transcribe_only: true, whisper_model: reviewModel,
        language: transcript?.requested_language || transcript?.language || "fa",
        transcription_hint: reviewHint.trim() });
      setGenStatus({ status: "running", stage: "transcribing", message: "Creating a transcript candidate" });
      setTranscriptMessage("Re-transcribing only. The current plan and render remain available.");
    } catch (error: any) { setTranscriptMessage(friendlyError(error, "retranscribe the audio")); }
    finally { setTranscriptBusy(false); }
  }

  function updateEffect(segmentId: string, effectId: string) {
    if (!parsedPlan) return;
    const copy = JSON.parse(JSON.stringify(parsedPlan));
    copy.visual_effects = (copy.visual_effects || []).filter((effect: any) => effect.segment_id !== segmentId);
    if (effectId) copy.visual_effects.push({ segment_id: segmentId, type: effectId });
    if (copy.visual_effects.length) copy.version = "0.2";
    setPlanText(JSON.stringify(copy, null, 2));
  }

  function updateTransition(boundaryIndex: number, patch: Record<string, any>) {
    if (!parsedPlan) return;
    const copy = JSON.parse(JSON.stringify(parsedPlan));
    copy.transitions = copy.transitions || [];
    const from = copy.segments[boundaryIndex];
    const to = copy.segments[boundaryIndex + 1];
    const existingIndex = copy.transitions.findIndex((item: any) =>
      item.from_segment_id === from.id && item.to_segment_id === to.id);
    const previous = existingIndex >= 0 ? copy.transitions[existingIndex] : {
      from_segment_id: from.id, to_segment_id: to.id, type: "hard_cut",
      duration_frames: 0, direction: "left", intensity: 1,
    };
    const next = { ...previous, ...patch, source: "manual", locked: true };
    if (next.type === "hard_cut") next.duration_frames = 0;
    else if (!next.duration_frames) next.duration_frames = 6;
    const deltaFrames = Number(next.duration_frames || 0) - Number(previous.duration_frames || 0);
    if (existingIndex >= 0) copy.transitions[existingIndex] = next;
    else copy.transitions.push(next);
    copy.transition_analysis = copy.transition_analysis || [];
    copy.transition_analysis[boundaryIndex] = { boundary_index: boundaryIndex,
      source: "manual", reason: "manual choice locked by the user" };
    copy.version = "0.3";
    if (deltaFrames) {
      const pivot = segmentOutputMarks(parsedPlan)[boundaryIndex + 1]?.start || 0;
      const delta = deltaFrames / (copy.canvas?.fps || 30);
      const shift = (value: number) => value >= pivot - 1e-6 ? Math.max(0, +(value - delta).toFixed(3)) : value;
      for (const item of copy.captions || []) { item.start = shift(item.start); item.end = shift(item.end); }
      for (const item of copy.broll || []) item.at = shift(item.at);
      for (const item of copy.sfx || []) item.at = shift(item.at);
      for (const item of copy.music?.duck || []) { item.start = shift(item.start); item.end = shift(item.end); }
      if (copy.cover) { copy.cover.start = shift(copy.cover.start); copy.cover.end = shift(copy.cover.end); }
      if (copy.poster) copy.poster.frame_time = shift(copy.poster.frame_time);
    }
    setPlanText(JSON.stringify(copy, null, 2));
  }

  function previewRenderedBoundary(outputTime: number) {
    if (!renderedRef.current) {
      setBoundaryMessage("Render a preview first; raw playback cannot show an overlapping transition exactly.");
      return;
    }
    renderedRef.current.currentTime = Math.max(0, outputTime - 0.35);
    renderedRef.current.play();
    setBoundaryMessage("Playing the rendered boundary from 0.35 seconds before the overlap.");
  }

  if (!job) return loadError ? <div className="errors" role="alert">{loadError} <button className="secondary" onClick={() => window.location.reload()}>Try again</button></div> : <LoadingState label="Loading job and edit plan…" />;

  const isGenerating = genStatus?.status === "running";
  const needsReview = !!(parsedPlan?.caption_review?.length || parsedPlan?.effect_review?.length);
  const renderedPreview = [...(job.versions || [])].reverse().find(name => name.includes("_preview"));

  return (
    <div>
      <Breadcrumbs items={[{ label: "Jobs", to: "/jobs" }, { label: job.raw_name || `Job ${job.id}` }, { label: "Plan Review" }]} />
      <div className="plan-review-heading">
        <h1>{job.raw_name || `Job ${job.id}`}</h1>
        <div className="plan-review-save">
          {saved && <span className="ok" role="status">Saved.</span>}
          <button
            type="button"
            onClick={() => { void save(); }}
            disabled={actionBusy || saving || !parsedPlan}
            title={saving || actionBusy ? "Wait for the current plan action" : !parsedPlan ? "Generate an edit plan first" : "Save edits to this plan"}
          >
            {saving ? "Saving…" : "Save plan"}
          </button>
        </div>
      </div>
      <JobWorkflow job={job} current={2} />
      {!parsedPlan && !isGenerating && <div className="empty-state" role="status"><strong>No edit plan yet</strong><p>Generate a plan from this job to review its timeline and render a reel.</p><a className="button-link" href="/new">Create a reel</a></div>}
      {parsedPlan && !isGenerating && <NextStep>Review the edit plan, then start a preview render to check the result.</NextStep>}

      {parsedPlan?.style_profile && (
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          padding: "6px 14px", borderRadius: "100px",
          background: "var(--accent-soft)", border: "1px solid rgba(99,102,241,0.15)",
          fontSize: 13, marginBottom: 16
        }}>
          <span style={{ fontWeight: 600 }}>{parsedPlan.style_profile.name} v{parsedPlan.style_profile.version}</span>
          <span className="muted">style pinned</span>
        </div>
      )}

      {isGenerating && (
        <div className="card" style={{ borderLeft: "3px solid var(--accent)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="generating-pulse" style={{
              width: 8, height: 8, borderRadius: "50%", background: "var(--accent)"
            }} />
            <b>Generating plan...</b>
            <span className="muted">Stage: {genStatus.stage}</span>
          </div>
          <div className="muted" style={{ marginTop: 4 }}>{genStatus.message}</div>
        </div>
      )}
      {actionError && <div className="errors" role="alert">{actionError}</div>}
      {detailsLoading && <LoadingState label="Loading plan details…" rows={1} />}
      {detailErrors.length > 0 && <div className="errors" role="alert">{detailErrors.map((message, i) => <p key={i}>{message}</p>)}</div>}
      {detailErrors.length > 0 && <button className="secondary" onClick={() => window.location.reload()}>Retry loading plan details</button>}
      {validating && <p className="muted" role="status">Checking edit plan…</p>}
      {genStatus?.status === "error" && (
        <div className="errors" role="alert">Generation failed: {genStatus.message} <a href="/new">Start a new reel</a></div>
      )}
      {genStatus?.asr_fallback_reason && (
        <div className="errors" role="status">ASR fallback: {genStatus.asr_fallback_reason}</div>
      )}

      {(genStatus?.cost_usd > 0 || genStatus?.asr_cost_usd > 0) && (
        <div className="card" style={{ padding: "10px 16px", fontSize: 13 }}>
          {genStatus.cost_usd > 0 && <>LLM cost: <b>${genStatus.cost_usd.toFixed(4)}</b>
          {" "}({genStatus.model}, {genStatus.input_tokens} in / {genStatus.output_tokens} out)</>}
          {genStatus.asr_cost_usd > 0 && <div style={{ marginTop: 4 }}>
            ASR cost: <b>${genStatus.asr_cost_usd.toFixed(4)}</b>
            {" "}({genStatus.asr_engine}, {genStatus.asr_audio_seconds?.toFixed(1)}s audio)
          </div>}
          {genStatus.correction_model && <div style={{ marginTop: 4 }}>
            Correction model: <b>{genStatus.correction_model}</b>
          </div>}
        </div>
      )}

      {parsedPlan?.generation_meta?.warnings?.filter((warning: string) =>
        !parsedPlan.music || !warning.startsWith("No playable background music")
      ).map((warning: string, i: number) => (
        <p className="muted" key={i}>{warning}</p>
      ))}
      <div className="grid2">
        <div className="card">
          <h2>{parsedPlan?.source_type === "generated" ? "Generated Source" : "Raw Video"}</h2>
          <AuthenticatedMedia as="video" ref={videoRef} src={api.rawUrl(job.id)} controls preload="metadata" />
          {parsedPlan?.source_type === "generated" && <p className="muted">Render a preview to hear the voiceover and background music together.</p>}
        </div>
        <div className="card">
          <h2>Timeline</h2>
          <Timeline plan={parsedPlan} onSeek={seekTo} />
        </div>
      </div>

      {renderedPreview &&
        <div className="card">
          <h2>Rendered Transition Preview</h2>
          <AuthenticatedMedia as="video" ref={renderedRef} src={api.exportUrl(job.id, renderedPreview)} controls preload="metadata" />
          <p className="muted" style={{ marginTop: 8 }}>Boundary Preview buttons below seek this rendered file, not the raw source.</p>
        </div>}
      {boundaryMessage && <p className="muted">{boundaryMessage}</p>}

      {id && parsedPlan && <PremiereCard key={`${id}:${savedPlanText}:${genStatus?.status}`} id={id}
        savePlan={async () => !!parsedPlan && (JSON.stringify(parsedPlan) !== savedPlanText ? save() : true)} />}
      {premiereManifest && <section className="card" dir="auto" aria-label="Premiere compatibility">
        <h2>Premiere Compatibility</h2>
        {JSON.stringify(parsedPlan) !== savedPlanText && <p className="errors">Compatibility package is stale. Save the current Edit Plan before downloading.</p>}
        <p className="muted">{premiereManifest.sequence?.width}x{premiereManifest.sequence?.height} · {premiereManifest.sequence?.fps} fps · {premiereManifest.sequence?.output_frames} frames · {Number(premiereManifest.sequence?.duration_seconds || 0).toFixed(2)} s</p>
        <p className="muted" style={{ marginTop: 4 }}>FCP7 XML interchange for Premiere import. Import the XML and SRT separately; save the imported sequence in Premiere as a native .prproj.</p>
        <div className="row" style={{ flexWrap: "wrap", gap: 12, margin: "12px 0", fontSize: 12 }}>
          <span>Exact editable: {premiereManifest.transitions?.filter((x: any) => x.capability_classification === "exact_editable").length || 0}</span>
          <span>Editable fallback: {premiereManifest.transitions?.filter((x: any) => x.capability_classification === "editable_fallback").length || 0}</span>
          <span>Verified: {[...(premiereManifest.transitions || []), ...(premiereManifest.captions?.components || []), ...(premiereManifest.visual_effects || [])].filter((x: any) => x.current_artifact_verification?.status === "verified").length}</span>
          <span>Unverified: {[...(premiereManifest.transitions || []), ...(premiereManifest.captions?.components || []), ...(premiereManifest.visual_effects || [])].filter((x: any) => x.current_artifact_verification?.status !== "verified").length}</span>
        </div>
        <p className={premiereManifest.current_artifact_verification?.fully_verified ? "muted" : "errors"}>
          Current package: {premiereManifest.current_artifact_verification?.fully_verified ? "fully inspected" : premiereManifest.current_artifact_verification?.status || "unverified"}
          {premiereManifest.current_artifact_verification?.verification_time ? ` · inspected ${premiereManifest.current_artifact_verification.verification_time}` : ""}
        </p>
        {(premiereManifest.transitions || []).map((row: any) => <p key={`${row.from_segment_id}-${row.to_segment_id}`} className={row.current_artifact_verification?.status === "verified" ? "muted" : "errors"} style={{ fontSize: 12, margin: "4px 0" }}>
          {row.from_segment_id} &rarr; {row.to_segment_id}: {row.requested_behavior?.type}, {row.duration_frames} frames{row.requested_behavior?.direction ? `, ${row.requested_behavior.direction}, intensity ${row.requested_behavior.intensity}` : ""}{row.requested_behavior?.zoom_mode ? `, ${row.requested_behavior.zoom_mode} ${row.requested_behavior.zoom_scale}x` : ""} &rarr; {row.premiere_representation} · previously {row.capability_classification || row.classification} · this package {row.current_artifact_verification?.classification || "unverified"}
        </p>)}
        {(premiereManifest.visual_effects || []).map((effect: any, i: number) => <p key={`${effect.segment_id}-${i}`} className={effect.current_artifact_verification?.status === "verified" ? "muted" : "errors"} style={{ fontSize: 12, margin: "4px 0" }}>{effect.segment_id}: {effect.effect_type} &rarr; rendered MP4 only · previously {effect.capability_classification || effect.classification} · this package {effect.current_artifact_verification?.classification || "unverified"}</p>)}
        {[...(premiereManifest.transitions || []), ...(premiereManifest.captions?.components || []), ...(premiereManifest.visual_effects || [])]
          .filter((item: any) => item.current_artifact_verification?.status !== "verified")
          .map((item: any, i: number) => <p key={`unverified-${i}`} className="errors" style={{ fontSize: 12, margin: "4px 0" }}>{item.from_segment_id && item.to_segment_id ? `${item.from_segment_id} → ${item.to_segment_id}` : item.segment_id || `Caption ${Number(item.caption_index) + 1}`}: current package inspection is unverified. {item.current_artifact_verification?.reason || item.explanation}</p>)}
        {!!premiereManifest.warnings?.length && <ul style={{ fontSize: 12 }}>{premiereManifest.warnings.map((warning: string, i: number) => <li key={i}>{warning}</li>)}</ul>}
        <p className="muted" style={{ fontSize: 12 }}>Source media uses an absolute path; relink in Premiere if it has moved. Captions use UTF-8 {premiereManifest.captions?.filename}; SRT carries text and timing, not AI Render font, weight, outline, placement, or RTL styling.</p>
        <p className="muted" style={{ fontSize: 12 }}>Generated package files: {(premiereManifest.generated_files || []).map((file: any) => file.filename).join(", ")}.</p>
        <p className="muted" style={{ fontSize: 12 }}>Import: open <b>project_premiere.xml</b> in Premiere, import <b>{premiereManifest.captions?.filename}</b> as captions, then save as .prproj. The rendered MP4 is visually authoritative for every fallback or rendered-only feature.</p>
        <div className="row" style={{ flexWrap: "wrap", marginTop: 12 }}>
          <button disabled={actionBusy} title={(actionBusy) ? "Wait for the current action to finish." : undefined} onClick={() => { if (id) void preparePremiereDownload(api.premiereUrl(id)); }}>Download Premiere package (ZIP)</button>
          <button className="secondary" disabled={actionBusy} title={(actionBusy) ? "Wait for the current action to finish." : undefined} onClick={() => { if (id) void preparePremiereDownload(api.premiereXmlUrl(id)); }}>Download XML</button>
          <button className="secondary" disabled={actionBusy} title={(actionBusy) ? "Wait for the current action to finish." : undefined} onClick={() => { if (id) void preparePremiereDownload(api.premiereCaptionsUrl(id)); }}>Download editable captions (SRT)</button>
          {id && <button className="secondary" disabled={actionBusy} title={(actionBusy) ? "Wait for the current action to finish." : undefined} onClick={() => void viewPremiereReport()}>View compatibility report</button>}
        </div>
      </section>}

      {parsedPlan && <div className="card">
        <label>Legacy or bundled caption font: <select value={parsedPlan.canvas?.caption_font_id ? "" : (parsedPlan.canvas?.caption_font || "")}
          onChange={e => setPlanText(JSON.stringify({ ...parsedPlan,
            canvas: { ...parsedPlan.canvas, caption_font: e.target.value || null, caption_font_id: null } }, null, 2))}>
          <option value="">Style default</option>
          {fonts.map(font => <option key={font} value={font}>{font}</option>)}
          {parsedPlan.canvas?.caption_font && !fonts.includes(parsedPlan.canvas.caption_font) &&
            <option value={parsedPlan.canvas.caption_font}>{parsedPlan.canvas.caption_font}</option>}
        </select></label>
      </div>}
      {parsedPlan && <FontLibrary selectedId={parsedPlan.canvas?.caption_font_id || undefined}
        onSelect={(font: FontEntry | null) => setPlanText(JSON.stringify({ ...parsedPlan,
          canvas: { ...parsedPlan.canvas, caption_font: font?.family || null, caption_font_id: font?.id || null } }, null, 2))} />}

      {corrections && (corrections.suggestions.length > 0 || corrections.auto_applied.length > 0) && (
        <ReviewCorrectionsPanel
          corrections={corrections}
          dismissed={dismissedCorrections}
          transcript={transcript}
          jobId={id!}
          busy={correctionBusy}
          onSeek={seekTo}
          onAccept={async (c) => {
            if (!id || !transcript) return;
            setCorrectionBusy(true);
            try {
              await api.acceptCorrection(id, {
                base_key: transcript.cache_key || transcript.file_hash,
                index: c.index, old: c.old, new: c.new,
                save_to_glossary: true,
              });
              const updated = await api.getTranscript(id);
              setTranscript(updated);
              setWordEdits({});
              setDismissedCorrections(d => new Set([...d, c.index]));
              setTranscriptMessage(`Accepted: ${c.old} → ${c.new} (saved to glossary)`);
            } catch (e: any) { setTranscriptMessage(friendlyError(e, "accept this correction")); }
            finally { setCorrectionBusy(false); }
          }}
          onReject={async (c) => {
            if (!id) return;
            setCorrectionBusy(true);
            try {
              await api.rejectCorrection(id, { index: c.index, old: c.old });
              setDismissedCorrections(d => new Set([...d, c.index]));
            } catch (e) { setTranscriptMessage(friendlyError(e, "reject this suggestion")); }
            finally { setCorrectionBusy(false); }
          }}
          onAcceptAllHigh={async () => {
            if (!id || !transcript) return;
            setCorrectionBusy(true);
            const highConf = corrections.suggestions.filter(c => c.confidence >= 0.85 && !dismissedCorrections.has(c.index));
            let accepted = 0;
            for (const c of highConf) {
              try {
                await api.acceptCorrection(id, {
                  base_key: transcript.cache_key || transcript.file_hash,
                  index: c.index, old: c.old, new: c.new, save_to_glossary: true,
                });
                setDismissedCorrections(d => new Set([...d, c.index]));
                accepted++;
              } catch (e) { setTranscriptMessage(friendlyError(e, "accept one of the suggestions")); }
            }
            const updated = await api.getTranscript(id).catch(e => { setTranscriptMessage(friendlyError(e, "refresh the transcript")); return null; });
            if (updated) { setTranscript(updated); setWordEdits({}); }
            if (updated) setTranscriptMessage(`Accepted ${accepted} high-confidence correction(s)`);
            setCorrectionBusy(false);
          }}
        />
      )}
      {correctionBusy && <p className="muted" role="status">Updating speech suggestions…</p>}

      {transcript && (
        <div className="card">
          <div className="section-header">
            <h2>Transcript</h2>
            <span className="muted">{transcript.language} · {transcript.model_size || "model unknown"}</span>
          </div>
          <p className="muted" style={{ marginBottom: 10 }}>Click a word to hear it. Edit uncertain words, then save before regenerating the plan. Yellow words have low ASR confidence.</p>
          <TranscriptView
            transcript={transcript}
            plan={parsedPlan}
            onSeek={seekTo}
            edits={wordEdits}
            onEdit={(index, change) => setWordEdits(current => {
              const baseline: WordEdit = { text: transcript.words[index].w,
                start: transcript.words[index].start, end: transcript.words[index].end };
              return { ...current, [index]: { ...baseline, ...current[index], ...change } };
            })}
          />
          <div className="row" style={{ marginTop: 14 }}>
            <button onClick={saveTranscriptCorrections} disabled={transcriptBusy || !Object.keys(wordEdits).length} title={(transcriptBusy || !Object.keys(wordEdits).length) ? "Make a transcript correction before saving." : undefined}>Save transcript corrections</button>
            <button className="secondary" onClick={regenerateFromTranscript}
              disabled={transcriptBusy || isGenerating || !!Object.keys(wordEdits).length} title={(transcriptBusy || isGenerating || !!Object.keys(wordEdits).length) ? "Make a transcript correction before saving." : undefined}>Regenerate plan from transcript</button>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <label>ASR model <select value={reviewModel} onChange={e => setReviewModel(e.target.value)}>
              <option value="medium">medium</option><option value="small">small</option>
              <option value="large-v3">large-v3</option>
            </select></label>
            <input aria-label="Speech terms for re-transcription" value={reviewHint}
              onChange={e => setReviewHint(e.target.value)} placeholder="Speech terms (optional)" />
            <button className="secondary" onClick={retranscribeOnly}
              disabled={transcriptBusy || isGenerating || !!Object.keys(wordEdits).length} title={(transcriptBusy || isGenerating || !!Object.keys(wordEdits).length) ? "Make a transcript correction before saving." : undefined}>Re-transcribe only</button>
          </div>
          {transcriptBusy && <p className="muted" role="status">Updating transcript…</p>}
          {transcriptMessage && <p className="muted" role="status" style={{ marginTop: 8 }}>{transcriptMessage}</p>}
        </div>
      )}

      <div className="card">
        <div className="tabs" aria-label="Edit plan view">
          <button aria-pressed={tab === "visual"} className={`tab-btn ${tab === "visual" ? "active" : ""}`} onClick={() => setTab("visual")}>
            Visual Editor
          </button>
          <button aria-pressed={tab === "json"} className={`tab-btn ${tab === "json" ? "active" : ""}`} onClick={() => setTab("json")}>
            JSON
          </button>
        </div>

        {tab === "visual" && parsedPlan ? (
          <VisualEditor
            jobId={job.id}
            plan={parsedPlan}
            effects={effects}
            onEffectChange={updateEffect}
            onUpdate={updatePlanField}
            onDelete={deleteItem}
            onSeek={seekTo}
            onSeekOutput={t => seekTo(outputToRaw(parsedPlan, t))}
            onTransitionChange={updateTransition}
            onPreviewBoundary={previewRenderedBoundary}
          />
        ) : (
          <div>
            <textarea rows={22} aria-label="Edit plan JSON" value={planText} onChange={e => setPlanText(e.target.value)} />
          </div>
        )}

        {errors.length > 0 ? (
          <div className="errors" style={{ marginTop: 12 }}>
            <div><b>Validation errors:</b></div>
            <ul>{errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
          </div>
        ) : parsedPlan ? <div className="ok" style={{ marginTop: 12 }}>Plan is valid.</div> : null}
        {saved && <div className="ok" style={{ marginTop: 8 }}>Saved.</div>}
      </div>

      <div className="action-bar">
        <label className="muted" title="Apply the preset loudness target after mixing voice, music, and SFX">
          <input type="checkbox" checked={normalizeAudio}
            onChange={e => setNormalizeAudio(e.target.checked)} />
          Normalize mixed audio
        </label>
        {needsReview &&
          <label className="muted"><input type="checkbox" checked={reviewAcknowledged}
            onChange={e => setReviewAcknowledged(e.target.checked)} />
            I reviewed the marked captions against the audio and checked subject framing</label>}
        <button onClick={() => { void save(); }} className="secondary" disabled={actionBusy || saving || !parsedPlan} title={saving || actionBusy ? "Wait for the current plan action" : !parsedPlan ? "Generate an edit plan first" : undefined}>{saving ? "Saving…" : "Save plan"}</button>
        <button onClick={() => doRender(true)} disabled={actionBusy || !parsedPlan} title={actionBusy ? "Wait for the current plan action" : !parsedPlan ? "Generate an edit plan first" : undefined}>Preview (540x960)</button>
        <button onClick={() => doRender(false)}
          disabled={actionBusy || !parsedPlan || (needsReview && !reviewAcknowledged)} title={actionBusy ? "Wait for the current plan action" : !parsedPlan ? "Generate an edit plan first" : needsReview && !reviewAcknowledged ? "Acknowledge the marked captions and framing checks first" : undefined}>Render (1080x1920)</button>
        {actionBusy && <span className="muted" role="status">Preparing your request…</span>}
        <button className="secondary" disabled={actionBusy || !parsedPlan} title={actionBusy ? "Wait for the current plan action" : !parsedPlan ? "Generate an edit plan first" : undefined} onClick={() => void downloadPlan()}>Download plan.json</button>
      </div>
    </div>
  );
}


/* ---------- Review Corrections Panel ---------- */

function ReviewCorrectionsPanel({ corrections, dismissed, transcript, jobId, busy, onSeek, onAccept, onReject, onAcceptAllHigh }: {
  corrections: Corrections;
  dismissed: Set<number>;
  transcript: Transcript | null;
  jobId: string;
  busy: boolean;
  onSeek: (t: number) => void;
  onAccept: (c: Correction) => void;
  onReject: (c: Correction) => void;
  onAcceptAllHigh: () => void;
}) {
  const pending = corrections.suggestions.filter(c => !dismissed.has(c.index));
  const applied = corrections.auto_applied.filter(c => !dismissed.has(c.index));
  const highConf = pending.filter(c => c.confidence >= 0.85);

  function playWord(c: Correction) {
    if (transcript) {
      const w = transcript.words[c.index];
      if (w) onSeek(w.start);
    }
  }

  return (
    <div className="card">
      <div className="section-header">
        <h2>Review Corrections</h2>
        {pending.length > 0 && (
          <span style={{
            padding: "3px 10px", borderRadius: "100px", fontSize: 11, fontWeight: 700,
            background: "var(--warning-soft)", color: "var(--warning)"
          }}>
            {pending.length} pending
          </span>
        )}
      </div>

      {applied.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Auto-applied (confidence &ge; 0.85):</div>
          {applied.map(c => (
            <div key={c.index} className="ve-item" style={{ borderLeft: "3px solid var(--success)" }}>
              <span className="muted" style={{ fontSize: 11, fontFamily: "monospace" }}>#{c.index}</span>
              <span style={{ textDecoration: "line-through", color: "var(--text-tertiary)" }}>{c.old}</span>
              <span style={{ color: "var(--text-tertiary)" }}>&rarr;</span>
              <b>{c.new}</b>
              <span className="muted" style={{ fontSize: 11, flex: 1 }}>{(c.confidence * 100).toFixed(0)}% &mdash; {c.reason}</span>
              <button className="secondary" aria-label={`Play audio for ${c.new}`} style={{ fontSize: 11, padding: "4px 8px" }} onClick={() => playWord(c)}>&#9654;</button>
            </div>
          ))}
        </div>
      )}

      {pending.length > 0 && (
        <>
          <div style={{ marginBottom: 10 }}>
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Suggestions (review required):</div>
            {pending.map(c => (
              <div key={c.index} className="ve-item" style={{ borderLeft: "3px solid var(--warning)" }}>
                <span className="muted" style={{ fontSize: 11, fontFamily: "monospace" }}>#{c.index}</span>
                <span style={{ color: "var(--warning)" }}>{c.old}</span>
                <span style={{ color: "var(--text-tertiary)" }}>&rarr;</span>
                <b>{c.new}</b>
                <span className="muted" style={{ fontSize: 11, flex: 1 }}>{(c.confidence * 100).toFixed(0)}% &mdash; {c.reason}</span>
                <button className="secondary" aria-label={`Play audio for ${c.old}`} style={{ fontSize: 11, padding: "4px 8px" }} onClick={() => playWord(c)} title="Play word audio">&#9654;</button>
                <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => onAccept(c)}>Accept</button>
                <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} className="secondary" style={{ fontSize: 11, padding: "4px 10px" }} onClick={() => onReject(c)}>Reject</button>
              </div>
            ))}
          </div>
          {highConf.length > 0 && (
            <button disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={onAcceptAllHigh}>
              Accept all high-confidence ({highConf.length})
            </button>
          )}
        </>
      )}
    </div>
  );
}


/* ---------- Transcript view with clickable words ---------- */

function TranscriptView({ transcript, plan, onSeek, edits, onEdit }: {
  transcript: Transcript; plan: any; onSeek: (t: number) => void;
  edits: Record<number, WordEdit>; onEdit: (index: number, change: Partial<WordEdit>) => void;
}) {
  const [selected, setSelected] = React.useState<number | null>(null);
  const removedRanges = React.useMemo(() => {
    if (!plan?.segments || !transcript) return new Set<number>();
    const kept = new Set<number>();
    for (const seg of plan.segments) {
      for (let i = 0; i < transcript.words.length; i++) {
        const w = transcript.words[i];
        if (w.start >= seg.in - 0.05 && w.end <= seg.out + 0.05) kept.add(i);
      }
    }
    const removed = new Set<number>();
    for (let i = 0; i < transcript.words.length; i++) {
      if (!kept.has(i)) removed.add(i);
    }
    return removed;
  }, [transcript, plan]);

  return (
    <div className="transcript-words">
      {transcript.words.map((w, i) => (
        <span
          key={i}
          role="button" tabIndex={0} aria-label={`Review word ${w.w} at ${w.start.toFixed(2)} seconds`}
          className={`tw ${removedRanges.has(i) ? "tw-removed" : ""} ${w.prob < 0.6 && !w.reviewed ? "tw-low" : ""} ${w.reviewed ? (w.original_w ? "tw-auto-corrected" : "tw-reviewed") : ""}`}
          title={
            w.reviewed && w.original_w
              ? `Auto-corrected: ${w.original_w} → ${w.w}\n${w.start.toFixed(2)}s–${w.end.toFixed(2)}s`
              : `${w.start.toFixed(2)}s — ${w.end.toFixed(2)}s (${(w.prob * 100).toFixed(0)}%)`
          }
          onClick={() => { onSeek(w.start); setSelected(i); }}
          onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSeek(w.start); setSelected(i); } }}
        >
          {edits[i]?.text ?? w.w}{" "}
        </span>
      ))}
      {selected !== null && <div className="row" style={{ marginTop: 12, padding: "10px 14px", background: "var(--bg-elevated)", borderRadius: "var(--radius-sm)" }}>
        <span className="muted">{transcript.words[selected].start.toFixed(2)}s</span>
        <input aria-label="Correct selected word" dir="auto" value={edits[selected]?.text ?? transcript.words[selected].w}
          onChange={e => onEdit(selected, { text: e.target.value })} />
        <label className="muted">Start <input aria-label="Word start time" type="number" min="0" step="0.01"
          value={edits[selected]?.start ?? transcript.words[selected].start}
          onChange={e => onEdit(selected, { start: Number(e.target.value) })} /></label>
        <label className="muted">End <input aria-label="Word end time" type="number" min="0" step="0.01"
          value={edits[selected]?.end ?? transcript.words[selected].end}
          onChange={e => onEdit(selected, { end: Number(e.target.value) })} /></label>
        <button className="secondary" onClick={() => onSeek(transcript.words[selected].start)}>Replay</button>
      </div>}
    </div>
  );
}


/* ---------- Visual plan editor ---------- */

function VisualEditor({ jobId, plan, effects, onEffectChange, onUpdate, onDelete, onSeek, onSeekOutput,
  onTransitionChange, onPreviewBoundary }: {
  jobId: string;
  plan: any;
  effects: EffectPreset[];
  onEffectChange: (segmentId: string, effectId: string) => void;
  onUpdate: (path: (string | number)[], value: any) => void;
  onDelete: (arrayPath: string[], index: number) => void;
  onSeek: (t: number) => void;
  onSeekOutput: (t: number) => void;
  onTransitionChange: (boundaryIndex: number, patch: Record<string, any>) => void;
  onPreviewBoundary: (outputTime: number) => void;
}) {
  const [activeEffectSegment, setActiveEffectSegment] = React.useState<string | null>(null);
  const [suggestSegment, setSuggestSegment] = React.useState<string | null>(null);

  const effectAnalysisMap: Record<string, { family: string; reason: string; intensity: number }> = {};
  for (const ea of (plan.effect_analysis || [])) {
    effectAnalysisMap[ea.segment_id] = ea;
  }

  return (
    <div className="visual-editor">
      {plan.cover && <>
        <h3>Opening title overlay</h3>
        <div className="ve-item" role="group" tabIndex={0} aria-label="Seek to cover title"
          onClick={() => onSeekOutput(plan.cover.start || 0)}
          onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSeekOutput(plan.cover.start || 0); } }}>
          <span className="ve-style ve-cta">cover</span>
          <input type="text" value={plan.cover.text || ""}
            aria-label="Cover title"
            onChange={e => onUpdate(["cover", "text"], e.target.value)}
            onClick={e => e.stopPropagation()} />
          <span className="muted">
            {(plan.cover.start || 0).toFixed(2)}s&ndash;{(plan.cover.end || 0).toFixed(2)}s
            {plan.cover.source_segment_id && ` · from ${plan.cover.source_segment_id}`}
          </span>
          {plan.cover.reason && <span className="muted" style={{ fontSize: 11 }}>{plan.cover.reason}</span>}
        </div>
      </>}

      <h3>Preplay video title</h3>
      {plan.poster ? (
        <div className="ve-item">
          <span className="ve-style ve-emphasis">poster</span>
          <input type="text" value={plan.poster.text || ""}
            aria-label="Poster text"
            onChange={e => onUpdate(["poster", "text"], e.target.value)} />
          <label className="muted"><input type="checkbox"
            checked={plan.poster.show_in_video !== false}
            onChange={e => onUpdate(["poster", "show_in_video"], e.target.checked)} />
            Keep this hook visible in portrait video</label>
          <span className="muted">Selected from the video at {(plan.poster.frame_time || 0).toFixed(2)}s; embedded in the MP4 opening frame when rendered.</span>
          {plan.poster.reason && <span className="muted" style={{ fontSize: 11 }}>{plan.poster.reason}</span>}
        </div>
      ) : <p className="muted">No poster text selected.</p>}

      <h3>Segments ({plan.segments?.length || 0})</h3>
      {!!plan.effect_review?.length &&
        <p className="errors" style={{ marginBottom: 8 }}>{plan.effect_review.length} motion effect(s) need a framing check in preview.</p>}
      {plan.segments?.map((seg: any, i: number) => {
        const currentEffect = (plan.visual_effects || []).find((e: any) => e.segment_id === seg.id);
        const analysis = effectAnalysisMap[seg.id];
        const next = plan.segments[i + 1];
        const transition = next ? (plan.transitions || []).find((item: any) =>
          item.from_segment_id === seg.id && item.to_segment_id === next.id) : null;
        const transitionAnalysis = (plan.transition_analysis || []).find((item: any) => item.boundary_index === i);
        const incomingMark = next ? segmentOutputMarks(plan)[i + 1] : null;
        return (<React.Fragment key={seg.id || i}>
        <div key={seg.id || i} className="ve-item" role="group" tabIndex={0} aria-label={`Seek to segment ${seg.id}`}
          onClick={() => onSeek(seg.in)}
          onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSeek(seg.in); } }}>
          <span className="ve-id">{seg.id}</span>
          <span className="muted">{seg.in.toFixed(2)}s &rarr; {seg.out.toFixed(2)}s</span>
          <button className="secondary" style={{ fontSize: 11, padding: "4px 10px" }} onClick={e => {
            e.stopPropagation(); setSuggestSegment(null);
            setActiveEffectSegment(activeEffectSegment === seg.id ? null : seg.id);
          }}>
            Effect: {currentEffect?.type || "Legacy zoom"}
            {analysis && <span className="muted" style={{ fontSize: 10 }}> ({analysis.family} x{analysis.intensity})</span>}
          </button>
          {analysis?.reason && !activeEffectSegment && (
            <span className="muted" style={{ fontSize: 11 }}>{analysis.reason}</span>
          )}
          {activeEffectSegment === seg.id && <label>Choose:
            <select aria-label={`Effect for ${seg.id}`}
              value={currentEffect?.type || ""}
              onClick={e => e.stopPropagation()}
              onChange={e => { onEffectChange(seg.id, e.target.value); setActiveEffectSegment(null); }}>
              <option value="">Legacy zoom</option>
              {[...new Set(effects.map(effect => effect.motion))].map(motion => (
                <optgroup key={motion} label={motion.replace(/_/g, " ")}>
                  {effects.filter(effect => effect.motion === motion).map(effect =>
                    <option key={effect.id} value={effect.id}>{effect.label}</option>)}
                </optgroup>
              ))}
            </select>
          </label>}
          <button className="secondary" style={{ fontSize: 10, padding: "3px 8px" }} title="Suggest alternative effects"
            onClick={e => { e.stopPropagation(); setSuggestSegment(suggestSegment === seg.id ? null : seg.id); setActiveEffectSegment(null); }}>
            Alt
          </button>
          {suggestSegment === seg.id && (
            <div style={{ marginTop: 4, padding: "6px 10px", background: "var(--bg-elevated)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                {analysis ? `Family: ${analysis.family} | Energy: ${analysis.intensity}/5 | ${analysis.reason}` : "No analysis available"}
              </div>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {effects.filter(e => currentEffect?.type && e.id !== currentEffect.type).slice(0, 2).map(alt => (
                  <button key={alt.id} className="secondary" style={{ fontSize: 11, padding: "3px 8px" }}
                    onClick={e2 => { e2.stopPropagation(); onEffectChange(seg.id, alt.id); setSuggestSegment(null); }}>
                    {alt.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {!(plan.visual_effects || []).some((effect: any) => effect.segment_id === seg.id) && <><label>Zoom from:
            <input type="number" step={0.05} min={1} max={1.5}
              value={seg.zoom?.from ?? 1}
              onChange={e => onUpdate(["segments", i, "zoom", "from"], +e.target.value)}
            />
          </label>
          <label>to:
            <input type="number" step={0.05} min={1} max={1.5}
              value={seg.zoom?.to ?? 1}
              onChange={e => onUpdate(["segments", i, "zoom", "to"], +e.target.value)}
            />
          </label>
          </>}
          <button className="danger-sm" aria-label={`Remove segment ${seg.id}`} onClick={e => { e.stopPropagation(); onDelete(["segments"], i); }}>&#10005;</button>
        </div>
        {next && <div className="ve-item" style={{ borderLeft: "3px solid #8b5cf6", marginLeft: 12 }}>
          <span className="ve-style ve-normal">{seg.id} &rarr; {next.id}</span>
          <label>Transition <select aria-label={`Transition ${seg.id} to ${next.id}`}
            value={transition?.type || "hard_cut"}
            onChange={e => onTransitionChange(i, { type: e.target.value })}>
            <option value="hard_cut">Hard cut</option>
            <option value="crossfade">Crossfade</option>
            <option value="directional">Directional slide</option>
            <option value="zoom">Boundary zoom</option>
          </select></label>
          {(transition?.type || "hard_cut") !== "hard_cut" && <>
            <label>Frames <input type="number" min={2} max={plan.transition_context?.output_kind === "post" ? 8 : plan.transition_context?.output_kind === "story" ? 10 : 12}
              value={transition?.duration_frames || 6}
              onChange={e => onTransitionChange(i, { duration_frames: Number(e.target.value) })} /></label>
            {transition?.type === "directional" && <>
              <label>Direction <select value={transition?.direction || "left"}
                onChange={e => onTransitionChange(i, { direction: e.target.value })}>
                <option value="left">Left</option><option value="right">Right</option>
                <option value="up">Up</option><option value="down">Down</option>
              </select></label>
              <label>Intensity <input type="range" min={0.5} max={1} step={0.05}
                value={transition?.intensity || 1}
                onChange={e => onTransitionChange(i, { intensity: Number(e.target.value) })} /></label>
            </>}
            {transition?.type === "zoom" && <>
              <label>Mode <select value={transition?.zoom_mode || "zoom_in"}
                onChange={e => onTransitionChange(i, { zoom_mode: e.target.value })}>
                <option value="zoom_in">Zoom in</option><option value="zoom_out">Zoom out</option>
              </select></label>
              <label>Scale <input type="number" min={1.02} max={1.5} step={0.01}
                value={transition?.zoom_scale || 1.15}
                onChange={e => onTransitionChange(i, { zoom_scale: Number(e.target.value) })} /></label>
            </>}
          </>}
          <span className="muted" style={{ fontSize: 11 }}>{transition?.locked ? "Manual · locked" : `${transition?.source || "default"}`}</span>
          <span className={transition?.type === "directional" || transition?.type === "zoom" ? "errors" : "muted"} style={{ fontSize: 11, padding: 0, background: "none", border: "none" }}>
            Premiere: {transition?.type === "crossfade" ? "Cross Dissolve" :
              transition?.type === "directional" ? "Cross Dissolve fallback" :
              transition?.type === "zoom" ? "Cross Dissolve fallback" : "Cut"}
          </span>
          {transitionAnalysis?.reason && <span className="muted" style={{ fontSize: 11 }}>{transitionAnalysis.reason}</span>}
          <button className="secondary" style={{ fontSize: 11, padding: "3px 8px" }} onClick={() => onPreviewBoundary(incomingMark?.start || 0)}>
            Preview boundary
          </button>
        </div>}
        </React.Fragment>);
      })}

      <h3>Captions ({plan.captions?.length || 0})</h3>
      {!!plan.caption_review?.length &&
        <p className="errors" style={{ marginBottom: 8 }}>{plan.caption_review.length} caption(s) need audio review.</p>}
      {plan.captions?.map((cap: any, i: number) => (
        <div key={i} className="ve-item" role="group" tabIndex={0} aria-label={`Seek to caption ${i + 1}`}
          onClick={() => onSeekOutput(cap.start)}
          onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSeekOutput(cap.start); } }}>
          <span className={`ve-style ve-${cap.style}`}>{cap.style}</span>
          {plan.caption_review?.some((warning: any) => warning.caption_index === i) &&
            <span title={plan.caption_review.find((warning: any) => warning.caption_index === i)?.source_text} style={{ color: "var(--warning)" }}>
              &#9888;
            </span>}
          <input type="text" value={cap.text} aria-label={`Caption ${i + 1} text`}
            onChange={e => onUpdate(["captions", i, "text"], e.target.value)}
            onClick={e => e.stopPropagation()}
          />
          <span className="muted" style={{ fontSize: 11 }}>{cap.start.toFixed(2)}s&ndash;{cap.end.toFixed(2)}s</span>
          <button className="danger-sm" aria-label={`Remove caption ${i + 1}`} onClick={e => { e.stopPropagation(); onDelete(["captions"], i); }}>&#10005;</button>
        </div>
      ))}

      <h3>B-roll ({plan.broll?.length || 0})</h3>
      {plan.broll?.map((b: any, i: number) => {
        const resolutions = plan._asset_resolutions?.broll || [];
        const resolution = resolutions.find((r: any) => r.index === i);
        const alternatives = resolution?.alternatives || [];
        return (
          <div key={i} className="ve-item" style={{ flexDirection: "column", alignItems: "stretch" }}>
            <div role="group" style={{ display: "flex", alignItems: "center", gap: 8 }} tabIndex={0} aria-label={`Seek to B-roll ${i + 1}`}
              onClick={() => onSeekOutput(b.at)}
              onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSeekOutput(b.at); } }}>
              <span className="muted" style={{ fontSize: 11 }}>@{b.at.toFixed(2)}s, {b.duration.toFixed(1)}s</span>
              <span style={{ flex: 1 }}>
                {b.query && <span className="tag" style={{ marginRight: 6 }}>{b.query}</span>}
                <span className="muted" style={{ fontSize: 11 }}>{b.file?.split("/").pop()}</span>
              </span>
              <button className="danger-sm" aria-label={`Remove B-roll ${i + 1}`} onClick={e => { e.stopPropagation(); onDelete(["broll"], i); }}>&#10005;</button>
            </div>
            {alternatives.length > 0 && (
              <div className="broll-alternatives">
                {alternatives.map((alt: string, ai: number) => (
                  <button key={ai} className={`broll-alt-card ${b.file === alt ? "active" : ""}`}
                    onClick={() => onUpdate(["broll", i, "file"], alt)}
                    title={alt}>
                    {alt.split("/").pop()}
                  </button>
                ))}
              </div>
            )}
          </div>
        );
      })}

      <h3>Music</h3>
      <MusicPicker jobId={jobId} file={plan.music?.file}
        onSelect={file => onUpdate(["music"], { file, volume_db: plan.music?.volume_db ?? -24, duck: plan.music?.duck ?? [] })} />
      {plan.music ? (
        <div className="ve-item" style={{ flexDirection: "column", alignItems: "stretch" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontWeight: 600 }}>{plan.music.file?.split("/").pop()}</span>
            <span className="muted" style={{ fontSize: 11 }}>Volume: {plan.music.volume_db} dB</span>
            <span className="muted" style={{ fontSize: 11 }}>Duck ranges: {plan.music.duck?.length || 0}</span>
            <button className="danger-sm" aria-label="Remove background music" onClick={() => onUpdate(["music"], null)}>&#10005;</button>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6 }}>Volume (dB)
              <input type="range" min={-30} max={0} step={1}
                value={plan.music.volume_db ?? -14}
                onChange={e => onUpdate(["music", "volume_db"], Number(e.target.value))} />
              <span style={{ fontFamily: "monospace", fontSize: 12, minWidth: 36 }}>{plan.music.volume_db ?? -14}</span>
            </label>
            <button className="secondary" style={{ fontSize: 11, padding: "4px 10px" }}
              onClick={() => {
                if (!plan.segments?.length) return;
                const marks = segmentOutputMarks(plan);
                const ducks = marks.map(({ start, end }: any) => ({
                  start, end, volume_db: Math.min(-18, (plan.music.volume_db ?? -14) - 8)
                }));
                onUpdate(["music", "duck"], ducks);
              }}>
              Auto-duck speech
            </button>
            <button className="secondary" style={{ fontSize: 11, padding: "4px 10px" }}
              onClick={() => onUpdate(["music", "duck"], [])}>
              Clear duck
            </button>
          </div>
        </div>
      ) : <p className="muted">No background music selected.</p>}

      <h3>SFX ({plan.sfx?.length || 0})</h3>
      {plan.sfx?.map((s: any, i: number) => (
        <div key={i} className="ve-item" role="group" tabIndex={0} aria-label={`Seek to sound effect ${i + 1}`}
          onClick={() => onSeekOutput(s.at)}
          onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSeekOutput(s.at); } }}>
          <span className="muted" style={{ fontSize: 11 }}>@{s.at.toFixed(2)}s</span>
          <span>{s.file === plan.generation_meta?.narration_file ? "Voiceover / گویندگی: " : ""}{s.file?.split("/").pop()}</span>
          <button className="danger-sm" aria-label={`Remove sound effect ${i + 1}`} onClick={e => { e.stopPropagation(); onDelete(["sfx"], i); }}>&#10005;</button>
        </div>
      ))}
    </div>
  );
}


function computePlanDiff(original: any, edited: any): any[] {
  const events: any[] = [];
  const origSegs = new Map<string, any>((original.segments || []).map((s: any): [string, any] => [s.id, s]));
  const editSegs = new Map<string, any>((edited.segments || []).map((s: any): [string, any] => [s.id, s]));

  for (const [id] of origSegs) {
    if (!editSegs.has(id)) events.push({ change_type: "segment_removed", segment_id: id });
  }
  for (const [id] of editSegs) {
    if (!origSegs.has(id)) events.push({ change_type: "segment_added", segment_id: id });
  }
  for (const [id, o] of origSegs) {
    const e = editSegs.get(id);
    if (!e) continue;
    if (Math.abs((o.in ?? 0) - (e.in ?? 0)) > 0.05 || Math.abs((o.out ?? 0) - (e.out ?? 0)) > 0.05) {
      events.push({ change_type: "segment_trimmed", segment_id: id,
        original_duration: +(o.out - o.in).toFixed(3), edited_duration: +(e.out - e.in).toFixed(3) });
    }
  }

  const origEffects = new Map((original.visual_effects || []).map((e: any) => [e.segment_id, e.type]));
  const editEffects = new Map((edited.visual_effects || []).map((e: any) => [e.segment_id, e.type]));
  for (const [sid, oldType] of origEffects) {
    const newType = editEffects.get(sid);
    if (newType && newType !== oldType) {
      events.push({ change_type: "effect_changed", segment_id: sid, old_effect: oldType, new_effect: newType });
    }
  }

  const oCaps = original.captions || [];
  const eCaps = edited.captions || [];
  for (let i = 0; i < Math.min(oCaps.length, eCaps.length); i++) {
    if (oCaps[i]?.text !== eCaps[i]?.text) {
      events.push({ change_type: "caption_edited", index: i, old_text: oCaps[i].text, new_text: eCaps[i].text });
    }
  }
  if (eCaps.length > oCaps.length) events.push({ change_type: "captions_added", count: eCaps.length - oCaps.length });
  if (eCaps.length < oCaps.length) events.push({ change_type: "captions_removed", count: oCaps.length - eCaps.length });

  if (JSON.stringify(original.music) !== JSON.stringify(edited.music)) events.push({ change_type: "music_changed" });
  if ((original.broll || []).length !== (edited.broll || []).length) {
    events.push({ change_type: "broll_changed", original_count: (original.broll || []).length, edited_count: (edited.broll || []).length });
  }

  return events;
}
