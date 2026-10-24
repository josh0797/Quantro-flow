/**
 * providerCallback — shared parsing of the query string a provider OAuth
 * callback (backend /api/integrations/<provider>/callback) appends when
 * it bounces the browser back to the SPA:
 *
 *   ?google_connected=success&account=<email>&return_to=/welcome/inbox
 *   ?google_connected=permission_missing&missing_scopes=a,b&account=...
 *   ?microsoft_connected=error&reason=<code>
 *
 * Used by the Welcome flow (OnboardingShell) and by Settings →
 * Integrations (ConnectPanel) so both read and clean the URL the same way.
 */

export const PROVIDER_CALLBACK_PARAMS = [
  'google_connected',
  'microsoft_connected',
  'account',
  'return_to',
  'reason',
  'detail',
  'missing_scopes',
];

/**
 * Returns `{ provider, status, account, reason, missingScopes }` or null
 * when the URL carries no provider callback. Google wins if (defensively)
 * both providers are present.
 */
export function readProviderCallback(params) {
  if (!params) return null;
  const googleStatus = params.get('google_connected');
  const microsoftStatus = params.get('microsoft_connected');
  const provider = googleStatus ? 'google' : microsoftStatus ? 'microsoft' : null;
  if (!provider) return null;
  return {
    provider,
    status: provider === 'google' ? googleStatus : microsoftStatus,
    account: params.get('account') || '',
    reason: params.get('reason') || '',
    missingScopes: (params.get('missing_scopes') || '').split(',').filter(Boolean),
  };
}

/** Copy of `params` without any of the callback keys (other params kept). */
export function stripProviderCallbackParams(params) {
  const next = new URLSearchParams(params);
  PROVIDER_CALLBACK_PARAMS.forEach((key) => next.delete(key));
  return next;
}

export function providerLabel(provider) {
  return provider === 'microsoft' ? 'Microsoft' : 'Google';
}

/**
 * Where the Welcome flow goes after a SUCCESSFUL provider OAuth return.
 * Google/Microsoft consent covers mail AND calendar, and the callback
 * handler marks both steps as real, so the next pending step from the
 * start / inbox / calendar screens is the CRM step. Returns null for any
 * other screen (the user stays where they are).
 */
export function nextStepAfterProviderConnect(pathname) {
  const here = (pathname || '').replace(/\/+$/, '');
  if (here === '/welcome' || here === '/welcome/inbox' || here === '/welcome/calendar') {
    return '/welcome/crm';
  }
  return null;
}
