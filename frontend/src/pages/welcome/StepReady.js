import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../../context/LanguageContext';
import { useAuth } from '../../contexts/AuthContext';
import { useOnboarding } from './OnboardingContext';
import { ArrowRight, Loader2 } from 'lucide-react';
import { supabase } from '../../lib/supabaseClient';
import { completeWelcomeOnboarding } from '../../lib/api';

/**
 * Step Final — Activación. The narrative climax.
 *
 * Sequence:
 *   1. On mount, kick off completeWelcomeOnboarding(...) which on the
 *      backend:
 *        • enables Simulation Mode for the workspace,
 *        • ensures the simulation seed exists for the chosen industry,
 *        • returns real counters for inbox / crm / calendar so we can
 *          pin them in the hero copy.
 *   2. Once we have counters, render the "Quantro is operating with
 *      you" headline with the real numbers and a single CTA into the
 *      Smart Inbox.
 *   3. On CTA tap, refresh the AuthContext (so needs_onboarding flips
 *      to false in the cached user object) and route into /inbox.
 */
export default function StepReady() {
  const { t } = useLanguage();
  const { user, refresh } = useAuth();
  const { state, reset } = useOnboarding();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [counters, setCounters] = useState({ conversations: 0, opportunities: 0, contacts: 0, events: 0 });
  const [advancing, setAdvancing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await completeWelcomeOnboarding({
          industry: state.industry || 'other',
          start_choice: state.start_choice || 'email',
          inbox_connected: !!state.inbox_connected,
          calendar_connected: !!state.calendar_connected,
          crm_connected: !!state.crm_connected,
          automations_connected: !!state.automations_connected,
        });
        // Mark Supabase user_metadata so ProtectedRoute stops sending the
        // user back to /welcome on reload. We do this in parallel with
        // the backend call — worst case the metadata flip lands a tick
        // later and the user sees one extra fade-in, never a redirect.
        try {
          await supabase.auth.updateUser({ data: { needs_onboarding: false } });
        } catch {
          /* non-blocking; we still allow navigation below */
        }
        if (!cancelled) setCounters(res?.counters || {});
      } catch {
        // Even if the activation call fails we don't want to trap the
        // user. Surface a graceful zero-state and let them click into
        // the inbox — they can re-trigger Simulation Mode from Settings.
        if (!cancelled) setCounters({ conversations: 0, opportunities: 0, contacts: 0, events: 0 });
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const firstName = (user?.name || '').trim().split(' ')[0];

  const handleEnter = async () => {
    setAdvancing(true);
    try {
      await refresh?.();
    } finally {
      reset();
      navigate('/inbox', { replace: true });
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center text-center" data-testid="step-ready-loading">
        <Loader2 size={28} className="animate-spin text-[hsl(var(--primary))] mb-6" />
        <p className="text-base text-muted-foreground">
          {t('welcome.ready.activating')}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center text-center" data-testid="step-ready-page">
      <p className="text-xs uppercase tracking-[0.18em] text-[hsl(var(--primary))] mb-3" data-testid="step-ready-eyebrow">
        {t('welcome.ready.eyebrow')}
      </p>
      <h1
        className="font-display text-4xl md:text-6xl font-semibold tracking-tight mb-6 text-balance"
        data-testid="step-ready-title"
      >
        {firstName
          ? t('welcome.ready.title_with_name', { name: firstName })
          : t('welcome.ready.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 leading-relaxed text-balance">
        {t('welcome.ready.subtitle')}
      </p>

      <div
        className="w-full max-w-2xl rounded-2xl border border-[hsl(var(--primary)/0.25)] bg-[hsl(var(--primary)/0.04)] p-6 md:p-8 mb-10 text-left"
        data-testid="step-ready-counters"
      >
        <p className="text-xs uppercase tracking-[0.16em] font-semibold text-[hsl(var(--primary))] mb-5">
          {t('welcome.ready.detected_label')}
        </p>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4">
          <ReadyMetric label={t('welcome.ready.metric_conversations')} value={counters.conversations} testid="metric-conversations" />
          <ReadyMetric label={t('welcome.ready.metric_opportunities')} value={counters.opportunities} testid="metric-opportunities" />
          <ReadyMetric label={t('welcome.ready.metric_contacts')} value={counters.contacts} testid="metric-contacts" />
          <ReadyMetric label={t('welcome.ready.metric_events')} value={counters.events} testid="metric-events" />
        </ul>
      </div>

      <button
        type="button"
        onClick={handleEnter}
        disabled={advancing}
        data-testid="step-ready-cta"
        className="inline-flex items-center gap-2 rounded-full bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.92)] text-[hsl(var(--primary-foreground))] px-8 py-4 text-base font-semibold transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:opacity-60 disabled:cursor-wait focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary)/0.6)]"
      >
        {advancing && <span className="size-3 rounded-full border-2 border-current border-t-transparent animate-spin" />}
        {t('welcome.ready.enter_cta')}
        <ArrowRight size={18} />
      </button>
    </div>
  );
}

function ReadyMetric({ label, value, testid }) {
  const numeric = Number.isFinite(Number(value)) ? Number(value) : 0;
  return (
    <li className="flex items-baseline gap-3" data-testid={`step-ready-${testid}`}>
      <span className="text-3xl md:text-4xl font-semibold tracking-tight tabular-nums text-foreground">
        {numeric}
      </span>
      <span className="text-sm text-muted-foreground">{label}</span>
    </li>
  );
}
