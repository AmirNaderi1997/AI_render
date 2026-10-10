import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import hermesApi from '../../services/hermesApi';
import AdvisorChat from '../../components/hermes/AdvisorChat';
import { array, message } from './hermesUtils';

const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const hours = Array.from({ length: 24 }, (_, hour) => hour);
const dayIndex = (value) => days.findIndex((day) => day.toLowerCase().startsWith(String(value || '').toLowerCase().slice(0, 3)));

export default function HermesAdvisor() {
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState('');
  const [tab, setTab] = useState('times');
  const [topic, setTopic] = useState('');
  const [description, setDescription] = useState('');
  const [tone, setTone] = useState('natural');
  const [times, setTimes] = useState([]);
  const [hashtags, setHashtags] = useState([]);
  const [captions, setCaptions] = useState([]);
  const [conversation, setConversation] = useState([]);
  const [followup, setFollowup] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadingAccounts, setLoadingAccounts] = useState(true);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');
  useEffect(() => { hermesApi.getAccounts().then((list) => { setAccounts(array(list)); setAccountId(list?.[0]?.id || ''); }).catch((e) => setError(message(e))).finally(() => setLoadingAccounts(false)); }, []);
  async function run(kind, extra = '') {
    if (!accountId) { setError('Connect an Instagram account first.'); return; }
    if ((kind === 'hashtags' && !topic.trim()) || (kind === 'caption' && !description.trim())) { setError('Enter a topic or description first.'); return; }
    setBusy(true); setError('');
    try { let result;
      if (kind === 'times') { result = await hermesApi.getBestTimes({ account_id: accountId, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Tehran', topic: [topic, extra].filter(Boolean).join(' ') }); setTimes(array(result.times)); }
      if (kind === 'hashtags') { result = await hermesApi.getHashtags({ account_id: accountId, content: [topic, extra].filter(Boolean).join(' '), count: 12 }); setHashtags(array(result.hashtags)); }
      if (kind === 'caption') { result = await hermesApi.generateCaption({ account_id: accountId, content: [description, extra].filter(Boolean).join(' '), tone }); setCaptions(array(result.captions)); }
      setConversation((current) => [...current, { role: 'user', text: extra || (kind === 'times' ? 'Find my best posting times' : kind === 'hashtags' ? topic : description) }, { role: 'advisor', text: kind === 'times' ? `${array(result.times).length} posting suggestions ready.` : kind === 'hashtags' ? `${array(result.hashtags).length} hashtag suggestions ready.` : `${array(result.captions).length} caption options ready.` }]);
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function copy(value) { try { await navigator.clipboard.writeText(value); setCopied(value); window.setTimeout(() => setCopied(''), 2200); } catch { setError('Could not copy to clipboard.'); } }
  const recommended = new Set(times.map((time) => `${dayIndex(time.weekday)}-${Number.parseInt(time.local_time, 10)}`));
  if (loadingAccounts) return <div className="hm-page hm-rise"><div className="hm-loading" role="status">Loading advisor and accounts…</div></div>;
  return <div className="hm-page hm-rise"><div className="hm-page-head"><div><span className="hm-eyebrow">CREATIVE INTELLIGENCE</span><h2>Ideas, with direction</h2><p>Find better timing, sharper hashtags and captions that sound like you.</p></div><span className="hm-ai-badge">✦ POWERED BY AI</span></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}
    {busy && <div className="hm-loading" role="status">Preparing advisor suggestions…</div>}
    {!accounts.length ? <div className="hm-empty hm-panel">Connect an account to use the advisor. <Link to="/hermes/connect">Connect Instagram →</Link></div> : <><div className="hm-filters"><label>Working with<select value={accountId} onChange={(e) => setAccountId(e.target.value)}>{accounts.map((account) => <option key={account.id} value={account.id}>@{account.username}</option>)}</select></label></div><div className="hm-advisor-layout"><div><div className="hm-tabs">{[['times', 'Best times'], ['hashtags', 'Hashtags'], ['caption', 'Caption generator']].map(([key, label]) => <button key={key} aria-pressed={tab === key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</div>
      {tab === 'times' && <section className="hm-panel hm-tool"><div className="hm-section-title"><div><h3>When should you post?</h3><p>Recommendations based on available account insights</p></div></div><div className="hm-inline-form"><input aria-label="Topic or campaign" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Optional: topic or campaign" /><button className="hm-btn hm-btn-primary" onClick={() => run('times')} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Find times →</button></div><div className="hm-heatmap"><div className="hm-heatmap-head"><span />{hours.map((hour) => <span key={hour} title={`${hour}:00`}>{hour % 3 === 0 ? String(hour).padStart(2, '0') : ''}</span>)}</div>{days.map((day, index) => <div className="hm-heatmap-row" key={day}><strong>{day.slice(0, 3)}</strong>{hours.map((hour) => <span key={hour} className={recommended.has(`${index}-${hour}`) ? 'recommended' : ''} title={`${day} ${hour}:00${recommended.has(`${index}-${hour}`) ? ' · suggested' : ''}`} />)}</div>)}</div>{times.length > 0 && <div className="hm-recommendations">{times.map((item, index) => <div key={index}><strong>{item.weekday} · {item.local_time}</strong><span>{item.reason || 'Recommended posting window'}</span></div>)}</div>}<p className="hm-tiny">Colored cells mark AI recommendations, not measured activity scores.</p></section>}
      {tab === 'hashtags' && <section className="hm-panel hm-tool"><div className="hm-section-title"><div><h3>Find relevant hashtags</h3><p>Start with a topic or niche.</p></div></div><div className="hm-inline-form"><input aria-label="Topic or campaign" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. independent coffee shop in Tehran" /><button className="hm-btn hm-btn-primary" onClick={() => run('hashtags')} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Suggest →</button></div>{hashtags.length ? <div className="hm-tag-results">{hashtags.map((item, index) => { const tag = typeof item === 'string' ? item : item.tag || item.hashtag || ''; const score = typeof item === 'object' ? item.relevance : null; return <button key={index} onClick={() => copy(tag)} title="Copy hashtag">{tag.startsWith('#') ? tag : `#${tag}`}{typeof score === 'number' && <small>{Math.round(score <= 1 ? score * 100 : score)}%</small>}</button>; })}</div> : <div className="hm-tool-empty">Suggested hashtags will appear here.</div>}<p className="hm-tiny">{copied ? 'Copied to clipboard.' : 'Tap a hashtag to copy it. Relevance scores appear only when provided by the advisor.'}</p></section>}
      {tab === 'caption' && <section className="hm-panel hm-tool"><div className="hm-section-title"><div><h3>Generate a caption</h3><p>Describe the content and choose a voice.</p></div></div><label>Content description<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows="5" placeholder="What is in your post? What should your audience feel or do?" /></label><div className="hm-inline-form"><select aria-label="Caption tone" value={tone} onChange={(e) => setTone(e.target.value)}><option value="natural">Natural</option><option value="warm">Warm</option><option value="professional">Professional</option><option value="playful">Playful</option></select><button className="hm-btn hm-btn-primary" onClick={() => run('caption')} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>✦ Generate options</button></div>{captions.length ? <div className="hm-caption-results">{captions.map((text, index) => { const value = typeof text === 'string' ? text : text.caption; return <article key={index}><span>OPTION 0{index + 1}</span><p>{value}</p><button className="hm-text-button" onClick={() => copy(value)}>{copied === value ? 'Copied ✓' : 'Copy caption ↗'}</button></article>; })}</div> : <div className="hm-tool-empty">Your caption options will appear here.</div>}</section>}
      </div><aside><AdvisorChat entries={conversation} /><div className="hm-panel hm-followup"><label>Refine this advice<input value={followup} onChange={(e) => setFollowup(e.target.value)} placeholder="Ask for a different angle…" /></label><button className="hm-btn hm-btn-quiet hm-full" onClick={() => { if (followup.trim()) { run(tab, followup.trim()); setFollowup(''); } }} disabled={busy || !followup.trim()} title={(busy || !followup.trim()) ? "Enter a follow-up first." : undefined}>Send follow-up →</button><p className="hm-tiny">Follow-ups rerun the selected advisor tool with your added direction.</p></div></aside></div></>}
  </div>;
}
