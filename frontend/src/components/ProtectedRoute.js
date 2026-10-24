import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { useOnboardingGate, useWelcomeEntryGate } from '../lib/onboardingGate';
import { readProviderCallback } from '../lib/providerCallback';
import { CONNECT_NEW_HOME } from '../routes/legacyRedirects';

/**
 * ProtectedRoute — wraps every authenticated screen.
 * - If still hydrating session → shows a slim loader.
 * - If unauthenticated → redirects to /login (preserves the intended URL).
 * - App routes: if `needs_onboarding` is still set → ask the onboarding
 *   gate (lib/onboardingGate) whether this is a brand-new workspace
 *   (→ /welcome) or an existing one that simply never finished the
 *   Welcome flow (→ flag cleared, app).
 * - `welcomeFlow` (the /welcome route): the same gate decides, once on
 *   entry, whether this user belongs in the flow. Anyone who does not
 *   (flag cleared, or an existing workspace opening /welcome from a
 *   bookmark / old tab) goes to the dashboard — or, when the URL is a
 *   provider OAuth return, to Settings → Integrations with the result so
 *   it is confirmed there instead of continuing the onboarding steps.
 * - `bypassOnboarding` (e.g. /join): no gate at all.
 * - Otherwise → renders children.
 */
export default function ProtectedRoute({ children, bypassOnboarding = false, welcomeFlow = false }) {
  const { user, loading } = useAuth();
  const { t } = useLanguage();
  const location = useLocation();

  const gateEnabled =
    !loading
    && !!user
    && !bypassOnboarding
    && !welcomeFlow
    && user.needs_onboarding === true
    && !location.pathname.startsWith('/welcome');
  const gate = useOnboardingGate(user, gateEnabled);
  const welcomeGate = useWelcomeEntryGate(user, welcomeFlow && !loading && !!user);

  if (
    loading
    || (gateEnabled && gate === 'checking')
    || (welcomeFlow && !!user && welcomeGate === 'checking')
  ) {
    return (
      <div
        data-testid="auth-loading"
        className="min-h-screen flex items-center justify-center bg-background text-foreground"
      >
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-[hsl(var(--primary))] border-t-transparent rounded-full animate-spin" />
          <div className="text-xs text-muted-foreground">{t('auth.signing_in')}</div>
        </div>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (welcomeFlow && welcomeGate === 'app') {
    const oauthReturn = readProviderCallback(new URLSearchParams(location.search));
    return oauthReturn
      ? <Navigate to={{ pathname: CONNECT_NEW_HOME, search: location.search }} replace />
      : <Navigate to="/dashboard" replace />;
  }

  // Onboarding gate: brand-new signups finish the Welcome activation flow
  // before reaching the main platform. Users who never had
  // `needs_onboarding=true`, or whose workspace already has real data,
  // are NOT forced through it.
  if (gateEnabled && gate === 'onboarding') {
    return <Navigate to="/welcome" replace />;
  }

  return children;
}
