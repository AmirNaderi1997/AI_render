import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { addMonths, addWeeks, format } from 'date-fns';
import hermesApi from '../../services/hermesApi';
import ScheduleCalendar from '../../components/hermes/ScheduleCalendar';
import PostCard from '../../components/hermes/PostCard';
import { array, message } from './hermesUtils';

export default function HermesScheduler() {
  const navigate = useNavigate();
  const [date, setDate] = useState(new Date());
  const [view, setView] = useState('month');
  const [posts, setPosts] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [dayOpen, setDayOpen] = useState(false);
  useEffect(() => { let alive = true; hermesApi.getSchedule().then((items) => alive && setPosts(array(items))).catch((e) => alive && setError(message(e))).finally(() => alive && setLoading(false)); return () => { alive = false; }; }, []);
  const selected = posts.filter((post) => post.scheduled_at && format(new Date(post.scheduled_at), 'yyyy-MM-dd') === format(date, 'yyyy-MM-dd'));
  function move(direction) { setDate((current) => view === 'month' ? addMonths(current, direction) : addWeeks(current, direction)); }
  return <div className="hm-page hm-rise"><div className="hm-page-head"><div><span className="hm-eyebrow">PUBLISHING CALENDAR</span><h2>Schedule your story</h2><p>Give every idea its moment.</p></div><Link className="hm-btn hm-btn-primary" to={`/hermes/post/new?date=${format(date, 'yyyy-MM-dd')}`}>＋ New post</Link></div>
    {error && <div className="hm-alert" role="alert">{error}</div>}
    <div className="hm-calendar-layout"><section className="hm-panel hm-calendar-panel"><div className="hm-calendar-toolbar"><div className="hm-calendar-title"><button className="hm-icon-button" onClick={() => move(-1)} aria-label="Previous period">‹</button><h3>{format(date, view === 'month' ? 'MMMM yyyy' : "MMM d, yyyy")}</h3><button className="hm-icon-button" onClick={() => move(1)} aria-label="Next period">›</button><button className="hm-today" onClick={() => setDate(new Date())}>Today</button></div><div className="hm-segment"><button aria-pressed={view === 'month'} className={view === 'month' ? 'active' : ''} onClick={() => setView('month')}>Month</button><button aria-pressed={view === 'week'} className={view === 'week' ? 'active' : ''} onClick={() => setView('week')}>Week</button></div></div>{loading ? <div className="hm-loading" role="status">Loading calendar…</div> : <ScheduleCalendar posts={posts} date={date} view={view} onDate={(day) => navigate(`/hermes/post/new?date=${format(day, 'yyyy-MM-dd')}`)} onPost={(post) => navigate(`/hermes/post/${post.id}`)} />}<div className="hm-legend">{[['draft', 'Draft'], ['scheduled', 'Scheduled'], ['posted', 'Posted'], ['failed', 'Failed']].map(([status, label]) => <span key={status}><i className={status} />{label}</span>)}</div></section>
      <aside className={`hm-day-panel hm-mobile-sheet ${dayOpen ? 'is-open' : ''}`}><button type="button" className="hm-sheet-toggle" aria-expanded={dayOpen} onClick={() => setDayOpen(value => !value)}>{format(date, 'EEE, MMM d')} · {selected.length} post{selected.length === 1 ? '' : 's'} <span>{dayOpen ? '⌄' : '⌃'}</span></button><div className="hm-section-title"><div><h3>{format(date, 'EEEE, MMM d')}</h3><p>{selected.length} scheduled post{selected.length === 1 ? '' : 's'}</p></div></div>{selected.length ? <div className="hm-stack">{selected.map((post) => <PostCard key={post.id} post={post} />)}</div> : <div className="hm-empty hm-panel">Nothing planned for this day.</div>}<Link className="hm-btn hm-btn-quiet hm-full" to={`/hermes/post/new?date=${format(date, 'yyyy-MM-dd')}`}>＋ Add a post</Link></aside></div>
  </div>;
}
