import React from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import DemoPreview from './components/DemoPreview';
import CalendarMockup from './components/CalendarMockup';
import { CalendarDays } from 'lucide-react';

export default function StepCalendar() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();

  const handleConnect = async () => {
    toast.info(t('welcome.preview.real_pending_title'), {
      description: t('welcome.preview.real_pending_desc'),
    });
    markStepConnected('calendar', 'demo');
    window.setTimeout(() => navigate('/welcome/crm'), 600);
  };

  const handleSkip = () => {
    markStepSkipped('calendar');
    navigate('/welcome/crm');
  };

  return (
    <div className="flex flex-col items-center text-center" data-testid="step-calendar-page">
      <div className="size-16 rounded-2xl bg-[hsl(var(--primary)/0.10)] text-[hsl(var(--primary))] flex items-center justify-center mb-6">
        <CalendarDays size={28} />
      </div>
      <h1 className="font-display text-3xl md:text-5xl font-semibold tracking-tight mb-3 text-balance" data-testid="step-calendar-title">
        {t('welcome.calendar.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 leading-relaxed text-balance whitespace-pre-line">
        {t('welcome.calendar.subtitle')}
      </p>

      <DemoPreview
        testIdPrefix="step-calendar"
        microcopyPreview={t('welcome.calendar.preview_microcopy')}
        microcopyEnd={t('welcome.calendar.preview_end_microcopy')}
        connectLabel={t('welcome.calendar.connect_cta')}
        skipLabel={t('welcome.calendar.skip_cta')}
        phases={[
          { key: 'syncing',   delay_ms: 0,    label: t('welcome.calendar.phase_syncing')   },
          { key: 'detecting', delay_ms: 1800, label: t('welcome.calendar.phase_detecting') },
          { key: 'aligning',  delay_ms: 3600, label: t('welcome.calendar.phase_aligning')  },
        ]}
        previewDurationMs={7000}
        onConnect={handleConnect}
        onSkip={handleSkip}
      >
        <CalendarMockup />
      </DemoPreview>
    </div>
  );
}
