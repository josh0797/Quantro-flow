import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import DemoPreview from './components/DemoPreview';
import CalendarMockup from './components/CalendarMockup';
import ProviderConnectModal from './components/ProviderConnectModal';
import { CalendarDays } from 'lucide-react';
import { getGoogleIntegrationStatus, getMicrosoftIntegrationStatus } from '../../lib/api';

export default function StepCalendar() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();
  const [pickerOpen, setPickerOpen] = useState(false);

  // If either Google or Microsoft is already connected from StepInbox
  // (the OAuth scopes for Mail include Calendar in both providers),
  // we don't bother running OAuth again — just mark the step real and
  // advance.
  const handleConnect = async () => {
    try {
      const [g, m] = await Promise.all([
        getGoogleIntegrationStatus().catch(() => null),
        getMicrosoftIntegrationStatus().catch(() => null),
      ]);
      const alreadyConnected = g?.connected || m?.connected;
      if (alreadyConnected) {
        const account = g?.connected ? (g.account_email || 'Google') : (m?.account_email || 'Microsoft');
        markStepConnected('calendar', 'real');
        toast.success(t('welcome.calendar.already_connected_title'), {
          description: t('welcome.calendar.already_connected_desc', { account }),
        });
        navigate('/welcome/crm');
        return;
      }
    } catch {
      /* status calls failed — fall through and let the user pick. */
    }

    // Open picker. Promise stays pending so DemoPreview keeps its
    // 'connecting' spinner while the user decides.
    return new Promise((resolve) => {
      setPickerOpen(true);
      window.__quantroPickerResolve = resolve;
    });
  };

  const handleOpenChange = (open) => {
    setPickerOpen(open);
    if (!open) {
      window.__quantroPickerResolve?.();
      window.__quantroPickerResolve = null;
    }
  };

  const handleSkip = () => {
    markStepSkipped('calendar');
    markStepConnected('calendar', 'demo');
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

      <ProviderConnectModal
        open={pickerOpen}
        onOpenChange={handleOpenChange}
        step="calendar"
        returnTo="/welcome/calendar"
      />
    </div>
  );
}
