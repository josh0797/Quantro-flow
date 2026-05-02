import React from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import DemoPreview from './components/DemoPreview';
import InboxMockup from './components/InboxMockup';
import { Mail } from 'lucide-react';

/**
 * Step 1 — Inbox. Preview → Connect pattern.
 *
 *   1. Show InboxMockup for ~7s while phase lines fade in.
 *   2. Surface CTA pair: "Conectar con Google" / "Continuar con demo".
 *   3. Connect path is wired to start the Google OAuth flow once it
 *      lands; today it surfaces a transparent toast and falls back to
 *      demo mode (we never claim a connection that didn't happen).
 */
export default function StepInbox() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();

  const handleConnect = async () => {
    // Real OAuth wiring lives in Phase B. Until those credentials land
    // we explicitly tell the user the flow is upcoming and keep them
    // in demo mode — honesty over fake "connected" badges.
    toast.info(t('welcome.preview.real_pending_title'), {
      description: t('welcome.preview.real_pending_desc'),
    });
    markStepConnected('inbox', 'demo');
    window.setTimeout(() => navigate('/welcome/calendar'), 600);
  };

  const handleSkip = () => {
    markStepSkipped('inbox');
    navigate('/welcome/calendar');
  };

  return (
    <div className="flex flex-col items-center text-center" data-testid="step-inbox-page">
      <div className="size-16 rounded-2xl bg-[hsl(var(--primary)/0.10)] text-[hsl(var(--primary))] flex items-center justify-center mb-6">
        <Mail size={28} />
      </div>
      <h1 className="font-display text-3xl md:text-5xl font-semibold tracking-tight mb-3 text-balance" data-testid="step-inbox-title">
        {t('welcome.inbox.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 leading-relaxed text-balance whitespace-pre-line">
        {t('welcome.inbox.subtitle')}
      </p>

      <DemoPreview
        testIdPrefix="step-inbox"
        microcopyPreview={t('welcome.inbox.preview_microcopy')}
        microcopyEnd={t('welcome.inbox.preview_end_microcopy')}
        connectLabel={t('welcome.inbox.connect_cta')}
        skipLabel={t('welcome.inbox.skip_cta')}
        phases={[
          { key: 'analyzing', delay_ms: 0,    label: t('welcome.inbox.phase_analyzing') },
          { key: 'detecting', delay_ms: 1800, label: t('welcome.inbox.phase_detecting') },
          { key: 'priorit',   delay_ms: 3600, label: t('welcome.inbox.phase_priorit')   },
        ]}
        previewDurationMs={7000}
        onConnect={handleConnect}
        onSkip={handleSkip}
      >
        <InboxMockup />
      </DemoPreview>
    </div>
  );
}
