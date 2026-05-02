import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { supabase } from '../lib/supabaseClient';

/**
 * AuthContext — single source of truth for the authenticated user.
 *
 * Powered by Supabase Auth (same project as the Quantro landing). We
 * intentionally keep the shape (user, workspaces, currentWorkspaceId,
 * loading, login/logout/switchWorkspace) compatible with the previous
 * Emergent-based implementation so consumers (Sidebar, ProtectedRoute,
 * PlanAndUsage) keep working unchanged.
 *
 * Responsibilities:
 *   - On mount → hydrate `session` / `user` via supabase.auth.getSession()
 *   - Subscribe to auth state changes (sign-in, sign-out, token refresh)
 *   - Expose signIn(email, password) / signUp(email, password) / signOut()
 *   - Expose `user` shape matching what the rest of the app expects:
 *       { user_id, email, name, picture, current_workspace_id }
 *   - Notify the app when the token changes by emitting `auth:token-changed`
 *     so authFetch() can re-attach the new Bearer.
 */
const AuthContext = createContext({
  user: null,
  session: null,
  workspaces: [],
  currentWorkspaceId: null,
  loading: true,
  signIn: async () => {},
  signUp: async () => {},
  signOut: async () => {},
  logout: async () => {},
  switchWorkspace: async () => {},
  refresh: async () => {},
});

export const useAuth = () => useContext(AuthContext);

function mapSupabaseUser(supaUser, workspaces = []) {
  if (!supaUser) return null;
  const meta = supaUser.user_metadata || {};
  const currentWs = workspaces.find((w) => w.is_current);
  return {
    user_id: supaUser.id,
    email: supaUser.email,
    name: meta.full_name || meta.name || (supaUser.email || 'User').split('@')[0],
    picture: meta.avatar_url || meta.picture || null,
    current_workspace_id: currentWs?.workspace_id || null,
    // Onboarding hints surfaced for ProtectedRoute to decide whether to
    // send the user through /onboarding-lite after signup.
    needs_onboarding: meta.needs_onboarding === true,
    country: meta.country || null,
    industry: meta.industry || null,
    company_name: meta.company_name || null,
    user_metadata: meta,
  };
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [supaUser, setSupaUser] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);

  /**
   * Pull the user's workspaces from the backend. The backend uses the
   * Supabase JWT (forwarded as Bearer) to identify the user, upsert them
   * into Mongo, claim/create a workspace, and return the membership list.
   * This keeps MongoDB the source of truth for operational data while
   * Supabase stays the source of truth for identity.
   */
  const fetchWorkspaces = useCallback(async (accessToken) => {
    if (!accessToken) return [];
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const res = await fetch(`${backendUrl}/api/auth/me`, {
        headers: { Authorization: `Bearer ${accessToken}` },
        cache: 'no-store',
      });
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data?.workspaces) ? data.workspaces : [];
    } catch (_) {
      return [];
    }
  }, []);

  const hydrateFromSession = useCallback(async (nextSession) => {
    setSession(nextSession);
    setSupaUser(nextSession?.user || null);
    if (nextSession?.access_token) {
      const ws = await fetchWorkspaces(nextSession.access_token);
      setWorkspaces(ws);
    } else {
      setWorkspaces([]);
    }
  }, [fetchWorkspaces]);

  // Initial load + auth state subscription
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { data } = await supabase.auth.getSession();
        if (!active) return;
        await hydrateFromSession(data?.session || null);
      } catch (_) {
        if (!active) return;
        await hydrateFromSession(null);
      } finally {
        if (active) setLoading(false);
      }
    })();

    const { data: sub } = supabase.auth.onAuthStateChange(async (_event, nextSession) => {
      await hydrateFromSession(nextSession);
      // Notify any fetch() wrappers that the token may have changed.
      window.dispatchEvent(new CustomEvent('auth:token-changed'));
    });

    return () => {
      active = false;
      try {
        sub?.subscription?.unsubscribe?.();
      } catch (e) {
        // eslint-disable-next-line no-console
        console.warn('[auth] could not unsubscribe from auth state changes:', e?.message || e);
      }
    };
  }, [hydrateFromSession]);

  // Global 401 listener (from authFetch / axios) → force re-auth.
  useEffect(() => {
    const handler = () => {
      // Do not call signOut() here — the server may be temporarily down.
      // Just drop local state; ProtectedRoute will redirect to /login.
      setSession(null);
      setSupaUser(null);
      setWorkspaces([]);
    };
    window.addEventListener('auth:unauthorized', handler);
    return () => window.removeEventListener('auth:unauthorized', handler);
  }, []);

  const signIn = useCallback(async (email, password) => {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    await hydrateFromSession(data.session);
    return data;
  }, [hydrateFromSession]);

  const signUp = useCallback(async (email, password, metadata = {}) => {
    // Default new signups into the Welcome activation flow. Callers can
    // still override by passing `needs_onboarding: false` explicitly.
    const enrichedMetadata = {
      needs_onboarding: true,
      ...metadata,
    };
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: enrichedMetadata,
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });
    if (error) throw error;
    if (data.session) {
      await hydrateFromSession(data.session);
    }
    return data;
  }, [hydrateFromSession]);

  const signOut = useCallback(async () => {
    try {
      await supabase.auth.signOut();
    } catch (e) {
      // Even if the network call fails we still want to wipe local state
      // so the user is no longer treated as authenticated by the SPA.
      // eslint-disable-next-line no-console
      console.warn('[auth] supabase.auth.signOut() failed:', e?.message || e);
    }
    setSession(null);
    setSupaUser(null);
    setWorkspaces([]);
  }, []);

  // Legacy alias — PlanAndUsage / Sidebar still call `logout()`.
  const logout = signOut;

  const refresh = useCallback(async () => {
    const { data } = await supabase.auth.getSession();
    await hydrateFromSession(data?.session || null);
  }, [hydrateFromSession]);

  const switchWorkspace = useCallback(async (workspaceId) => {
    const accessToken = session?.access_token;
    if (!accessToken) return;
    const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
    await fetch(`${backendUrl}/api/auth/workspaces/switch`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ workspace_id: workspaceId }),
    });
    await refresh();
    window.location.reload();
  }, [session, refresh]);

  const user = mapSupabaseUser(supaUser, workspaces);

  const value = {
    user,
    session,
    workspaces,
    currentWorkspaceId: user?.current_workspace_id || null,
    loading,
    signIn,
    signUp,
    signOut,
    logout,
    switchWorkspace,
    refresh,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
