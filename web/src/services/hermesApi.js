import { ensureFreshToken, getToken, handleUnauthorized } from '../auth';

const BASE = (import.meta.env.VITE_HERMES_API_URL || '/api/hermes').replace(/\/$/, '');

async function request(path, { method = 'GET', body, ...options } = {}) {
  await ensureFreshToken();
  const token = getToken();
  if (!token) handleUnauthorized();
  const headers = { Authorization: `Bearer ${token}`, ...options.headers };
  if (body !== undefined && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(`${BASE}${path}`, { ...options, method, headers, body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new Error('Hermes is unavailable. Check that its service is running.');
  }
  if (response.status === 401) handleUnauthorized();
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const detail = data?.detail;
    const message = typeof detail === 'string' ? detail : detail?.code || `Hermes request failed (${response.status})`;
    throw new Error(message.replaceAll('_', ' ').toLowerCase());
  }
  return response.status === 204 ? null : response.json();
}

const query = (values = {}) => {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') params.set(key, value); });
  return params.size ? `?${params}` : '';
};

export const hermesApi = {
  getInstagramSettings: () => request('/settings/instagram'),
  saveInstagramSettings: (credentials) => request('/settings/instagram', { method: 'POST', body: credentials }),
  deleteInstagramSettings: () => request('/settings/instagram', { method: 'DELETE' }),
  testInstagramConnection: () => request('/settings/instagram/test', { method: 'POST' }),
  connectInstagram: () => request('/auth/connect', { method: 'POST' }),
  authCallback: (code, state) => request(`/auth/callback${query({ code, state })}`),
  refreshToken: (accountId) => request('/auth/refresh', { method: 'POST', body: { account_id: accountId } }),
  getAccounts: () => request('/auth/accounts'),
  createPost: (post) => request('/posts/', { method: 'POST', body: post }),
  getPosts: (filters) => request(`/posts/${query(filters)}`),
  getPost: (id) => request(`/posts/${encodeURIComponent(id)}`),
  updatePost: (id, post) => request(`/posts/${encodeURIComponent(id)}`, { method: 'PUT', body: post }),
  deletePost: (id) => request(`/posts/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  publishNow: (id) => request(`/posts/${encodeURIComponent(id)}/publish`, { method: 'POST' }),
  uploadMedia: (file) => { const body = new FormData(); body.append('file', file); return request('/posts/media', { method: 'POST', body }); },
  getSchedule: (filters) => request(`/schedule/${query(filters)}`),
  bulkSchedule: (items) => request('/schedule/bulk', { method: 'POST', body: { items } }),
  getAccountAnalytics: (accountId) => request(`/analytics/account/${encodeURIComponent(accountId)}`),
  getPostAnalytics: (accountId) => request(`/analytics/posts/${encodeURIComponent(accountId)}`),
  refreshAnalytics: (accountId) => request(`/analytics/refresh/${encodeURIComponent(accountId)}`, { method: 'POST' }),
  getBestTimes: (body) => request('/advisor/best-times', { method: 'POST', body }),
  getHashtags: (body) => request('/advisor/hashtags', { method: 'POST', body }),
  generateCaption: (body) => request('/advisor/caption', { method: 'POST', body }),
  getContentPlan: (body) => request('/advisor/content-plan', { method: 'POST', body }),
};

export default hermesApi;
