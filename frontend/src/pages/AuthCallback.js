import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';

/**
 * AuthCallback — receives `#session_id=<id>` from Emergent Auth
 * after the Google consent screen, exchanges it with our backend
 * and redirects to the dashboard.
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { t } = useLanguage();
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        // Emergent returns session_id in the URL fragment (hash)
        const hash = window.location.hash || '';
        const params = new URLSearchParams(hash.replace(/^#/, ''));
        const sessionId = params.get('session_id');
        if (!sessionId) {
          throw new Error('Missing session_id');
        }
        await login(sessionId);
        // Clean the URL & route to dashboard
        if (!cancelled) {
          window.history.replaceState({}, document.title, window.location.pathname);
          toast.success(t('auth.welcome_back', { name: '' }).replace(/,\s*$/, ''));
          navigate('/', { replace: true });
        }
      } catch (err) {
        console.error('Auth callback failed:', err);
        if (!cancelled) {
          setError(err?.message || 'unknown');
          toast.error(t('auth.login_failed_title'), { description: t('auth.login_failed_desc') });
          setTimeout(() => navigate('/login', { replace: true }), 2000);
        }
      }
    };
    run();
    return () => { cancelled = true; };
  }, [login, navigate, t]);

  return (
    <div
      data-testid="auth-callback-screen"
      className="min-h-screen flex items-center justify-center bg-background text-foreground"
    >
      <div className="text-center space-y-3">
        <div className="inline-block w-8 h-8 border-2 border-[hsl(var(--primary))] border-t-transparent rounded-full animate-spin" />
        <p className="text-sm text-muted-foreground">
          {error ? t('auth.login_failed_title') : t('auth.signing_in')}
        </p>
      </div>
    </div>
  );
}
