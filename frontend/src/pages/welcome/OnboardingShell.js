import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate, Link, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '../../contexts/AuthContext';
import { useLanguage } from '../../context/LanguageContext';
import { OnboardingProvider, useOnboarding } from './OnboardingContext';
import { syncGoogleData, syncMicrosoftData, startGoogleOAuth, startMicrosoftOAuth } from '../../lib/api';
import { clearNeedsOnboardingFlag, needsWelcomeFlow } from '../../lib/onboardingGate';
import { CONNECT_NEW_HOME } from '../../routes/legacyRedirects';
import {
  readProviderCallback,
  stripProviderCallbackParams,
  nextStepAfterProviderConnect,
  providerLabel,
} from '../../lib/providerCallback';
import { Zap, LogOut, LayoutDashboard, Loader2 } from 'lucide-react';

/**
 * OnboardingShell — chrome around every /welcome screen.
 *
 * Visual mandate (dark Apple-feel, Quantro-consistent):
 *   • Background: app dark canvas + soft cyan radial wash
 *   • Generous whitespace, large display typography
 *   • Subtle progress dots at the top so the user always knows depth
 *   • Fade-in container so step transitions feel like the system
 *     turning on, not a form pagination
 *
 * The heavy lifting (per-step copy, CTAs, animations) lives in the
 * child route — the shell only renders identity, progress and exits
 * ("Ir al panel" + sign out), plus the background-sync status.
 */
const STEPS = [
  { key: 'start',       path: '/welcome' },
  { key: 'checkout',    path: '/welcome/checkout' },
  { key: 'inbox',       path: '/welcome/inbox' },
  { key: 'calendar',    path: '/welcome/calendar' },
  { key: 'crm',         path: '/welcome/crm' },
  { key: 'automations', path: '/welcome/automations' },
  { key: 'ready',       path: '/welcome/ready' },
];

export default function OnboardingShell() {
  const { user, signOut } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const location = useLocation();
  const [mounted, setMounted] = useState(false);

  // Trigger the fade-in once on each route change.
  useEffect(() => {
    setMounted(false);
    const id = window.requestAnimationFrame(() => setMounted(true));
    return () => window.cancelAnimationFrame(id);
  }, [location.pathname]);

  const stepIndex = useMemo(() => {
    const i = STEPS.findIndex((s) => s.path === location.pathname);
    return i === -1 ? 0 : i;
  }, [location.pathname]);

  const handleSignOut = async () => {
    await signOut?.();
    navigate('/login', { replace: true });
  };

  return (
    <OnboardingProvider key={user?.user_id || 'anonymous'}>
      <ProviderCallbackHandler />
      <div
        className="min-h-screen w-full bg-background text-foreground relative overflow-hidden"
        data-testid="onboarding-shell"
      >
        {/* Soft cyan wash, identical aesthetic to the AppShell so users
            never feel they left the product. */}
        <div
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              'radial-gradient(80% 60% at 50% 0%, hsl(var(--primary) / 0.10) 0%, transparent 60%), radial-gradient(60% 60% at 100% 100%, hsl(var(--accent) / 0.05) 0%, transparent 70%)',
          }}
        />

        {/* Top bar: brand + small progress + exit */}
        <header className="flex items-center justify-between px-6 md:px-12 lg:px-16 pt-8">
          <Link to="/welcome" className="flex items-center gap-3" data-testid="onboarding-brand">
            <div className="size-9 rounded-lg bg-[hsl(var(--primary)/0.12)] flex items-center justify-center">
              <Zap size={18} className="text-[hsl(var(--primary))]" />
            </div>
            <div className="flex flex-col leading-tight">
              <span className="text-sm font-semibold tracking-tight">Quantro Flow</span>
              <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Business OS</span>
            </div>
          </Link>

          {/* Progress dots — informative but never blocking */}
          <div className="hidden md:flex items-center gap-2" aria-label={t('welcome.progress_aria')}>
            {STEPS.map((s, i) => (
              <span
                key={s.key}
                aria-current={i === stepIndex ? 'step' : undefined}
                className={[
                  'h-1.5 rounded-full transition-all duration-300 ease-out',
                  i === stepIndex
                    ? 'w-8 bg-[hsl(var(--primary))]'
                    : i < stepIndex
                    ? 'w-4 bg-[hsl(var(--primary)/0.55)]'
                    : 'w-4 bg-[hsl(var(--muted-foreground)/0.20)]',
                ].join(' ')}
                data-testid={`onboarding-progress-${s.key}`}
              />
            ))}
          </div>

          <div className="flex items-center gap-4">
            <ExitToDashboardButton />
            <button
              type="button"
              onClick={handleSignOut}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors duration-200 inline-flex items-center gap-1.5"
              data-testid="onboarding-signout"
            >
              <LogOut size={12} />
              {t('welcome.sign_out')}
            </button>
          </div>
        </header>

        <SyncStatusBanner />

        {/* Step content with subtle fade-in. Children are responsible
            for their own layout (centered hero, side-by-side, etc.) */}
        <main
          className={[
            'mx-auto w-full max-w-5xl px-6 md:px-10 pt-12 md:pt-16 pb-24',
            'transition-all duration-300 ease-out',
            mounted ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2',
          ].join(' ')}
          data-testid="onboarding-main"
          data-step={STEPS[stepIndex]?.key}
        >
          <Outlet context={{ user }} />
        </main>
      </div>
    </OnboardingProvider>
  );
}

