import Calendar from 'react-calendar';
import { addDays, endOfWeek, format, isSameDay, startOfWeek } from 'date-fns';

export default function ScheduleCalendar({ posts = [], date, onDate, onPost, view = 'month' }) {
  const match = (day) => posts.filter((post) => post.scheduled_at && isSameDay(new Date(post.scheduled_at), day));
  if (view === 'week') {
    const start = startOfWeek(date, { weekStartsOn: 6 });
    return <div className="hm-week-grid">{Array.from({ length: 7 }, (_, index) => {
      const day = addDays(start, index);
      return <div className={`hm-week-day ${isSameDay(day, date) ? 'selected' : ''}`} key={index}><button className="hm-week-date" onClick={() => onDate(day)} title="Create a post on this day"><small>{format(day, 'EEE')}</small><strong>{format(day, 'd')}</strong></button><div className="hm-week-posts">{match(day).map((post) => <button key={post.id} className={`hm-calendar-post ${post.status}`} onClick={() => onPost(post)} title={post.caption}>{format(new Date(post.scheduled_at), 'HH:mm')} {post.caption || 'Untitled post'}</button>)}</div></div>;
    })}</div>;
  }
  return <div onClickCapture={(event) => { const id = event.target.dataset.postId; if (id) { event.stopPropagation(); onPost(posts.find((post) => post.id === id)); } }}><Calendar className="hm-calendar" value={date} onChange={onDate} calendarType="gregory" next2Label={null} prev2Label={null} tileContent={({ date: day, view: tileView }) => tileView === 'month' ? <div className="hm-calendar-dots">{match(day).slice(0, 4).map((post) => <span key={post.id} data-post-id={post.id} className={post.status} title={`Edit: ${post.caption || post.status}`} />)}</div> : null} /></div>;
}
