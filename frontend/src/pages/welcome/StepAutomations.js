import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import { Webhook, ArrowRight, Check, SkipForward } from 'lucide-react';

/**
 * Step 4 — Automations / Webhooks. Last optional step before the
 * Activation moment. Same connect/skip pattern as Calendar/CRM.
 */
export default function StepAutomations() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();
  const [connecting, setConnecting] = React.useState(false);
  const [done, setDone] = React.useState(false);

  const handleConnect = () => {
    setConnecting(true);
    window.setTimeout(() => {
      setDone(true);
      markStepConnected('automations', 'simulated');
      window.setTimeout(() => navigate('/welcome/ready'), 1100);
    }, 1100);
  };

  const handleSkip = () => {
    markStepSkipped('automations');
    navigate('/welcome/ready');
  };

  return (
    <div className="flex flex-col items-center text-center" data-testid="step-automations-page">
      <div className="size-16 rounded-2xl bg-[hsl(var(--accent)/0.12)] text-[hsl(var(--accent))] flex items-center justify-center mb-7">
        <Webhook size={28} />
      </div>
      <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground mb-3" data-testid="step-automations-eyebrow">
        {t('welcome.automations.eyebrow_optional')}
      </p>
      <h1 className="font-display text-4xl md:text-5xl font-semibold tracking-tight mb-4 text-balance" data-testid="step-automations-title">
        {t('welcome.automations.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 leading-relaxed text-balance whitespace-pre-line">
        {t('welcome.automations.subtitle')}
      </p>

      {!done && (
        <div className="flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={handleConnect}
            disabled={connecting}
            data-testid="step-automations-connect-btn"
            className="inline-flex items-center gap-2.5 rounded-full bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.92)] text-[hsl(var(--primary-foreground))] px-7 py-3.5 text-sm font-semibold transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:opacity-60 disabled:cursor-wait"
          >
            {connecting && <span className="size-3 rounded-full border-2 border-current border-t-transparent animate-spin" />}
            {t('welcome.automations.connect_cta')}
          </button>
          <button
            type="button"
            onClick={handleSkip}
            disabled={connecting}
            data-testid="step-automations-skip"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors duration-200 disabled:opacity-50"
          >
            <SkipForward size={12} />
            {t('welcome.automations.skip_cta')}
          </button>
        </div>
      )}

      {done && (
        <div className="flex flex-col items-center gap-3 animate-in fade-in slide-in-from-bottom-1 duration-500" data-testid="step-automations-done">
          <div className="inline-flex items-center gap-2 rounded-full bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] px-4 py-2 text-sm font-medium">
            <Check size={14} />
            {t('welcome.automations.ready_label')}
          </div>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            {t('welcome.automations.advancing')}
            <ArrowRight size={12} />
          </span>
        </div>
      )}
    </div>
  );
}