/**
 * ExitToDashboardButton — always-visible way out of the Welcome flow.
 * Clears Supabase `needs_onboarding` (via the onboarding gate helper, so
 * ProtectedRoute can never bounce the user back here), forgets this
 * user's Welcome progress and opens the dashboard. Never traps the user:
 * the dismissal is recorded synchronously, so we navigate at once and the
 * metadata write + auth refresh finish (or fail, logged) in the
 * background — a slow or hanging network can't keep the user here.
 */
export function ExitToDashboardButton() {
  const { user, refresh } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [exiting, setExiting] = useState(false);

  const handleExit = () => {
    if (exiting) return;
    setExiting(true);
    clearNeedsOnboardingFlag(user?.user_id)
      .then(() => refresh?.())
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.warn('[welcome] could not clear needs_onboarding:', err?.message || err);
      });
    navigate('/dashboard', { replace: true });
  };

  return (
    <button
      type="button"
      onClick={handleExit}
      disabled={exiting}
      className="text-xs font-medium text-foreground/80 hover:text-foreground border border-[hsl(var(--border))] hover:border-[hsl(var(--primary)/0.45)] rounded-full px-3 py-1.5 transition-colors duration-200 inline-flex items-center gap-1.5 disabled:opacity-60 disabled:cursor-wait"
      data-testid="onboarding-exit-dashboard"
    >
      {exiting ? <Loader2 size={12} className="animate-spin" /> : <LayoutDashboard size={12} />}
      {t('welcome.go_to_dashboard')}
    </button>
  );
}

/**
 * SyncStatusBanner — visible feedback while the post-OAuth mailbox /
 * calendar sync runs in the background (it can take ~25 s in prod).
 */
function SyncStatusBanner() {
  const { t } = useLanguage();
  const { syncInProgress } = useOnboarding();
  if (!syncInProgress) return null;
  return (
    <div className="flex justify-center px-6 pt-6">
      <div
        role="status"
        aria-live="polite"
        className="inline-flex items-center gap-2.5 rounded-full border border-[hsl(var(--primary)/0.30)] bg-[hsl(var(--primary)/0.06)] px-4 py-2 text-sm"
        data-testid="onboarding-sync-status"
      >
        <Loader2 size={14} className="animate-spin text-[hsl(var(--primary))]" />
        <span className="font-medium text-foreground">{t('welcome.sync.in_progress')}</span>
        <span className="hidden sm:inline text-xs text-muted-foreground">{t('welcome.sync.in_progress_hint')}</span>
      </div>
    </div>
  );
}

