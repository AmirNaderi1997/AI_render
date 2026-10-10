import { useEffect, useState } from 'react';
import { addDays, format } from 'date-fns';
import { Link, useNavigate } from 'react-router-dom';
import hermesApi from '../../services/hermesApi';
import { array, fromInputDateTime, message, tags } from './hermesUtils';

function plannedDate(item) {
  const today = new Date();
  for (let offset = 0; offset < 7; offset++) {
    const date = addDays(today, offset);
    if (format(date, 'EEEE').toLowerCase().startsWith(String(item.weekday || '').toLowerCase().slice(0, 3))) {
      const time = /^\d{2}:\d{2}$/.test(item.local_time || '') ? item.local_time : '12:00';
      const candidate = `${format(date, 'yyyy-MM-dd')}T${time}`;
      if (new Date(candidate) > today) return candidate;
    }
  }
  return `${format(addDays(today, 1), 'yyyy-MM-dd')}T12:00`;
}

export default function HermesContentPlan() {
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState('');
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('');
  const [frequency, setFrequency] = useState(5);
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => { hermesApi.getAccounts().then((list) => { setAccounts(array(list)); setAccountId(list?.[0]?.id || ''); }).catch((e) => setError(message(e))).finally(() => setLoadingAccounts(false)); }, []);
  async function generate() {
    if (!accountId || !topic.trim()) { setError('Connect an account and enter a content niche.'); return; }
    setBusy(true); setError(''); setNotice('');
    try { const result = await hermesApi.getContentPlan({ account_id: accountId, topic: `${topic.trim()} | Target audience: ${audience.trim() || 'general'}`, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Tehran', posts_per_week: Number(frequency) });
      const days = array(result.days).slice(0, 7);
      setItems(days.map((item, index) => ({ ...item, key: index, caption: item.caption || item.caption_idea || '', hashtags: array(item.hashtags).join(', '), media_url: '', date_time: plannedDate(item) })));
      if (!days.length) setNotice('The advisor returned no plan items. Try a more specific niche.');
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  function update(index, key, value) { setItems((current) => current.map((item, i) => i === index ? { ...item, [key]: value } : item)); }
  async function apply() {
    if (!items.length) return;
    const invalid = items.find((item) => !/^https:\/\/[^\s]+$/i.test(item.media_url) || !item.date_time || new Date(item.date_time) <= new Date() || item.caption.length > 2200 || tags(item.hashtags).length > 30);
    if (invalid) { setError('Each item needs a public HTTPS media URL, a future time, and a valid caption and hashtag count.'); return; }
    if (!window.confirm(`Create and schedule ${items.length} posts?`)) return;
    setBusy(true); setError('');
    const created = [];
    try {
      for (const item of items) { const post = await hermesApi.createPost({ account_id: accountId, caption: item.caption, hashtags: tags(item.hashtags), media_urls: [item.media_url], scheduled_at: null }); created.push(post.id); }
      await hermesApi.bulkSchedule(items.map((item, index) => ({ post_id: created[index], scheduled_at: fromInputDateTime(item.date_time) })));
      navigate('/hermes/scheduler', { replace: true });
    } catch (e) {
      const rollback = await Promise.allSettled(created.map((id) => hermesApi.deletePost(id)));
      const failed = rollback.filter((item) => item.status === 'rejected').length;
      setError(`${message(e)}${failed ? ` ${failed} draft(s) could not be removed; review your calendar.` : ' Drafts created during this attempt were removed.'}`);
    } finally { setBusy(false); }
  }
  if (loadingAccounts) return <div className="hm-page hm-rise"><div className="hm-loading" role="status">Loading content planner…</div></div>;
  return <div className="hm-page hm-rise"><div className="hm-page-head"><div><span className="hm-eyebrow">AI CONTENT PLANNING</span><h2>A week, thoughtfully planned</h2><p>Turn your niche and audience into a ready to review publishing plan.</p></div><span className="hm-ai-badge">✦ POWERED BY AI</span></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}{notice && <div className="hm-notice" role="status">{notice}</div>}
    {busy && <div className="hm-loading" role="status">{items.length ? 'Scheduling your plan…' : 'Generating your plan…'}</div>}
    {!accounts.length ? <div className="hm-empty hm-panel">Connect an account to generate a content plan. <Link to="/hermes/connect">Connect Instagram →</Link></div> : <><section className="hm-panel hm-plan-form"><div className="hm-section-title"><div><h3>Set the direction</h3><p>Hermes will suggest topics, captions and times.</p></div></div><div className="hm-plan-fields"><label>Account<select value={accountId} onChange={(e) => setAccountId(e.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>@{account.username}</option>)}</select></label><label>Content niche<input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. slow fashion, local cafes" /></label><label>Target audience<input value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="e.g. young creatives in Tehran" /></label><label>Posts this week<select value={frequency} onChange={(e) => setFrequency(Number(e.target.value))}>{Array.from({ length: 7 }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1} post{index ? 's' : ''}</option>)}</select></label></div><button className="hm-btn hm-btn-primary" onClick={generate} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>✦ Generate weekly plan</button></section>
      {items.length > 0 && <><div className="hm-section-title hm-plan-results-title"><div><h3>Your 7-day plan</h3><p>Review and edit each suggestion before scheduling.</p></div><span>{items.length} ideas</span></div><div className="hm-plan-week">{Array.from({ length: 7 }, (_, offset) => { const day = addDays(new Date(), offset); const count = items.filter((item) => item.date_time?.slice(0, 10) === format(day, 'yyyy-MM-dd')).length; return <div key={offset} className={count ? 'planned' : ''}><small>{format(day, 'EEE')}</small><strong>{format(day, 'd')}</strong><span>{count ? `${count} post${count > 1 ? 's' : ''}` : 'Open'}</span></div>; })}</div><div className="hm-plan-items">{items.map((item, index) => <article className="hm-panel hm-plan-item" key={item.key}><div className="hm-plan-number">{String(index + 1).padStart(2, '0')}</div><div className="hm-plan-content"><div className="hm-plan-item-head"><span className="hm-eyebrow">{item.weekday || 'Planned post'} · {item.format || 'Instagram post'}</span><strong>{item.topic || 'Content idea'}</strong></div><div className="hm-plan-edit-grid"><label>Caption<textarea rows="3" value={item.caption} onChange={(e) => update(index, 'caption', e.target.value)} /></label><label>Hashtags<input value={item.hashtags} onChange={(e) => update(index, 'hashtags', e.target.value)} placeholder="tag one, tag two" /></label><label>Public HTTPS media URL<input type="url" value={item.media_url} onChange={(e) => update(index, 'media_url', e.target.value)} placeholder="https://example.com/image.jpg" /></label><label>Schedule time<input type="datetime-local" value={item.date_time} onChange={(e) => update(index, 'date_time', e.target.value)} /></label></div></div></article>)}</div><div className="hm-plan-apply hm-panel"><div><strong>Ready to bring your week to life?</strong><p>Every item needs public media before it can be scheduled.</p></div><button className="hm-btn hm-btn-primary" onClick={apply} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Apply plan →</button></div></>}
    </>}
  </div>;
}
