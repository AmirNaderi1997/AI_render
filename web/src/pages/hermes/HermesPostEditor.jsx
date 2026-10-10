import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import hermesApi from '../../services/hermesApi';
import { array, fromInputDateTime, message, tags, toInputDateTime } from './hermesUtils';

export default function HermesPostEditor() {
  const { id } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const [accounts, setAccounts] = useState([]);
  const [accountId, setAccountId] = useState('');
  const [caption, setCaption] = useState('');
  const [hashtags, setHashtags] = useState('');
  const [mediaUrl, setMediaUrl] = useState('');
  const [previewUrl, setPreviewUrl] = useState('');
  const [scheduledAt, setScheduledAt] = useState(() => search.get('date') ? `${search.get('date')}T12:00` : '');
  const [status, setStatus] = useState('draft');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  useEffect(() => { let alive = true; Promise.all([hermesApi.getAccounts(), id ? hermesApi.getPost(id) : Promise.resolve(null)]).then(([list, post]) => { if (!alive) return; setAccounts(array(list)); setAccountId(post?.account_id || list?.[0]?.id || ''); if (post) { setCaption(post.caption || ''); setHashtags(array(post.hashtags).join(', ')); setMediaUrl(post.media_urls?.[0] || ''); setScheduledAt(post.scheduled_at ? toInputDateTime(post.scheduled_at) : ''); setStatus(post.status); } }).catch((e) => alive && setError(message(e))).finally(() => alive && setLoading(false)); return () => { alive = false; }; }, [id]);
  useEffect(() => () => { if (previewUrl.startsWith('blob:')) URL.revokeObjectURL(previewUrl); }, [previewUrl]);
  const parsedTags = tags(hashtags);
  const editable = !['posted', 'publishing'].includes(status);
  const validMedia = /^https:\/\/[^\s]+$/i.test(mediaUrl);
  async function upload(file) {
    if (!file) return;
    setError(''); setNotice('');
    if (!['image/jpeg', 'image/png', 'video/mp4'].includes(file.type)) { setError('Use a JPG, PNG, or MP4 file.'); return; }
    setPreviewUrl(URL.createObjectURL(file)); setBusy(true);
    try { const result = await hermesApi.uploadMedia(file); if (result.media_url) { setMediaUrl(result.media_url); setNotice('Media uploaded and ready to publish.'); } else { setMediaUrl(''); setNotice('Upload saved locally. Publishing needs a public HTTPS media URL; paste one below or configure Hermes public media hosting.'); } } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function ask(kind) {
    if (!accountId) { setError('Connect an Instagram account first.'); return; }
    if (!caption.trim()) { setError('Describe your post in the caption field first.'); return; }
    setBusy(true); setError('');
    try { if (kind === 'caption') { const result = await hermesApi.generateCaption({ account_id: accountId, content: caption, tone: 'natural' }); setSuggestions(array(result.captions).filter((item) => typeof item === 'string')); } else { const result = await hermesApi.getHashtags({ account_id: accountId, content: caption, count: 10 }); setHashtags(array(result.hashtags).map((item) => typeof item === 'string' ? item : item.tag || '').join(', ')); } } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function save(mode) {
    setError(''); setNotice('');
    if (!accountId) { setError('Connect an Instagram account first.'); return; }
    if (caption.length > 2200 || parsedTags.length > 30) { setError('Instagram allows 2,200 caption characters and 30 hashtags.'); return; }
    if ((mode === 'schedule' || mode === 'publish') && !validMedia) { setError('A public HTTPS media URL is required to schedule or publish.'); return; }
    if (mode === 'schedule' && (!scheduledAt || new Date(scheduledAt) <= new Date())) { setError('Choose a future date and time.'); return; }
    const body = { caption, hashtags: parsedTags, media_urls: validMedia ? [mediaUrl] : [], scheduled_at: mode === 'schedule' ? fromInputDateTime(scheduledAt) : null };
    setBusy(true);
    try { const post = id ? await hermesApi.updatePost(id, body) : await hermesApi.createPost({ account_id: accountId, ...body }); if (mode === 'publish') await hermesApi.publishNow(post.id); navigate(mode === 'schedule' ? '/hermes/scheduler' : '/hermes', { replace: true }); } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function remove() { if (!id || !window.confirm('Delete this post?')) return; setBusy(true); try { await hermesApi.deletePost(id); navigate('/hermes/scheduler', { replace: true }); } catch (e) { setError(message(e)); setBusy(false); } }
  if (loading) return <div className="hm-page hm-rise"><div className="hm-loading" role="status">Loading post editor…</div></div>;
  return <div className="hm-page hm-rise"><div className="hm-page-head"><div><span className="hm-eyebrow">{id ? 'EDIT POST' : 'CREATE POST'}</span><h2>{id ? 'Refine your post' : 'Make something worth sharing'}</h2><p>Craft your caption, choose media and set the right moment.</p></div><Link className="hm-btn hm-btn-quiet" to="/hermes/scheduler">← Calendar</Link></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}{notice && <div className="hm-notice" role="status">{notice}</div>}
    {busy && <div className="hm-loading" role="status">Updating your post…</div>}
    {!accounts.length && <div className="hm-empty hm-panel">Connect an Instagram account before creating a post. <Link to="/hermes/connect">Connect Instagram →</Link></div>}
    <div className="hm-editor-grid"><div className="hm-stack"><section className="hm-panel hm-form-panel"><div className="hm-section-title"><h3>Post details</h3><span className={`hm-status ${status}`}>{status}</span></div><label>Instagram account<select value={accountId} onChange={(e) => setAccountId(e.target.value)} disabled={!!id || !editable}>{accounts.length ? accounts.map((account) => <option key={account.id} value={account.id}>@{account.username}</option>) : <option value="">Connect an account first</option>}</select></label><label>Caption<textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows="8" placeholder="Write a story that invites your audience in…" disabled={!editable} maxLength="2200" /></label><div className="hm-input-footer"><button className="hm-text-button" onClick={() => ask('caption')} disabled={busy || !editable} title={(busy || !editable) ? "This post cannot be edited in its current state." : undefined}>✦ Generate caption</button><span>{caption.length} / 2200</span></div>{suggestions.length > 0 && <div className="hm-suggestions">{suggestions.map((option, index) => <button key={index} onClick={() => { setCaption(option.slice(0, 2200)); setSuggestions([]); }}>{option}</button>)}</div>}<label>Hashtags<input value={hashtags} onChange={(e) => setHashtags(e.target.value)} placeholder="design, process, inspiration" disabled={!editable} /></label><div className="hm-input-footer"><button className="hm-text-button" onClick={() => ask('hashtags')} disabled={busy || !editable} title={(busy || !editable) ? "This post cannot be edited in its current state." : undefined}>✦ Suggest hashtags</button><span className={parsedTags.length > 30 ? 'hm-negative' : ''}>{parsedTags.length} / 30</span></div></section>
      <section className="hm-panel hm-form-panel"><div className="hm-section-title"><h3>Media & timing</h3></div><label className="hm-upload"><span>↑</span><strong>Upload an image or video</strong><small>JPG, PNG or MP4 · up to 100 MB</small><input type="file" accept="image/jpeg,image/png,video/mp4" onChange={(e) => upload(e.target.files?.[0])} disabled={busy || !editable} /></label><label>Public HTTPS media URL<input type="url" value={mediaUrl} onChange={(e) => setMediaUrl(e.target.value)} placeholder="https://example.com/post.jpg" disabled={!editable} /></label><p className="hm-tiny">Instagram needs a public media URL. A local upload is usable only when Hermes public media hosting is configured.</p><label>Schedule for<input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} disabled={!editable} /></label></section>
      {editable && <div className="hm-editor-actions"><button className="hm-btn hm-btn-quiet" onClick={() => save('draft')} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Save draft</button><button className="hm-btn hm-btn-quiet" onClick={() => save('publish')} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Post now</button><button className="hm-btn hm-btn-primary" onClick={() => save('schedule')} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Schedule post →</button>{id && <button className="hm-text-button hm-delete" onClick={remove} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Delete</button>}</div>}</div>
      <aside className={`hm-preview-side hm-mobile-sheet ${previewOpen ? 'is-open' : ''}`}><button type="button" className="hm-sheet-toggle" aria-expanded={previewOpen} onClick={() => setPreviewOpen(value => !value)}>Live preview <span>{previewOpen ? '⌄' : '⌃'}</span></button><div className="hm-section-title"><div><h3>Live preview</h3><p>How your post could look</p></div></div><div className="hm-instagram-preview"><div className="hm-ig-head"><div className="hm-ig-avatar">◎</div><strong>@{accounts.find((item) => item.id === accountId)?.username || 'your.account'}</strong><span>•••</span></div><div className="hm-ig-media">{(previewUrl || mediaUrl) ? /\.(mp4)(\?|$)/i.test(previewUrl || mediaUrl) ? <video src={previewUrl || mediaUrl} controls /> : <img src={previewUrl || mediaUrl} alt="Post preview" /> : <div><span>✦</span><small>Your media will appear here</small></div>}</div><div className="hm-ig-actions">♡　◯　➤ <span>▢</span></div><div className="hm-ig-caption"><strong>@{accounts.find((item) => item.id === accountId)?.username || 'your.account'}</strong> {caption || 'Your caption will appear here…'}<div className="hm-ig-tags">{parsedTags.slice(0, 10).map((tag) => `#${tag}`).join(' ')}</div></div></div><p className="hm-tiny">Preview is approximate. Instagram may crop media differently.</p></aside></div>
  </div>;
}
