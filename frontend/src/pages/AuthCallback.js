import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Loader2 } from 'lucide-react';
import { supabase } from '../lib/supabaseClient';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';

/**
 * AuthCallback — handles any redirect from Supabase Auth.
 *
 * Common cases handled:
 *   1. Email confirmation link (type=signup)  → lands here with tokens
 *      already exchanged by supabase-js (detectSessionInUrl = true).
 *   2. OAuth callback (future: Google/Apple via Supabase).
 *   3. Magic link sign-in (future).
 *
 * We just wait for the SDK to finalize the session and then navigate to
 * the dashboard. If no session shows up within a short window we route
 * the user back to /login with a friendly error.
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const { t } = useLanguage();
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        // Give supabase-js a tick to process any tokens in the URL.
        await new Promise((r) => setTimeout(r, 50));
        const { data, error: sessionErr } = await supabase.auth.getSession();
        if (sessionErr) throw sessionErr;
        if (!data?.session) {
          throw new Error('No session');
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
          toast.error(t('auth.login_failed_title'), { description: t('auth.login_failed_desc') });
          setTimeout(() => navigate('/login', { replace: true }), 1500);
        }
      }
    };
    run();
    return () => { cancelled = true; };
  }, [navigate, refresh, t]);

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
