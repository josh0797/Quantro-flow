import React, { useState } from 'react';
import { ShieldCheck, Sparkles, Globe, Zap, Mail, Lock, User, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';
import { useLanguage } from '../context/LanguageContext';
import { useAuth } from '../contexts/AuthContext';
import { Navigate } from 'react-router-dom';
import LanguageSwitcher from '../components/LanguageSwitcher';

/**
 * Validates that a full name contains at least two whitespace-separated
 * words (first + last name). Trims and collapses extra whitespace.
 */
export function isValidFullName(value) {
  if (!value) return false;
  const parts = String(value).trim().split(/\s+/).filter(Boolean);
  return parts.length >= 2 && parts.every((p) => p.length >= 2);
}

/**
 * LoginPage — first surface of the authenticated product.
 *
 * Powered by Supabase Auth (email + password). Uses the SAME Supabase
 * project as the Quantro landing so sessions, profiles and AI usage are
 * shared seamlessly across the ecosystem. Users that already signed up
 * on https://quantro.technology can sign in here directly.
 *
 * Signup additionally collects the user's `full_name` (min 2 words),
 * which is stored in ``user_metadata.full_name`` and later upserted into
 * `profiles.full_name`. Right after signup the user is sent through the
 * `/onboarding-lite` step to capture country, industry and company name.
 */
export default function LoginPage() {
  const { t } = useLanguage();
  const { user, loading, signIn, signUp } = useAuth();
  const [mode, setMode] = useState('signin'); // 'signin' | 'signup'
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState('');

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background text-foreground">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={14} className="animate-spin" />
          {t('auth.signing_in')}
        </div>
      </div>
    );
  }

  if (user) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormError('');

    if (!email || !password) {
      setFormError(t('auth.missing_fields'));
      return;
    }
    if (mode === 'signup') {
      if (!isValidFullName(fullName)) {
        setFormError(t('auth.full_name_invalid'));
        return;
      }
      if (password.length < 8) {
        setFormError(t('auth.password_min'));
        return;
      }
    }

    setSubmitting(true);
    try {
      if (mode === 'signin') {
        await signIn(email, password);
      } else {
        const cleanName = String(fullName).trim().replace(/\s+/g, ' ');
        const result = await signUp(email, password, {
          full_name: cleanName,
          name: cleanName,
          needs_onboarding: true,
        });
        if (result?.session) {
          toast.success(t('auth.account_confirmed'));
        } else {
          toast.success(t('auth.signup_success_title'), {
            description: t('auth.signup_success_desc'),
          });
          setMode('signin');
          setPassword('');
        }
      }
    } catch (err) {
      setFormError(err?.message || t('auth.login_failed_desc'));
    } finally {
      setSubmitting(false);
    }
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
        <form
          onSubmit={handleSubmit}
          className="w-full max-w-sm space-y-6"
          data-testid="login-form"
        >
          <div className="md:hidden flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] flex items-center justify-center font-bold">Q</div>
            <div className="text-lg font-semibold">Quantro Flow</div>
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold">
              {mode === 'signin' ? t('auth.sign_in_cta') : t('auth.sign_up_cta')}
            </h2>
            <p className="text-sm text-muted-foreground">{t('auth.sign_in_subtitle')}</p>
          </div>

          <div className="space-y-4">
            {mode === 'signup' && (
              <div className="space-y-1.5">
                <Label htmlFor="full_name" className="text-xs text-muted-foreground">
                  {t('auth.full_name_label')}
                </Label>
                <div className="relative">
                  <User size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="full_name"
                    data-testid="login-full-name-input"
                    type="text"
                    autoComplete="name"
                    placeholder={t('auth.full_name_placeholder')}
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    disabled={submitting}
                    required
                    className="pl-9 h-10 bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]"
                  />
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="email" className="text-xs text-muted-foreground">
                {t('auth.email_label')}
              </Label>
              <div className="relative">
                <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="email"
                  data-testid="login-email-input"
                  type="email"
                  autoComplete="email"
                  placeholder={t('auth.email_placeholder')}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={submitting}
                  required
                  className="pl-9 h-10 bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password" className="text-xs text-muted-foreground">
                {t('auth.password_label')}
              </Label>
              <div className="relative">
                <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="password"
                  data-testid="login-password-input"
                  type="password"
                  autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                  placeholder={t('auth.password_placeholder')}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={submitting}
                  required
                  minLength={mode === 'signup' ? 8 : undefined}
                  className="pl-9 h-10 bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]"
                />
              </div>
            </div>
          </div>

          {formError && (
            <div
              data-testid="login-error"
              className="text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2"
            >
              {formError}
            </div>
          )}

          <Button
            data-testid="login-submit-btn"
            type="submit"
            disabled={submitting}
            className="w-full h-11 text-sm font-medium bg-[hsl(var(--foreground))] text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground)/0.9)]"
          >
            {submitting ? (
              <span className="flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" />
                {t('auth.signing_in')}
              </span>
            ) : (
              mode === 'signin' ? t('auth.sign_in_cta') : t('auth.sign_up_cta')
            )}
          </Button>

          <div className="flex items-center justify-between gap-2 text-xs">
            <button
              type="button"
              data-testid="login-mode-toggle"
              onClick={() => {
                setMode(mode === 'signin' ? 'signup' : 'signin');
                setFormError('');
              }}
              className="text-[hsl(var(--primary))] hover:underline"
            >
              {mode === 'signin' ? t('auth.toggle_to_signup') : t('auth.toggle_to_signin')}
            </button>
          </div>

          <div className="flex items-center gap-2 text-xs text-muted-foreground pt-2 border-t border-[hsl(var(--border))]">
            <ShieldCheck size={14} className="text-[hsl(var(--success))]" />
            <span>{t('auth.secure_session')} · {t('auth.secured_by')}</span>
          </div>
        </form>
      </div>
    </div>
  );
}
