import { useCallback, useEffect, useRef, useState } from 'react';
import hermesApi from '../../services/hermesApi';
import AccountCard from '../../components/hermes/AccountCard';
import { array, message } from './hermesUtils';

export default function HermesConnect() {
  const [accounts, setAccounts] = useState([]);
  const [followers, setFollowers] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const poll = useRef(null);
  const load = useCallback(async () => { const list = await hermesApi.getAccounts(); setAccounts(array(list)); setLoading(false); return array(list); }, []);
  useEffect(() => { load().catch((e) => { setError(message(e)); setLoading(false); }); return () => clearInterval(poll.current); }, [load]);
  const accountIds = accounts.map((account) => account.id).join(',');
  useEffect(() => { if (!accountIds) return; let alive = true; Promise.allSettled(accounts.map((account) => hermesApi.getAccountAnalytics(account.id))).then((results) => { if (alive) setFollowers(Object.fromEntries(accounts.map((account, index) => [account.id, results[index].status === 'fulfilled' ? results[index].value?.followers : null]))); }); return () => { alive = false; }; }, [accountIds]);
  async function connect() {
    setBusy(true); setError(''); setNotice('');
    try {
      const before = accounts.length;
      const { authorization_url: url } = await hermesApi.connectInstagram();
      const popup = window.open(url, 'hermes-instagram-connect', 'popup,width=600,height=760');
      if (!popup) { setNotice('Pop-up blocked. Opened Instagram authorization in this tab.'); window.location.assign(url); return; }
      setNotice('Finish authorization in the Instagram window. This page will update after the account is connected.');
      clearInterval(poll.current);
      poll.current = setInterval(async () => {
        try { const list = await load(); if (list.length > before) { clearInterval(poll.current); popup.close(); setNotice('Instagram account connected.'); } else if (popup.closed) { clearInterval(poll.current); setNotice('Authorization window closed. Refresh accounts if you completed the connection.'); } } catch { /* The account list is retried on the next poll. */ }
      }, 2500);
    } catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  async function refresh(account) {
    setBusy(true); setError('');
    try { await hermesApi.refreshToken(account.id); await load(); setNotice(`Token refreshed for @${account.username}.`); } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function refreshList() {
    setBusy(true); setError('');
    try { await load(); setNotice('Account list updated.'); }
    catch (e) { setError(message(e)); }
    finally { setBusy(false); }
  }
  return <div className="hm-page hm-rise"><div className="hm-page-head"><div><span className="hm-eyebrow">ACCOUNT CONNECTIONS</span><h2>Instagram accounts</h2><p>Manage the professional accounts that power your studio.</p></div><button className="hm-btn hm-btn-primary" onClick={connect} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>◎ Connect Instagram</button></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}{notice && <div className="hm-notice" role="status">{notice}</div>}
    {busy && <div className="hm-loading" role="status">Updating Instagram accounts…</div>}
    <div className="hm-connect-banner hm-panel"><div className="hm-connect-symbol">◎</div><div><h3>Publish with confidence</h3><p>Connect an Instagram professional account through Meta's authorization flow. Hermes stores a renewable connection token and keeps your posts in one place.</p></div><button className="hm-btn hm-btn-quiet" disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined} onClick={refreshList}>Refresh list</button></div>
    <div className="hm-section-title"><div><h3>Connected accounts</h3><p>Token status and account details</p></div><span>{accounts.length} total</span></div>
    {loading ? <div className="hm-loading" role="status">Loading accounts…</div> : accounts.length ? <div className="hm-stack">{accounts.map((account) => <AccountCard key={account.id} account={account} followers={followers[account.id]} actions={<div className="hm-account-actions"><button className="hm-text-button" onClick={() => refresh(account)} disabled={busy} title={(busy) ? "Wait for the current action to finish." : undefined}>Refresh token</button><button className="hm-text-button" disabled title="Hermes does not provide a disconnect endpoint yet">Disconnect unavailable</button></div>} />)}</div> : <div className="hm-empty hm-panel">No Instagram accounts connected. Use the button above to begin.</div>}
    <p className="hm-footnote">Disconnect is unavailable because the Hermes API does not expose account removal yet.</p>
  </div>;
}
