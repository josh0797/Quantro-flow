import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../../context/LanguageContext';
import { Sparkles, Check, ArrowRight } from 'lucide-react';

/**
 * Checkout placeholder — the brief calls for a Checkout step between
 * Start Choice and Flow Setup. We're deliberately NOT launching the
 * full Stripe Checkout flow during onboarding (it lives at /plan and
 * causes a 30s+ external detour that breaks the "system turning on"
 * narrative). Instead, we celebrate that the Starter plan is already
 * active and offer a soft upsell path that lives in the rest of the
 * product. The visual cadence stays identical to a real activation
 * step so users don't feel cheated.
 */
export default function Checkout() {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [pulseDone, setPulseDone] = useState(false);

  useEffect(() => {
    const id = window.setTimeout(() => setPulseDone(true), 700);
    return () => window.clearTimeout(id);
  }, []);

  return (
    <div className="flex flex-col items-center text-center" data-testid="checkout-page">
      {/* Visual: a calm "activated" badge that pulses once on mount and
          then settles. The intent is to tell the user the system is
          alive without celebratory confetti or noisy modals. */}
      <div
        className={[
          'relative size-20 rounded-2xl flex items-center justify-center mb-8',
          'bg-[hsl(var(--primary)/0.10)] text-[hsl(var(--primary))]',
          'transition-all duration-500 ease-out',
          pulseDone ? 'scale-100' : 'scale-90',
        ].join(' ')}
      >
        <Check size={36} strokeWidth={2.4} />
        <span
          className={[
            'absolute inset-0 rounded-2xl border-2 border-[hsl(var(--primary)/0.4)]',
            'transition-all duration-700 ease-out',
            pulseDone ? 'scale-150 opacity-0' : 'scale-100 opacity-100',
          ].join(' ')}
          aria-hidden="true"
        />
      </div>

      <p className="text-sm uppercase tracking-[0.18em] text-[hsl(var(--primary))] mb-3" data-testid="checkout-eyebrow">
        {t('welcome.checkout.eyebrow')}
      </p>
      <h1
        className="font-display text-4xl md:text-5xl font-semibold tracking-tight mb-4 text-balance"
        data-testid="checkout-title"
      >
        {t('welcome.checkout.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 text-balance">
        {t('welcome.checkout.subtitle')}
      </p>

      <div className="w-full max-w-md rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-6 mb-10 text-left">
        <div className="flex items-center gap-3 mb-4">
          <Sparkles size={18} className="text-[hsl(var(--primary))]" />
          <span className="text-sm font-semibold tracking-tight">
            {t('welcome.checkout.plan_starter_name')}
          </span>
          <span className="ml-auto text-[10px] uppercase tracking-[0.16em] font-semibold text-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.12)] rounded-full px-2 py-0.5">
            {t('welcome.checkout.plan_active_badge')}
          </span>
        </div>
        <ul className="space-y-2.5 text-sm text-muted-foreground">
          {['feat_inbox', 'feat_calendar', 'feat_crm', 'feat_automations'].map((k) => (
            <li key={k} className="flex items-start gap-2.5">
              <Check size={14} className="mt-0.5 text-[hsl(var(--primary))] shrink-0" />
              <span>{t(`welcome.checkout.${k}`)}</span>
            </li>
          ))}
        </ul>
      </div>

      <button
        type="button"
        onClick={() => navigate('/welcome/inbox')}
        data-testid="checkout-continue-btn"
        className="inline-flex items-center gap-2 rounded-full bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.92)] text-[hsl(var(--primary-foreground))] px-7 py-3.5 text-sm font-semibold transition-all duration-300 ease-out hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary)/0.6)]"
      >
        {t('welcome.checkout.continue_cta')}
        <ArrowRight size={16} />
      </button>
      <button
        type="button"
        onClick={() => navigate('/plan')}
        className="mt-4 text-xs text-muted-foreground hover:text-foreground transition-colors duration-200"
        data-testid="checkout-upgrade-link"
      >
        {t('welcome.checkout.upgrade_link')}
      </button>
    </div>
  );
}
