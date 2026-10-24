import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';

/**
 * Legacy URLs that moved. Rendered inside the authenticated AppShell
 * routes (App.js) — keep every old link, bookmark and OAuth return
 * working.
 *
 * /connect and /connect/* → /settings/integrations
 *   Quantro Connect was merged into Settings → Integrations. The query
 *   string and hash are preserved so provider OAuth returns that still
 *   target /connect (e.g. ?google_connected=success&account=…, from an
 *   OAuth flow started before the merge — the backend keeps /connect on
 *   its return_to allowlist) are handled by the Integrations tab.
 */
export const CONNECT_NEW_HOME = '/settings/integrations';

export function LegacyConnectRedirect() {
  const location = useLocation();
  return (
    <Navigate
      replace
      to={{ pathname: CONNECT_NEW_HOME, search: location.search, hash: location.hash }}
    />
  );
}

export const legacyRedirectRoutes = [
  { path: '/connect', element: <LegacyConnectRedirect /> },
  { path: '/connect/*', element: <LegacyConnectRedirect /> },
];
