import React, { useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useLanguage } from '../../context/LanguageContext';
import { OnboardingProvider } from './OnboardingContext';
import { Zap, LogOut } from 'lucide-react';

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
 * child route — the shell only renders identity, progress and exit.
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
    <OnboardingProvider>
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

          <button
            type="button"
            onClick={handleSignOut}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors duration-200 inline-flex items-center gap-1.5"
            data-testid="onboarding-signout"
          >
            <LogOut size={12} />
            {t('welcome.sign_out')}
          </button>
        </header>

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
