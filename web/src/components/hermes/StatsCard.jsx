export default function StatsCard({ label, value, note, icon, trend }) {
  return <article className="hm-stat hm-panel"><div className="hm-stat-top"><span>{label}</span><span className="hm-stat-icon" aria-hidden="true">{icon}</span></div><strong>{value}</strong><div className="hm-stat-bottom">{trend != null && <span className={trend >= 0 ? 'hm-positive' : 'hm-negative'}>{trend >= 0 ? '↗' : '↘'} {Math.abs(trend)}%</span>}<small>{note}</small></div></article>;
}
