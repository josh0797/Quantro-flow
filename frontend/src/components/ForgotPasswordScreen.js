import React, { useState } from 'react';
import { Mail, Loader2, ArrowLeft, MailCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useLanguage } from '../context/LanguageContext';
import { supabase } from '../lib/supabaseClient';
import { requestPasswordReset } from '../lib/passwordRecovery';
import AuthCardShell from './AuthCardShell';

/**
 * ForgotPasswordScreen — "¿Olvidaste tu contraseña?" from LoginPage.
 *
 * Sends the Supabase reset email (link back to /auth/callback, where
 * AuthCallback asks for the new password). The confirmation is neutral on
 * purpose: it never says whether an account exists for the email.
 */
export default function ForgotPasswordScreen({ initialEmail = '', onBack }) {
  const { t } = useLanguage();
  const [email, setEmail] = useState(initialEmail);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormError('');
    if (!email.trim()) {
      setFormError(t('auth_help.email_required'));
      return;
    }
    setSubmitting(true);
    try {
      const res = await requestPasswordReset(supabase, email);
      if (res.ok) setSent(true);
      else setFormError(t('auth_help.send_failed'));
    } catch (_) {
      setFormError(t('auth_help.send_failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthCardShell testId="forgot-password-screen">
      {sent ? (
        <div className="space-y-3" data-testid="forgot-password-sent">
          <MailCheck size={28} className="text-[hsl(var(--primary))]" />
          <h2 className="text-2xl font-semibold">{t('auth_help.link_sent_title')}</h2>
          <p className="text-sm text-muted-foreground leading-relaxed">{t('auth_help.link_sent_desc')}</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-6" data-testid="forgot-password-form">
          <div className="space-y-2">
            <h2 className="text-2xl font-semibold">{t('auth_help.forgot_title')}</h2>
            <p className="text-sm text-muted-foreground">{t('auth_help.forgot_subtitle')}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="forgot_email" className="text-xs text-muted-foreground">
              {t('auth.email_label')}
            </Label>
            <div className="relative">
              <Mail size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                id="forgot_email"
                data-testid="forgot-password-email-input"
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
          {formError && (
            <div
              data-testid="forgot-password-error"
              className="text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2"
            >
              {formError}
            </div>
          )}
          <Button
            data-testid="forgot-password-submit-btn"
            type="submit"
            disabled={submitting}
            className="w-full h-11 text-sm font-medium bg-[hsl(var(--foreground))] text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground)/0.9)]"
          >
            {submitting ? (
              <span className="flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" />
                {t('auth_help.sending')}
              </span>
            ) : (
              t('auth_help.send_link_cta')
            )}
          </Button>
        </form>
      )}
      <button
        type="button"
        data-testid="forgot-password-back"
        onClick={onBack}
        className="flex items-center gap-1.5 text-xs text-[hsl(var(--primary))] hover:underline"
      >
        <ArrowLeft size={12} />
        {t('auth_help.back_to_signin')}
      </button>
    </AuthCardShell>
  );
}
