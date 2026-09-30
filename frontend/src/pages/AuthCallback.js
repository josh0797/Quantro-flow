import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Loader2, Lock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { supabase } from '../lib/supabaseClient';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import AuthCardShell from '../components/AuthCardShell';
import {
  MIN_PASSWORD_LENGTH,
  clearRecoveryState,
  hasFreshRecoveryMarker,
  isRecoveryCallback,
  notePasswordRecoveryEvent,
  urlSaysRecovery,
} from '../lib/passwordRecovery';

/**
 * AuthCallback — handles any redirect from Supabase Auth.
 *
 * Common cases handled:
 *   1. Email confirmation link (type=signup)  → lands here with tokens
 *      already exchanged by supabase-js (detectSessionInUrl = true).
 *   2. Password reset link (PASSWORD_RECOVERY) → the exchange signs the
 *      user in; we ask for a new password (min 8) before continuing. See
 *      lib/passwordRecovery.js for how a recovery is recognised.
 *   3. OAuth callback / magic link sign-in (future).
 *
 * We wait for the SDK to finalize the session and then navigate to the
 * dashboard. If no session shows up within a short window we route the
 * user back to /login with a friendly error.
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const { t } = useLanguage();
  const [error, setError] = useState(null);
  const [recovery, setRecovery] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // Registered before supabase-js finishes the code exchange (AuthContext
    // records the event too; the local reset marker covers any race).
    const { data: sub } = supabase.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') notePasswordRecoveryEvent();
    });
    const { search, hash } = window.location;
    const run = async () => {
      try {
        // Give supabase-js a tick to process any tokens in the URL.
        await new Promise((r) => setTimeout(r, 50));
        const { data, error: sessionErr } = await supabase.auth.getSession();
        if (sessionErr) throw sessionErr;
        if (!data?.session) {
          throw new Error('No session');
        }
        // supabase-js dispatches PASSWORD_RECOVERY in a timeout right after
        // the exchange; let it land before deciding which screen to show.
        await new Promise((r) => setTimeout(r, 0));
        if (cancelled) return;
        if (isRecoveryCallback({ search, hash, sessionEmail: data.session.user?.email })) {
          window.history.replaceState({}, document.title, window.location.pathname);
          setRecovery(true);
          return;
        }
        await refresh();
        if (!cancelled) {
          window.history.replaceState({}, document.title, window.location.pathname);
          toast.success(t('auth.account_confirmed'));
          navigate('/', { replace: true });
        }
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || 'unknown');
          if (urlSaysRecovery(search, hash) || hasFreshRecoveryMarker()) {
            toast.error(t('auth_help.link_invalid_title'), { description: t('auth_help.link_invalid_desc') });
          } else {
            toast.error(t('auth.login_failed_title'), { description: t('auth.login_failed_desc') });
          }
          setTimeout(() => navigate('/login', { replace: true }), 1500);
        }
      }
    };
    run();
    return () => {
      cancelled = true;
      sub?.subscription?.unsubscribe?.();
    };
  }, [navigate, refresh, t]);

  if (recovery) {
    return (
      <NewPasswordForm
        t={t}
        onDone={async () => {
          await refresh();
          navigate('/', { replace: true });
        }}
      />
    );
  }

  return (
    <div
      data-testid="auth-callback-screen"
      className="min-h-screen flex items-center justify-center bg-background text-foreground"
    >
      <div className="text-center space-y-3">
        <Loader2 size={28} className="animate-spin mx-auto text-[hsl(var(--primary))]" />
        <p className="text-sm text-muted-foreground">
          {error ? t('auth.login_failed_title') : t('auth.signing_in')}
        </p>
      </div>
    </div>
  );
}

function NewPasswordForm({ t, onDone }) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setFormError('');
    if (password.length < MIN_PASSWORD_LENGTH) {
      setFormError(t('auth.password_min'));
      return;
    }
    if (password !== confirm) {
      setFormError(t('auth_help.password_mismatch'));
      return;
    }
    setSaving(true);
    try {
      const { error } = await supabase.auth.updateUser({ password });
      if (error) throw error;
      clearRecoveryState();
      toast.success(t('auth_help.password_updated'));
      await onDone();
    } catch (err) {
      // Supabase explains why (e.g. same as the old password) — show it.
      setFormError(err?.message || t('auth_help.update_failed'));
      toast.error(t('auth_help.update_failed'));
      setSaving(false);
    }
  };

  const field = (id, testId, label, value, onChange) => (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">{label}</Label>
      <div className="relative">
        <Lock size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input
          id={id}
          data-testid={testId}
          type="password"
          autoComplete="new-password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={saving}
          required
          minLength={MIN_PASSWORD_LENGTH}
          className="pl-9 h-10 bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]"
        />
      </div>
    </div>
  );

  return (
    <AuthCardShell testId="new-password-screen">
      <form onSubmit={handleSubmit} className="space-y-6" data-testid="new-password-form">
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold">{t('auth_help.new_password_title')}</h2>
          <p className="text-sm text-muted-foreground">{t('auth_help.new_password_subtitle')}</p>
        </div>
        <div className="space-y-4">
          {field('new_password', 'new-password-input', t('auth_help.new_password_label'), password, setPassword)}
          {field('confirm_password', 'confirm-password-input', t('auth_help.confirm_password_label'), confirm, setConfirm)}
        </div>
        {formError && (
          <div
            data-testid="new-password-error"
            className="text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2"
          >
            {formError}
          </div>
        )}
        <Button
          data-testid="new-password-submit-btn"
          type="submit"
          disabled={saving}
          className="w-full h-11 text-sm font-medium bg-[hsl(var(--foreground))] text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground)/0.9)]"
        >
          {saving ? (
            <span className="flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" />
              {t('auth_help.saving')}
            </span>
          ) : (
            t('auth_help.save_password_cta')
          )}
        </Button>
      </form>
    </AuthCardShell>
  );
}
