import { supabase } from './supabaseClient';

/**
 * authFetch — drop-in replacement for fetch() that attaches the current
 * Supabase access token as a Bearer header. Components that previously used
 * raw fetch() (BusinessProfileContext, Sidebar, IntegrationsPanel) use this
 * to stay authenticated without wiring each request manually.
 *
 * Implementation note: we call supabase.auth.getSession() inside the
 * wrapper so token refresh is picked up automatically without needing a
 * re-render or an explicit event. @supabase/supabase-js caches the
 * session in memory so this is effectively a synchronous lookup.
 */
export async function authFetch(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  let token = null;
  try {
    const { data } = await supabase.auth.getSession();
    token = data?.session?.access_token || null;
  } catch (_) {
    token = null;
  }
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
