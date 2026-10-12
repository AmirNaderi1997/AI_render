import { FormEvent, useEffect, useState } from 'react';
import hermesApi from '../../services/hermesApi';
import { message } from './hermesUtils';

export type InstagramStatus = { configured: boolean; instagram_user_id: string | null };

const fields = [
  ['access_token', 'Instagram Access Token', 'password'],
  ['instagram_user_id', 'Instagram User ID', 'text'],
  ['app_id', 'App ID', 'text'],
  ['app_secret', 'App Secret', 'password'],
] as const;
type Field = (typeof fields)[number][0];
const empty: Record<Field, string> = { access_token: '', instagram_user_id: '', app_id: '', app_secret: '' };

export function InstagramSettingsPanel({ onChanged }: { onChanged?: (status: InstagramStatus) => void }) {
  const [form, setForm] = useState(empty);
  const [status, setStatus] = useState<InstagramStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let alive = true;
    hermesApi.getInstagramSettings().then((result: InstagramStatus) => { if (alive) setStatus(result); })
      .catch((e: unknown) => { if (alive) setError(message(e)); });
    return () => { alive = false; };
  }, []);

  function apply(result: InstagramStatus) {
    setStatus(result);
    onChanged?.(result);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const missing = fields.filter(([field]) => !form[field].trim()).map(([, label]) => label);
    if (missing.length) { setNotice(''); setError(`Required: ${missing.join(', ')}.`); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      apply(await hermesApi.saveInstagramSettings({
        access_token: form.access_token.trim(),
        instagram_user_id: form.instagram_user_id.trim(),
        app_id: form.app_id.trim(),
        app_secret: form.app_secret.trim(),
      }));
      setForm(empty);
      setNotice('Instagram credentials saved.');
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    setBusy(true); setError(''); setNotice('');
    try {
      apply(await hermesApi.deleteInstagramSettings());
      setNotice('Instagram credentials removed.');
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }

  const configured = !!status?.configured;
  return <section className="hm-panel hm-form-panel">
    <div className="hm-section-title"><h3>Instagram connection</h3>
      <strong role="status" aria-live="polite" className={configured ? 'hm-positive' : 'hm-muted'}>
        {status === null ? 'Checking…' : configured ? `Configured${status.instagram_user_id ? ` · ${status.instagram_user_id}` : ''}` : 'Not configured'}
      </strong></div>
    <p className="hm-tiny">Enter all Instagram API credentials here. They are encrypted before storage and are never shown again.</p>
    {error && <div className="hm-alert" role="alert">{error}</div>}
    {notice && <div className="hm-notice" role="status" style={{ color: '#6de2ca' }}>✓ {notice}</div>}
    <form onSubmit={save} autoComplete="off" noValidate style={{ display: 'grid', gap: 16 }}>
      {fields.map(([field, label, type]) => <label key={field}>{label}
        <input type={type} value={form[field]} required placeholder={configured && field === 'instagram_user_id' ? status?.instagram_user_id ?? '' : 'Enter a value'}
          onChange={(event) => setForm((current) => ({ ...current, [field]: event.target.value }))}
          autoComplete="new-password" spellCheck={false} disabled={busy} />
      </label>)}
      <div className="hm-account-actions">
        <button className="hm-btn hm-btn-primary" type="submit" disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>{busy ? 'Working…' : 'Save'}</button>
        <button className="hm-btn hm-btn-quiet" type="button" onClick={disconnect} disabled={busy || !configured} title={(busy || !configured) ? "Connect Instagram first." : undefined}>Disconnect</button>
      </div>
    </form>
  </section>;
}

export function HermesSettingsModal({ onClose, onChanged }: { onClose: () => void; onChanged?: (status: InstagramStatus) => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return <div role="dialog" aria-modal="true" aria-label="Instagram settings" onClick={onClose}
    style={{ position: 'fixed', inset: 0, zIndex: 50, background: 'rgba(5,6,12,.72)', display: 'grid', placeItems: 'center', padding: 20 }}>
    <div onClick={(event) => event.stopPropagation()} style={{ width: 'min(520px, 100%)', maxHeight: '90vh', overflow: 'auto' }}>
      <InstagramSettingsPanel onChanged={onChanged} />
      <button className="hm-btn hm-btn-quiet hm-full" type="button" onClick={onClose} style={{ marginTop: 10 }}>Close</button>
    </div>
  </div>;
}

export default function HermesSettings() {
  return <div className="hm-page hm-rise">
    <div className="hm-page-head"><div><span className="hm-eyebrow">ACCOUNT SETTINGS</span><h2>Instagram credentials</h2><p>Enter your Instagram API credentials here instead of editing the server's .env file.</p></div></div>
    <InstagramSettingsPanel />
  </div>;
}
