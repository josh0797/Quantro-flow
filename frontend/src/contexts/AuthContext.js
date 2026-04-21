import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { authMe, authLogout, authExchangeSession, authSwitchWorkspace, setStoredToken, getStoredToken } from '../lib/api';

/**
 * AuthContext — owns the authenticated user + workspace state for the entire app.
 *
 * Responsibilities:
 *   - On mount: check /api/auth/me to hydrate user from existing session cookie.
 *   - Expose login(session_id) that exchanges an Emergent session_id for a cookie.
 *   - Expose logout(), switchWorkspace(id).
 *   - Listen to the global `auth:unauthorized` event from the axios interceptor
 *     and flip back to unauthenticated state (triggers redirect to /login).
 */
const AuthContext = createContext({
  user: null,
  workspaces: [],
  currentWorkspaceId: null,
  loading: true,
  login: async () => {},
  logout: async () => {},
  switchWorkspace: async () => {},
  refresh: async () => {},
});

export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    // Bail out fast if there's no token at all — avoids a useless 401 on first load.
    if (!getStoredToken()) {
      setUser(null);
      setWorkspaces([]);
      setLoading(false);
      return;
    }
    try {
      const data = await authMe();
      setUser({
        user_id: data.user_id,
        email: data.email,
        name: data.name,
        picture: data.picture,
        current_workspace_id: data.current_workspace_id,
      });
      setWorkspaces(data.workspaces || []);
    } catch (err) {
      setStoredToken(null);
      setUser(null);
      setWorkspaces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Global 401 listener
  useEffect(() => {
    const handler = () => {
      setUser(null);
      setWorkspaces([]);
    };
    window.addEventListener('auth:unauthorized', handler);
    return () => window.removeEventListener('auth:unauthorized', handler);
  }, []);

  const login = useCallback(async (sessionId) => {
    const result = await authExchangeSession(sessionId);
    if (result?.session_token) {
      setStoredToken(result.session_token);
    }
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    try { await authLogout(); } catch (_) { /* ignore */ }
    setStoredToken(null);
    setUser(null);
    setWorkspaces([]);
  }, []);

  const switchWorkspace = useCallback(async (workspaceId) => {
    await authSwitchWorkspace(workspaceId);
    await refresh();
    // Ask consumers (BusinessProfile / pages) to re-fetch. The simplest
    // & safest way: reload the SPA so every context rehydrates.
    window.location.reload();
  }, [refresh]);

  const value = {
    user,
    workspaces,
    currentWorkspaceId: user?.current_workspace_id || null,
    loading,
    login,
    logout,
    switchWorkspace,
    refresh,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
