import { ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';

export default function EngagementChart({ data = [], type = 'line', metrics = ['reach', 'impressions'], height = 270 }) {
  if (!data.length) return <div className="hm-chart-empty">No measured data for this period yet.</div>;
  const colors = ['#8b82ff', '#4dd4c7', '#ffb36b'];
  const parts = <><CartesianGrid stroke="rgba(255,255,255,.07)" vertical={false} /><XAxis dataKey="label" stroke="#858ba0" tickLine={false} axisLine={false} fontSize={11} /><YAxis stroke="#858ba0" tickLine={false} axisLine={false} fontSize={11} width={38} /><Tooltip contentStyle={{ background: '#1b1e2c', border: '1px solid rgba(255,255,255,.12)', borderRadius: 12 }} /><Legend />{metrics.map((metric, index) => type === 'bar' ? <Bar key={metric} dataKey={metric} fill={colors[index]} radius={[5, 5, 0, 0]} /> : <Line key={metric} dataKey={metric} stroke={colors[index]} strokeWidth={2.5} dot={{ r: 4 }} activeDot={{ r: 6 }} connectNulls />)}</>;
  return <div className="hm-chart" style={{ height }}><ResponsiveContainer width="100%" height="100%">{type === 'bar' ? <BarChart data={data}>{parts}</BarChart> : <LineChart data={data}>{parts}</LineChart>}</ResponsiveContainer></div>;
}
