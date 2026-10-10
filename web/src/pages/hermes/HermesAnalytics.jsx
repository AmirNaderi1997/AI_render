import { useCallback, useEffect, useMemo, useState } from 'react';
import { format, subDays } from 'date-fns';
import { Link } from 'react-router-dom';
import hermesApi from '../../services/hermesApi';
import EngagementChart from '../../components/hermes/EngagementChart';
import StatsCard from '../../components/hermes/StatsCard';
import { array, message, number, percent } from './hermesUtils';

const snapshotKey = (id) => `hermes_analytics_snapshots_${id}`;
function snapshots(id) { try { return array(JSON.parse(localStorage.getItem(snapshotKey(id)))); } catch { return []; } }
function saveSnapshot(id, insight) {
  if (!insight) return snapshots(id);
  const day = insight.date || new Date().toISOString().slice(0, 10);
  const next = [...snapshots(id).filter((row) => row.date !== day), { date: day, followers: insight.followers, reach: insight.reach, impressions: insight.impressions }].sort((a, b) => a.date.localeCompare(b.date)).slice(-90);
  localStorage.setItem(snapshotKey(id), JSON.stringify(next));
  return next;
}

export default function HermesAnalytics() {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState('');
  const [insight, setInsight] = useState(null);
  const [postInsights, setPostInsights] = useState([]);
  const [posts, setPosts] = useState([]);
  const [history, setHistory] = useState([]);
  const [range, setRange] = useState('30d');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [sort, setSort] = useState('engagement_rate');
  const [busy, setBusy] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => { hermesApi.getAccounts().then((items) => { setAccounts(array(items)); setAccountId(items?.[0]?.id || ''); }).catch((e) => setError(message(e))).finally(() => setLoadingAccounts(false)); }, []);
  const load = useCallback(async (force = false) => {
    if (!accountId) return;
    setBusy(true); setError('');
    try { const [data, postData, ownPosts] = await Promise.all([force ? hermesApi.refreshAnalytics(accountId) : hermesApi.getAccountAnalytics(accountId), force ? Promise.resolve(null) : hermesApi.getPostAnalytics(accountId), hermesApi.getPosts()]);
      const current = force ? data.account : data; setInsight(current); setPostInsights(array(force ? data.posts : postData)); setPosts(array(ownPosts)); setHistory(saveSnapshot(accountId, current));
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }, [accountId]);
  useEffect(() => { load(); }, [load]);
  const startDate = range === 'custom' ? customStart : format(subDays(new Date(), Number.parseInt(range) - 1), 'yyyy-MM-dd');
  const endDate = range === 'custom' ? customEnd : format(new Date(), 'yyyy-MM-dd');
  const series = history.filter((row) => (!startDate || row.date >= startDate) && (!endDate || row.date <= endDate)).map((row) => ({ ...row, label: format(new Date(`${row.date}T12:00:00`), 'MMM d') }));
  const postRows = useMemo(() => postInsights.map((row) => ({ ...row, post: posts.find((post) => post.id === row.post_id) })).filter((row) => { const date = row.post?.posted_at || row.fetched_at; return (!startDate || date?.slice(0, 10) >= startDate) && (!endDate || date?.slice(0, 10) <= endDate); }).sort((a, b) => sort === 'date' ? new Date(b.post?.posted_at || b.fetched_at) - new Date(a.post?.posted_at || a.fetched_at) : (b[sort] || 0) - (a[sort] || 0)), [postInsights, posts, startDate, endDate, sort]);
  const measuredEngagement = postRows.filter((row) => typeof row.engagement_rate === 'number');
  const engagement = measuredEngagement.length ? measuredEngagement.reduce((sum, row) => sum + row.engagement_rate, 0) / measuredEngagement.length : null;
  if (loadingAccounts) return <div className="hm-page hm-rise"><div className="hm-loading" role="status">Loading analytics accounts…</div></div>;
  return <div className="hm-page hm-rise"><div className="hm-page-head"><div><span className="hm-eyebrow">PERFORMANCE INTELLIGENCE</span><h2>Know what resonates</h2><p>Instagram insights and locally collected account snapshots.</p></div><button className="hm-btn hm-btn-primary" onClick={() => load(true)} disabled={busy || !accountId} title={(busy || !accountId) ? "Choose an account first." : undefined}>↻ Refresh data</button></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}
    {busy && <div className="hm-loading" role="status">Loading performance data…</div>}
    {!accounts.length ? <div className="hm-empty hm-panel">Connect an account to view analytics. <Link to="/hermes/connect">Connect Instagram →</Link></div> : <><div className="hm-filters"><label>Account<select value={accountId} onChange={(e) => setAccountId(e.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>@{account.username}</option>)}</select></label><div className="hm-segment">{['7d', '30d', '90d', 'custom'].map((option) => <button key={option} aria-pressed={range === option} className={range === option ? 'active' : ''} onClick={() => setRange(option)}>{option === 'custom' ? 'Custom' : option}</button>)}</div>{range === 'custom' && <><label>From<input type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} /></label><label>To<input type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} /></label></>}</div>
      <div className="hm-stats"><StatsCard label="Followers" value={number(insight?.followers)} note="Current account count" icon="◎" /><StatsCard label="Reach" value={number(insight?.reach)} note="Latest Instagram insight" icon="↗" /><StatsCard label="Impressions" value={number(insight?.impressions)} note="Latest Instagram insight" icon="◴" /><StatsCard label="Engagement rate" value={percent(engagement)} note="Average measured posts" icon="♡" /></div>
      <div className="hm-chart-grid"><section className="hm-panel hm-chart-panel"><div className="hm-section-title"><div><h3>Audience growth</h3><p>Followers from saved daily snapshots</p></div></div><EngagementChart data={series} metrics={['followers']} /></section><section className="hm-panel hm-chart-panel"><div className="hm-section-title"><div><h3>Reach & impressions</h3><p>Saved daily account insights</p></div></div><EngagementChart data={series} metrics={['reach', 'impressions']} /></section></div>
      <section className="hm-panel hm-chart-panel"><div className="hm-section-title"><div><h3>Post comparison</h3><p>Reach and impressions from published posts</p></div></div><EngagementChart type="bar" data={postRows.slice(0, 12).reverse().map((row, i) => ({ label: row.post?.posted_at?.slice(5, 10) || `Post ${i + 1}`, reach: row.reach, impressions: row.impressions }))} metrics={['reach', 'impressions']} /></section>
      <section className="hm-panel hm-table-panel"><div className="hm-section-title"><div><h3>Post performance</h3><p>Latest measured metrics per published post</p></div><label>Sort by<select value={sort} onChange={(e) => setSort(e.target.value)}><option value="engagement_rate">Engagement</option><option value="reach">Reach</option><option value="date">Date</option></select></label></div><div className="hm-table-scroll"><table><thead><tr><th>Post</th><th>Date</th><th>Reach</th><th>Impressions</th><th>Engagement</th></tr></thead><tbody>{postRows.length ? postRows.map((row) => <tr key={row.id}><td>{row.post?.caption?.slice(0, 55) || row.post_id}</td><td>{row.post?.posted_at?.slice(0, 10) || '—'}</td><td>{number(row.reach)}</td><td>{number(row.impressions)}</td><td>{percent(row.engagement_rate)}</td></tr>) : <tr><td colSpan="5" className="hm-empty-cell">No published post insights for this period.</td></tr>}</tbody></table></div></section><p className="hm-footnote">Hermes exposes the latest account insight. Trend charts begin accumulating daily snapshots in this browser as you use Analytics; earlier history is not available from the API.</p></>}
  </div>;
}
