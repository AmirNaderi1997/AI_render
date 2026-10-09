import { useEffect, useState } from 'react';
import hermesApi from '../../services/hermesApi';
import { message } from './hermesUtils';

const fields = [
  ['access_token', 'Instagram access token'],
  ['app_id', 'App ID'],
  ['app_secret', 'App secret'],
  ['business_account_id', 'Business account ID'],
];
const empty = Object.fromEntries(fields.map(([field]) => [field, '']));

export default function HermesSettings() {
  const [form, setForm] = useState(empty);
  const [saved, setSaved] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    let alive = true;
    hermesApi.getSettings().then((result) => { if (alive) setSaved(result); })
      .catch((e) => { if (alive) setError(message(e)); });
    return () => { alive = false; };
  }, []);

  async function save(event) {
    event.preventDefault();
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await hermesApi.saveSettings(form);
      setSaved(result);
      setForm(empty);
      setNotice('Credentials saved. Test the connection to verify the token and account ID.');
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }

  async function test() {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await hermesApi.testConnection();
      setSaved(result);
      setNotice(result.connection_status === 'connected' ? 'Instagram connection verified.' : result.connection_status === 'expired' ? 'The token was rejected. Replace it and test again.' : 'The token did not match the business account ID.');
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }

  const status = saved?.connection_status || 'disconnected';
  return <div className="hm-page hm-rise">
    <div className="hm-page-head"><div><span className="hm-eyebrow">ACCOUNT SETTINGS</span><h2>Instagram credentials</h2><p>Save credentials for your account and verify the Graph API connection.</p></div></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}
    {notice && <div className="hm-notice" role="status">{notice}</div>}
    <section className="hm-panel hm-form-panel">
      <div className="hm-section-title"><h3>Connection status</h3><strong role="status" aria-live="polite">{status.charAt(0).toUpperCase() + status.slice(1)}</strong></div>
      <p className="hm-tiny">Status reflects the last connection test. Environment values take precedence until removed from the server configuration.</p>
      <form onSubmit={save} autoComplete="off" style={{ display: 'grid', gap: 16, marginTop: 18 }}>
        {fields.map(([field, label]) => <label key={field}>{label}
          <input type="password" value={form[field]} placeholder={saved?.[field] || 'Enter a new value'}
            onChange={(event) => setForm((current) => ({ ...current, [field]: event.target.value }))}
            autoComplete="new-password" spellCheck="false" disabled={busy} />
        </label>)}
        <div className="hm-account-actions"><button className="hm-btn hm-btn-primary" type="submit" disabled={busy || !Object.values(form).some((value) => value.trim())}>{busy ? 'Working…' : 'Save credentials'}</button>
          <button className="hm-btn hm-btn-quiet" type="button" onClick={test} disabled={busy || !saved?.access_token || !saved?.business_account_id}>Test Connection</button></div>
      </form>
    </section>
  </div>;
}
