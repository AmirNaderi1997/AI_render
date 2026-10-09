import { initial, localDateTime, number } from '../../pages/hermes/hermesUtils';

export default function AccountCard({ account, followers, actions }) {
  const expiry = account.token_expires_at ? new Date(account.token_expires_at).getTime() : 0;
  const tokenState = !expiry || expiry < Date.now() ? 'Expired' : expiry < Date.now() + 14 * 86400000 ? 'Expiring soon' : 'Connected';
  return <article className="hm-account hm-panel">
    <div className="hm-avatar">{initial(account.username)}</div>
    <div className="hm-account-info"><strong>@{account.username}</strong><span>Instagram professional account</span><small>{followers == null ? 'Followers unavailable' : `${number(followers)} followers`}</small></div>
    <div className="hm-account-side"><span className={`hm-token ${tokenState === 'Connected' ? 'ok' : tokenState === 'Expired' ? 'bad' : 'warn'}`}><i />{tokenState}</span><small>Token: {localDateTime(account.token_expires_at)}</small>{actions}</div>
  </article>;
}
