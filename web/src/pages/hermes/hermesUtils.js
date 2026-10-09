import { friendlyError } from '../../ui';

export const array = (value) => Array.isArray(value) ? value : [];
export const number = (value) => typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat().format(value) : '—';
export const percent = (value) => typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—';
export const message = (error) => friendlyError(error, 'complete this Hermes action');
export const localDateTime = (value) => value ? new Date(value).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'Not scheduled';
export const toInputDateTime = (value) => {
  const date = value ? new Date(value) : new Date();
  return Number.isNaN(date.getTime()) ? '' : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
export const fromInputDateTime = (value) => value ? new Date(value).toISOString() : null;
export const tags = (value) => value.split(',').map((tag) => tag.trim().replace(/^#/, '')).filter(Boolean);
export const initial = (name) => (name || 'I').slice(0, 1).toUpperCase();
