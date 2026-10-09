import { Link } from 'react-router-dom';
import { localDateTime } from '../../pages/hermes/hermesUtils';

export default function PostCard({ post }) {
  const media = post.media_urls?.[0];
  return <Link className="hm-post hm-panel" to={`/hermes/post/${post.id}`}>
    <div className="hm-post-image">{media && /\.(mp4)(\?|$)/i.test(media) ? <video src={media} muted /> : media ? <img src={media} alt="Post media" loading="lazy" /> : <span>✦</span>}</div>
    <div className="hm-post-copy"><div><span className={`hm-status ${post.status}`}>{post.status}</span><span className="hm-muted">{localDateTime(post.scheduled_at || post.posted_at)}</span></div><strong>{post.caption || 'Untitled post'}</strong><small>{post.hashtags?.length ? `${post.hashtags.length} hashtags` : 'No hashtags'}</small></div>
    <span className="hm-post-arrow" aria-hidden="true">↗</span>
  </Link>;
}
