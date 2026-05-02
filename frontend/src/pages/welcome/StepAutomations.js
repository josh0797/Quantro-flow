import React from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import DemoPreview from './components/DemoPreview';
import WebhooksMockup from './components/WebhooksMockup';
import { Webhook } from 'lucide-react';

export default function StepAutomations() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();

  const handleConnect = async () => {
    toast.info(t('welcome.preview.real_pending_title'), {
      description: t('welcome.preview.real_pending_desc_webhooks'),
    });
    markStepConnected('automations', 'demo');
    window.setTimeout(() => navigate('/welcome/ready'), 600);
  };

  const handleSkip = () => {
    markStepSkipped('automations');
    navigate('/welcome/ready');
  };

  return (
    <div className="flex flex-col items-center text-center" data-testid="step-automations-page">
      <div className="size-16 rounded-2xl bg-[hsl(var(--accent)/0.12)] text-[hsl(var(--accent))] flex items-center justify-center mb-6">
        <Webhook size={28} />
      </div>
      <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground mb-3" data-testid="step-automations-eyebrow">
        {t('welcome.automations.eyebrow_optional')}
      </p>
      <h1 className="font-display text-3xl md:text-5xl font-semibold tracking-tight mb-3 text-balance" data-testid="step-automations-title">
        {t('welcome.automations.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 leading-relaxed text-balance whitespace-pre-line">
        {t('welcome.automations.subtitle')}
      </p>

      <DemoPreview
        testIdPrefix="step-automations"
        microcopyPreview={t('welcome.automations.preview_microcopy')}
        microcopyEnd={t('welcome.automations.preview_end_microcopy')}
        connectLabel={t('welcome.automations.connect_cta')}
        skipLabel={t('welcome.automations.skip_cta')}
        phases={[
          { key: 'listening',  delay_ms: 0,    label: t('welcome.automations.phase_listening') },
          { key: 'classifying', delay_ms: 1800, label: t('welcome.automations.phase_classifying') },
          { key: 'reacting',   delay_ms: 3600, label: t('welcome.automations.phase_reacting') },
        ]}
        previewDurationMs={7000}
        onConnect={handleConnect}
        onSkip={handleSkip}
      >
        <WebhooksMockup />
      </DemoPreview>
    </div>
  );
}
