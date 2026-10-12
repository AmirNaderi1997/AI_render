import React from "react";

export function segmentOutputMarks(plan: any): { seg: any; start: number; end: number }[] {
  const segments = plan?.segments || [];
  const fps = plan?.canvas?.fps || 30;
  const transitions = new Map<string, number>((plan?.transitions || []).map((item: any) =>
    [`${item.from_segment_id}\u0000${item.to_segment_id}`, item.duration_frames || 0]));
  let acc = 0;
  return segments.map((seg: any, index: number) => {
    const start = acc;
    const end = start + Math.round((seg.out - seg.in) * fps) / fps;
    acc = end;
    if (index < segments.length - 1) {
      acc -= (transitions.get(`${seg.id}\u0000${segments[index + 1].id}`) || 0) / fps;
    }
    return { seg, start, end };
  });
}

/** Map an output-timeline time to the incoming raw clip at that point. */
export function outputToRaw(planOrSegments: any, t: number): number {
  const plan = Array.isArray(planOrSegments) ? { segments: planOrSegments } : planOrSegments;
  const marks = segmentOutputMarks(plan);
  for (let index = marks.length - 1; index >= 0; index--) {
    const { seg, start, end } = marks[index];
    if (t >= start - 1e-6 && t < end) return seg.in + Math.max(0, t - start);
  }
  for (const s of plan.segments || []) {
    const len = s.out - s.in;
    if (t < len) return s.in + Math.max(0, t);
  }
  const last = (plan.segments || [])[plan.segments.length - 1];
  return last ? last.out : 0;
}

export function Timeline({ plan, onSeek }: { plan: any; onSeek: (t: number) => void }) {
  if (!plan?.segments?.length) return <p className="muted">No timeline yet. Generate or add a plan to see its tracks.</p>;

  const segMarks = segmentOutputMarks(plan);
  const outDur = Math.max(...segMarks.map(item => item.end), 0);
  const seek = (t: number) => onSeek(outputToRaw(plan, t));
  const pct = (t: number) => Math.max(0, Math.min(100, (t / outDur) * 100));

  const lane = (label: string, items: React.ReactNode) => (
    <div className="lane">
      <div className="lane-label">{label}</div>
      <div className="lane-track">{items}</div>
    </div>
  );

  const box = (cls: string, start: number, end: number, text: string, onClick: () => void) => (
    <button type="button" key={cls + start + text} className={`lane-item ${cls}`}
      style={{ left: `${pct(start)}%`, width: `${Math.max(pct(end - start), 0.5)}%` }}
      title={`${text} (${start.toFixed(2)}s–${end.toFixed(2)}s)`}
      aria-label={`Seek to ${text} at ${start.toFixed(1)} seconds`}
      onClick={onClick}>{text}</button>
  );

  return (
    <div className="timeline" aria-label="Edit timeline">
      {lane("Segments", segMarks.map(({ seg, start, end }: any) =>
        box("c-seg", start, end, seg.id, () => onSeek(seg.in))
      ))}
      {lane("Effects", segMarks
        .filter(({ seg }: any) => (plan.visual_effects || []).some((effect: any) => effect.segment_id === seg.id)
          || (seg.zoom && (seg.zoom.from !== 1 || seg.zoom.to !== 1)))
        .map(({ seg, start, end }: any) =>
          box("c-zoom", start, end,
            (plan.visual_effects || []).find((effect: any) => effect.segment_id === seg.id)?.type
              || `${seg.zoom.from}→${seg.zoom.to}`, () => onSeek(seg.in))
        ))}
      {lane("Transitions", (plan.transitions || []).map((transition: any) => {
        const incoming = segMarks.find(item => item.seg.id === transition.to_segment_id);
        if (!incoming) return null;
        const duration = (transition.duration_frames || 0) / (plan.canvas?.fps || 30);
        return box(transition.type === "hard_cut" ? "c-seg" : "c-zoom",
          Math.max(0, incoming.start), Math.max(incoming.start + duration, incoming.start + 0.02),
          transition.type, () => seek(incoming.start));
      }))}
      {plan.cover && lane("Opening title", [box("c-cap", plan.cover.start || 0, plan.cover.end || 2.5,
        plan.cover.text, () => seek(plan.cover.start || 0))])}
      {lane("Captions", (plan.captions || []).map((c: any) =>
        box("c-cap", c.start, c.end, c.text, () => seek(c.start))
      ))}
      {lane("B-roll", (plan.broll || []).map((b: any) =>
        box("c-broll", b.at, b.at + b.duration, (b.file || "").split("/").pop() || "broll", () => seek(b.at))
      ))}
      {lane("Music", plan.music
        ? [box("c-music", 0, outDur, `${(plan.music.file || "").split("/").pop() || "music"} ${plan.music.volume_db}dB`, () => seek(0))]
        : [])}
      {lane("SFX", (plan.sfx || []).map((s: any) =>
        box("c-sfx", s.at, s.at + 0.6, (s.file || "").split("/").pop() || "sfx", () => seek(s.at))
      ))}
    </div>
  );
}
