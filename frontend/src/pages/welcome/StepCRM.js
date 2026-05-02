import React from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import DemoPreview from './components/DemoPreview';
import CRMMockup from './components/CRMMockup';
import { Users2 } from 'lucide-react';

export default function StepCRM() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();

  const handleConnect = async () => {
    toast.info(t('welcome.preview.real_pending_title'), {
      description: t('welcome.preview.real_pending_desc_crm'),
    });
    markStepConnected('crm', 'demo');
    window.setTimeout(() => navigate('/welcome/automations'), 600);
  };

  const handleSkip = () => {
    markStepSkipped('crm');
    navigate('/welcome/automations');
  };

  return (
    <div className="flex flex-col items-center text-center" data-testid="step-crm-page">
      <div className="size-16 rounded-2xl bg-[hsl(var(--accent)/0.12)] text-[hsl(var(--accent))] flex items-center justify-center mb-6">
        <Users2 size={28} />
      </div>
      <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground mb-3" data-testid="step-crm-eyebrow">
        {t('welcome.crm.eyebrow_optional')}
      </p>
      <h1 className="font-display text-3xl md:text-5xl font-semibold tracking-tight mb-3 text-balance" data-testid="step-crm-title">
        {t('welcome.crm.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 leading-relaxed text-balance whitespace-pre-line">
        {t('welcome.crm.subtitle')}
      </p>

      <DemoPreview
        testIdPrefix="step-crm"
        microcopyPreview={t('welcome.crm.preview_microcopy')}
        microcopyEnd={t('welcome.crm.preview_end_microcopy')}
        connectLabel={t('welcome.crm.connect_cta')}
        skipLabel={t('welcome.crm.skip_cta')}
        phases={[
          { key: 'matching',  delay_ms: 0,    label: t('welcome.crm.phase_matching')  },
          { key: 'staging',   delay_ms: 1800, label: t('welcome.crm.phase_staging')   },
          { key: 'flagging',  delay_ms: 3600, label: t('welcome.crm.phase_flagging')  },
        ]}
        previewDurationMs={7000}
        onConnect={handleConnect}
        onSkip={handleSkip}
      >
        <CRMMockup />
      </DemoPreview>
    </div>
  );
}
