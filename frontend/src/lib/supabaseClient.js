import { createClient } from '@supabase/supabase-js';

/**
 * Supabase client — shared singleton used by both Auth and direct table
 * access. Points at the SAME project as https://quantro.technology so we
 * share sessions, `profiles`, `ai_usage`, and any other table that already
 * exists in the Quantro ecosystem. Do NOT create a second Supabase project.
 *
 * Credentials are read from REACT_APP_SUPABASE_URL and
 * REACT_APP_SUPABASE_ANON_KEY (see /app/frontend/.env). The anon key is
 * safe to ship to the browser because Row-Level Security policies in
 * Supabase enforce access control server-side.
 */
const SUPABASE_URL = process.env.REACT_APP_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.REACT_APP_SUPABASE_ANON_KEY;

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  // Do not throw in production; the app should still render a friendly
  // login error instead of a white screen when credentials are missing.
  // eslint-disable-next-line no-console
  console.error('[supabase] Missing REACT_APP_SUPABASE_URL / REACT_APP_SUPABASE_ANON_KEY env vars');
}

export const supabase = createClient(
  SUPABASE_URL || 'https://missing.supabase.co',
  SUPABASE_ANON_KEY || 'missing',
  {
    auth: {
      // Persist the session so a page refresh keeps the user logged in.
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storage: typeof window !== 'undefined' ? window.localStorage : undefined,
      storageKey: 'quantro-flow-auth',
      flowType: 'pkce',
    },
  }
);

/**
 * Convenience helper for reading the current access token synchronously
 * (the underlying session is already persisted in localStorage by
 * @supabase/supabase-js). Returns null when no session is active.
 */
export async function getAccessToken() {
  try {
    const { data, error } = await supabase.auth.getSession();
    if (error) return null;
    return data?.session?.access_token || null;
  } catch (_) {
    return null;
  }
}
