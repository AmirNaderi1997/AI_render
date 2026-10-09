import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import hermesApi from '../../services/hermesApi';
import AccountCard from '../../components/hermes/AccountCard';
import PostCard from '../../components/hermes/PostCard';
import StatsCard from '../../components/hermes/StatsCard';
import { array, message, number, percent } from './hermesUtils';
import HermesSettings from './HermesSettings';

export default function HermesDashboard() {
  const [accounts, setAccounts] = useState([]);
  const [posts, setPosts] = useState([]);
  const [insights, setInsights] = useState({});
  const [postInsights, setPostInsights] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    Promise.all([hermesApi.getAccounts(), hermesApi.getPosts()]).then(async ([a, p]) => {
      const [results, postResults] = await Promise.all([
        Promise.allSettled(array(a).map((account) => hermesApi.getAccountAnalytics(account.id))),
        Promise.allSettled(array(a).map((account) => hermesApi.getPostAnalytics(account.id))),
      ]);
      if (alive) { setAccounts(array(a)); setPosts(array(p)); setInsights(Object.fromEntries(array(a).map((account, i) => [account.id, results[i].status === 'fulfilled' ? results[i].value : null]))); setPostInsights(postResults.flatMap((result) => result.status === 'fulfilled' ? array(result.value) : [])); }
    }).catch((e) => alive && setError(message(e))).finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, []);
  const upcoming = posts.filter((post) => post.status === 'scheduled' && new Date(post.scheduled_at) > new Date()).sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at)).slice(0, 5);
  const latest = Object.values(insights).filter(Boolean);
  const followerValues = latest.map((item) => item.followers).filter((value) => typeof value === 'number');
  const followerCount = followerValues.length ? followerValues.reduce((sum, value) => sum + value, 0) : null;
  const engagementValues = postInsights.map((item) => item.engagement_rate).filter((value) => typeof value === 'number');
  const engagement = engagementValues.length ? engagementValues.reduce((sum, value) => sum + value, 0) / engagementValues.length : null;
  return <div className="hm-page hm-rise">
    <div className="hm-page-head"><div><span className="hm-eyebrow">WORKSPACE OVERVIEW</span><h2>Your publishing command center</h2><p>Everything happening across your connected Instagram accounts.</p></div><Link className="hm-btn hm-btn-primary" to="/hermes/post/new">＋ New post</Link></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}
    {loading ? <div className="hm-loading" role="status">Loading your studio…</div> : <>
      <div className="hm-stats"><StatsCard label="Total posts" value={number(posts.length)} note="All drafts and published" icon="▤" /><StatsCard label="Scheduled" value={number(upcoming.length)} note="Coming up next" icon="◷" /><StatsCard label="Engagement rate" value={percent(engagement)} note="Average measured posts" icon="↗" /><StatsCard label="Followers" value={number(followerCount)} note={followerCount == null ? 'No insight available' : 'Across connected accounts'} icon="◎" /></div>
      {!accounts.length && <div className="hm-hero-cta hm-panel"><div className="hm-hero-mark">◎</div><div><span className="hm-eyebrow">GET STARTED</span><h3>Connect your Instagram account</h3><p>Link a professional account to schedule posts, track performance and get AI suggestions.</p></div><Link className="hm-btn hm-btn-primary" to="/hermes/connect">Connect Instagram ↗</Link></div>}
      <div className="hm-two-column"><section><div className="hm-section-title"><div><h3>Connected accounts</h3><p>{accounts.length} account{accounts.length === 1 ? '' : 's'} in your studio</p></div><Link to="/hermes/connect">Manage accounts →</Link></div>{accounts.length ? <div className="hm-stack">{accounts.map((account) => <AccountCard key={account.id} account={account} followers={insights[account.id]?.followers} />)}</div> : <div className="hm-empty hm-panel">No accounts connected yet.</div>}</section><section><div className="hm-section-title"><div><h3>Upcoming posts</h3><p>Your next five scheduled posts</p></div><Link to="/hermes/scheduler">Open calendar →</Link></div>{upcoming.length ? <div className="hm-stack">{upcoming.map((post) => <PostCard key={post.id} post={post} />)}</div> : <div className="hm-empty hm-panel">Your calendar is clear. Create a post to start planning.</div>}</section></div>
      <div className="hm-quick-actions"><Link to="/hermes/post/new"><span>＋</span><strong>Create a post</strong><small>Write and schedule content</small></Link><Link to="/hermes/analytics"><span>◴</span><strong>View analytics</strong><small>See what resonates</small></Link><Link to="/hermes/advisor"><span>✦</span><strong>Ask the advisor</strong><small>Find your next idea</small></Link></div>
    </>}
    <HermesSettings />
  </div>;
}
