import React from "react";
import { useParams } from "react-router-dom";
import { api } from "./api";

export default function Render() {
  const { id } = useParams();
  const [s, setS] = React.useState<any>(null);

  React.useEffect(() => {
    if (!id) return;
    const tick = () => api.renderStatus(id).then(setS).catch(() => {});
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [id]);

  if (!id || !s) return <p>Loading…</p>;
  const finished = s.status === "done";

  return (
    <div>
      <h1>Render — {id}</h1>
      <div className="card">
        <div>Status: <b>{s.status}</b> {s.message && <span className="muted">— {s.message}</span>}</div>
        <div className="progress" style={{ marginTop: 12 }}>
          <div style={{ width: `${s.progress}%` }} />
        </div>
        <div className="muted" style={{ marginTop: 4 }}>{s.progress}%</div>
      </div>

      {finished && s.output && (
        <div className="card">
          <h2>Latest export: {s.output}</h2>
          <video src={api.exportUrl(id, s.output)} controls />
          <div style={{ marginTop: 8 }}>
            <a href={api.exportUrl(id, s.output)} download><button>Download</button></a>
          </div>
        </div>
      )}

      {s.versions?.length > 0 && (
        <div className="card">
          <h2>Previous versions</h2>
          <ul>
            {s.versions.map((v: string) => (
              <li key={v}><a href={api.exportUrl(id, v)}>{v}</a></li>
            ))}
          </ul>
        </div>
      )}

      <a href={`/jobs/${id}`}>← Back to plan</a>
    </div>
  );
}
