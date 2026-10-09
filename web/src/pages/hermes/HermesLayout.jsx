import { NavLink, Outlet, useLocation } from 'react-router-dom';
import './hermes.css';

const links = [
  ['Overview', '/hermes', '◫'], ['Accounts', '/hermes/connect', '◎'],
  ['Scheduler', '/hermes/scheduler', '▦'], ['Analytics', '/hermes/analytics', '◴'],
  ['AI Advisor', '/hermes/advisor', '✦'], ['Content Plan', '/hermes/content-plan', '▤'],
  ['Settings', '/hermes/settings', '⚙'],
];

export default function HermesLayout() {
  const location = useLocation();
  return <div className="hm-shell">
    <div className="hm-topline"><div><span className="hm-eyebrow">AI RENDER / HERMES</span><h1>Instagram studio<span className="hm-heading-star">✳</span></h1><p>Plan, publish and learn from every post.</p></div><span className="hm-live"><i /> HERMES STUDIO</span></div>
    <div className="hm-subnav" aria-label="Hermes pages">{links.map(([label, href, icon]) => <NavLink key={href} to={href} end={href === '/hermes'} className={({ isActive }) => `hm-subnav-link ${isActive || (href === '/hermes/scheduler' && location.pathname.startsWith('/hermes/post/')) ? 'active' : ''}`}><span aria-hidden="true">{icon}</span>{label}</NavLink>)}</div>
    <Outlet />
  </div>;
}
