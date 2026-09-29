import React from "react";

export function Timeline({ plan, onSeek }: { plan: any; onSeek: (t: number) => void }) {
  if (!plan?.segments?.length) return <p className="muted">No timeline yet.</p>;

  const outDur = plan.segments.reduce((a: number, s: any) => a + (s.out - s.in), 0);
  // seg-boundaries in output timeline
  let acc = 0;
  const segMarks = plan.segments.map((s: any) => {
    const start = acc;
    const end = acc + (s.out - s.in);
    acc = end;
    return { seg: s, start, end };
  });
  const pct = (t: number) => Math.max(0, Math.min(100, (t / outDur) * 100));

  const lane = (label: string, items: React.ReactNode) => (
    <div className="lane">
      <div className="lane-label">{label}</div>
      <div className="lane-track">{items}</div>
    </div>
  );

  const box = (cls: string, start: number, end: number, text: string, onClick: () => void) => (
    <div key={cls + start + text} className={`lane-item ${cls}`}
      style={{ left: `${pct(start)}%`, width: `${Math.max(pct(end - start), 0.5)}%` }}
      title={`${text} (${start.toFixed(2)}s–${end.toFixed(2)}s)`}
      onClick={onClick}>{text}</div>
  );

  return (
    <div className="timeline">
      {lane("Segments", segMarks.map(({ seg, start, end }: any) =>
        box("c-seg", start, end, seg.id, () => onSeek(start))
      ))}
      {lane("Zoom", segMarks
        .filter(({ seg }: any) => seg.zoom && (seg.zoom.from !== 1 || seg.zoom.to !== 1))
        .map(({ seg, start, end }: any) =>
          box("c-zoom", start, end, `${seg.zoom.from}→${seg.zoom.to}`, () => onSeek(start))
        ))}
      {lane("Captions", (plan.captions || []).map((c: any) =>
        box("c-cap", c.start, c.end, c.text, () => onSeek(c.start))
      ))}
      {lane("B-roll", (plan.broll || []).map((b: any) =>
        box("c-broll", b.at, b.at + b.duration, b.file.split("/").pop(), () => onSeek(b.at))
      ))}
      {lane("Music", plan.music
        ? [box("c-music", 0, outDur, `${plan.music.file.split("/").pop()} ${plan.music.volume_db}dB`, () => onSeek(0))]
        : [])}
      {lane("SFX", (plan.sfx || []).map((s: any) =>
        box("c-sfx", s.at, s.at + 0.6, s.file.split("/").pop(), () => onSeek(s.at))
      ))}
    </div>
  );
}