/**
 * ProviderCallbackHandler — invisible companion that watches the URL
 * for the ?google_connected=… / ?microsoft_connected=… query string a
 * provider OAuth callback appends.
 *
 * Only a user who is still onboarding (needs_onboarding set and not
 * cleared this session) is moved through the Welcome steps. Anyone else
 * — e.g. an existing owner whose OAuth was started from an old tab — is
 * sent to Settings → Integrations with the same result, where it is
 * confirmed; never forward into CRM / automations / ready (the last one
 * re-seeds the workspace).
 *
 * success:
 *   1. Marks the inbox AND calendar steps as connection_mode='real' (the
 *      provider consent covers mail + calendar) so the Activación screen
 *      renders "Datos reales".
 *   2. Moves to the next pending step IMMEDIATELY (CRM when coming from
 *      start / inbox / calendar) — the OAuth already succeeded, so the
 *      user must never sit on a screen that offers "Conectar" again.
 *   3. Runs /api/integrations/<provider>/sync in the background through
 *      OnboardingContext.runProviderSync. While it runs the shell shows
 *      "Sincronizando tus correos…" and every connect button in the flow
 *      is disabled, so OAuth cannot be restarted by a second click.
 *
 * error (?<provider>_connected=error&reason=...) only shows a toast and
 * leaves the user where they were — we never trap them.
 *
 * permission_missing (?google_connected=permission_missing&missing_scopes=...)
 * means the user authorized SOME but not all required scopes (e.g.
 * unchecked Calendar access on the consent screen). We must NOT mark
 * inbox/calendar as 'real' in that case — the connection exists but is
 * unusable for sync. Instead we surface exactly which permission is
 * missing and offer a "Reauthorize" action that restarts the OAuth
 * flow with prompt=consent so the user can grant the rest.
 */
export function ProviderCallbackHandler() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useLanguage();
  const { user } = useAuth();
  const { markStepConnected, runProviderSync } = useOnboarding();
  const handledRef = useRef(null);

  const callback = readProviderCallback(params);
  const signature = callback ? params.toString() : null;

  useEffect(() => {
    if (!callback) {
      // URL is clean again — a later OAuth return (even with the same
      // account) must be handled.
      handledRef.current = null;
      return;
    }
    // Guard against React StrictMode's double effect in development.
    if (handledRef.current === signature) return;
    handledRef.current = signature;

    if (!needsWelcomeFlow(user)) {
      navigate({ pathname: CONNECT_NEW_HOME, search: location.search }, { replace: true });
      return;
    }

    const { provider, status, account, reason, missingScopes } = callback;
    const label = providerLabel(provider);
    const next = status === 'success' ? nextStepAfterProviderConnect(location.pathname) : null;

    // Strip the callback params in the same navigation that moves the
    // user forward, so a refresh never re-fires these side effects.
    if (next) {
      navigate(next, { replace: true });
    } else {
      setParams(stripProviderCallbackParams(params), { replace: true });
    }

    if (status === 'error') {
      toast.error(t(`welcome.connect_modal.${provider}_failed_title`), { description: reason || 'unknown' });
      return;
    }

    if (status === 'permission_missing') {
      // Connection exists but is unusable — never claim it's real.
      const scopesLabel = missingScopes
        .map((s) => s.split('/').pop().replace(/\./g, ' '))
        .join(', ') || t('welcome.connect_modal.microsoft_subtitle');
      toast.warning(t('welcome.connect_modal.permission_missing_title'), {
        description: t('welcome.connect_modal.permission_missing_desc', {
          provider: label,
          scopes: scopesLabel,
        }),
        action: {
          label: t('welcome.connect_modal.reauthorize_cta'),
          onClick: () => {
            const start = provider === 'microsoft' ? startMicrosoftOAuth : startGoogleOAuth;
            start(location.pathname).then(({ auth_url }) => {
              if (auth_url) window.location.href = auth_url;
            });
          },
        },
      });
      return;
    }

    if (status === 'success') {
      markStepConnected('inbox', 'real');
      markStepConnected('calendar', 'real');
      const syncFn = provider === 'google' ? syncGoogleData : syncMicrosoftData;
      // Fire-and-forget: navigation above already happened.
      runProviderSync(provider, syncFn).then(({ ok, result, error }) => {
        if (ok) {
          toast.success(t('welcome.preview.real_connected_title_v2', { provider: label }), {
            description: t('welcome.preview.real_synced_desc', {
              account,
              emails: result?.counts?.emails ?? 0,
              events: result?.counts?.events ?? 0,
            }),
          });
        } else {
          toast.warning(t('welcome.preview.real_connected_no_sync_title_v2', { provider: label }), {
            description: error?.response?.data?.detail || t('welcome.preview.real_connected_no_sync_desc'),
          });
        }
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  return null;
}
