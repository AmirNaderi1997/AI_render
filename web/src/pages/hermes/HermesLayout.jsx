import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import hermesApi from '../../services/hermesApi';
import { HermesSettingsModal } from './HermesSettings';
import './hermes.css';

const links = [
  ['Overview', '/hermes', '◫'], ['Accounts', '/hermes/connect', '◎'],
  ['Scheduler', '/hermes/scheduler', '▦'], ['Analytics', '/hermes/analytics', '◴'],
  ['AI Advisor', '/hermes/advisor', '✦'], ['Content Plan', '/hermes/content-plan', '▤'],
  ['Settings', '/hermes/settings', '⚙'],
];

export default function HermesLayout() {
  const location = useLocation();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [instagram, setInstagram] = useState(null);
  const [settingsError, setSettingsError] = useState('');
  const loadInstagram = () => hermesApi.getInstagramSettings().then(value => { setInstagram(value); setSettingsError(''); }).catch(() => setSettingsError('Could not load Instagram settings. Please try again.'));
  useEffect(() => { void loadInstagram(); }, []);
  return <div className="hm-shell">
    <div className="hm-topline"><div><span className="hm-eyebrow">AI RENDER / HERMES</span><h1>Instagram studio<span className="hm-heading-star">✳</span></h1><p>Plan, publish and learn from every post.</p></div><div style={{ display: 'flex', alignItems: 'center', gap: 10 }}><button type="button" className="hm-btn hm-btn-quiet" onClick={() => setSettingsOpen(true)} aria-haspopup="dialog">⚙ Instagram: {instagram ? (instagram.configured ? 'Configured' : 'Not configured') : '…'}</button><span className="hm-live"><i /> HERMES STUDIO</span></div></div>
    <div className="hm-subnav" aria-label="Hermes pages">{links.map(([label, href, icon]) => <NavLink key={href} to={href} end={href === '/hermes'} className={({ isActive }) => `hm-subnav-link ${isActive || (href === '/hermes/scheduler' && location.pathname.startsWith('/hermes/post/')) ? 'active' : ''}`}><span aria-hidden="true">{icon}</span>{label}</NavLink>)}</div>
    {settingsError && <p className="errors" role="alert">{settingsError} <button type="button" className="secondary" onClick={() => void loadInstagram()}>Retry</button></p>}
    <Outlet />
    {settingsOpen && <HermesSettingsModal onClose={() => setSettingsOpen(false)} onChanged={setInstagram} />}
  </div>;
}
