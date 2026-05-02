import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';

/**
 * ProtectedRoute — wraps every authenticated screen.
 * - If still hydrating session → shows a slim loader.
 * - If unauthenticated → redirects to /login (preserves the intended URL).
 * - If authenticated but onboarding is still pending and we're NOT
 *   already on /onboarding-lite → redirect there first.
 * - Otherwise → renders children.
 */
export default function ProtectedRoute({ children, bypassOnboarding = false }) {
  const { user, loading } = useAuth();
  const { t } = useLanguage();
  const location = useLocation();

  if (loading) {
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

  // Onboarding gate: freshly-signed-up users must finish the Welcome
  // activation flow before reaching the main platform. Existing users
  // (who never had `needs_onboarding=true` set on their Supabase
  // metadata) are NOT forced through it.
  if (!bypassOnboarding && user.needs_onboarding && !location.pathname.startsWith('/welcome')) {
    return <Navigate to="/welcome" replace />;
  }

  return children;
}
