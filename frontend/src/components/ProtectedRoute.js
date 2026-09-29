import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { useOnboardingGate } from '../lib/onboardingGate';

/**
 * ProtectedRoute — wraps every authenticated screen.
 * - If still hydrating session → shows a slim loader.
 * - If unauthenticated → redirects to /login (preserves the intended URL).
 * - If authenticated but `needs_onboarding` is still set and we're NOT
 *   already inside /welcome → ask the onboarding gate (lib/onboardingGate)
 *   whether this is a brand-new workspace (→ /welcome) or an existing one
 *   that simply never finished the Welcome flow (→ flag cleared, app).
 * - Otherwise → renders children.
 */
export default function ProtectedRoute({ children, bypassOnboarding = false }) {
  const { user, loading } = useAuth();
  const { t } = useLanguage();
  const location = useLocation();

  const gateEnabled =
    !loading
    && !!user
    && !bypassOnboarding
    && user.needs_onboarding === true
    && !location.pathname.startsWith('/welcome');
  const gate = useOnboardingGate(user, gateEnabled);

  if (loading || (gateEnabled && gate === 'checking')) {
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

  // Onboarding gate: brand-new signups finish the Welcome activation flow
  // before reaching the main platform. Users who never had
  // `needs_onboarding=true`, or whose workspace already has real data,
  // are NOT forced through it.
  if (gateEnabled && gate === 'onboarding') {
    return <Navigate to="/welcome" replace />;
  }

  return children;
}
