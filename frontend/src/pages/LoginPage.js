import React, { useState } from 'react';
import { ShieldCheck, Sparkles, Globe, Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useLanguage } from '../context/LanguageContext';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';
import LanguageSwitcher from '../components/LanguageSwitcher';

/**
 * LoginPage — first-surface of the authenticated product.
 *
 * Flow:
 *   1. User clicks "Continue with Google" → we redirect to
 *      `https://auth.emergentagent.com/?redirect=<app url>/auth/callback`
 *   2. Emergent handles Google OAuth and sends the user back to our
 *      /auth/callback route with `#session_id=<token>` in the URL.
 *   3. AuthCallback posts that session_id to /api/auth/session and we
 *      become authenticated.
 */
export default function LoginPage() {
  const { t } = useLanguage();
  const { user, loading } = useAuth();
  const [submitting, setSubmitting] = useState(false);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background text-foreground">
        <div className="text-sm text-muted-foreground">{t('auth.signing_in')}</div>
      </div>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  const handleGoogle = () => {
    setSubmitting(true);
    const redirectUrl = `${window.location.origin}/auth/callback`;
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div
      data-testid="login-page"
      className="min-h-screen w-full flex items-stretch bg-background text-foreground relative overflow-hidden"
    >
      {/* Left: brand/sell panel */}
      <div className="hidden md:flex flex-col justify-between w-1/2 p-12 relative bg-gradient-to-br from-[hsl(var(--primary)/0.08)] via-background to-background border-r border-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] flex items-center justify-center font-bold">
            Q
          </div>
          <div className="text-lg font-semibold tracking-tight">Quantro Flow</div>
          <div className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground">Business OS</div>
        </div>
        <div className="space-y-6 max-w-md">
          <h1 className="text-3xl lg:text-4xl font-semibold leading-tight">
            {t('auth.sign_in_title')}
          </h1>
          <p className="text-muted-foreground leading-relaxed">
            {t('auth.sign_in_subtitle')}
          </p>
          <div className="space-y-3 pt-4">
            {[
              { icon: Sparkles, label: 'Smart Inbox · CRM · Scheduling · Content' },
              { icon: Zap, label: 'Auto-execution + smart escalations' },
              { icon: Globe, label: 'Español · English · Multi-workspace' },
            ].map(({ icon: I, label }, idx) => (
              <div key={idx} className="flex items-center gap-3 text-sm text-muted-foreground">
                <I size={16} className="text-[hsl(var(--primary))]" />
                <span>{label}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <ShieldCheck size={14} className="text-[hsl(var(--success))]" />
          <span>{t('auth.secured_by')}</span>
        </div>
      </div>

      {/* Right: action panel */}
      <div className="flex-1 flex flex-col items-center justify-center p-8 md:p-12 relative">
        <div className="absolute top-4 right-4">
          <LanguageSwitcher />
        </div>
        <div className="w-full max-w-sm space-y-8">
          <div className="md:hidden flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] flex items-center justify-center font-bold">Q</div>
            <div className="text-lg font-semibold">Quantro Flow</div>
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold">{t('auth.sign_in_title')}</h2>
            <p className="text-sm text-muted-foreground">{t('auth.sign_in_subtitle')}</p>
          </div>
          <Button
            data-testid="login-google-btn"
            onClick={handleGoogle}
            disabled={submitting}
            className="w-full h-11 text-sm font-medium bg-[hsl(var(--foreground))] text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground)/0.9)]"
          >
            {submitting ? t('auth.signing_in') : t('auth.sign_in_with_google')}
          </Button>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <ShieldCheck size={14} className="text-[hsl(var(--success))]" />
            <span>{t('auth.secure_session')}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
