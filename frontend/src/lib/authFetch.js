import { getStoredToken } from './api';

/**
 * authFetch — drop-in replacement for fetch() that attaches the
 * Bearer session token automatically. Components that previously used
 * raw fetch() (e.g., BusinessProfileContext, Sidebar, IntegrationsPanel)
 * use this to stay authenticated without manually wiring each request.
 */
export async function authFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getStoredToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  // Never use the HTTP cache for auth-gated calls — browsers may
  // otherwise replay a stale 401 response before our token was set.
  const res = await fetch(url, { ...options, headers, cache: 'no-store' });
  if (res.status === 401 && token) {
    window.dispatchEvent(new CustomEvent('auth:unauthorized'));
  }
  return res;
}
