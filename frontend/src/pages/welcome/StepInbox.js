import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import DemoPreview from './components/DemoPreview';
import InboxMockup from './components/InboxMockup';
import ProviderConnectModal from './components/ProviderConnectModal';
import { Mail } from 'lucide-react';

/**
 * Step 1 — Inbox. Preview → Connect, multi-provider edition.
 *
 * The CTA "Conectar" no longer redirects directly to Google. It opens
 * a small modal where the user can pick Google (Gmail) or Microsoft
 * (Outlook). The actual OAuth bootstrap lives inside
 * <ProviderConnectModal /> — once the user picks a provider we do a
 * full-page redirect to the consent screen. The provider callback
 * bounces back with ?<provider>_connected=success and the
 * <OnboardingShell /> picks it up to run the sync.
 *
 * Skip path: marks the step as demo, advances to /welcome/calendar.
 */
export default function StepInbox() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();
  const [pickerOpen, setPickerOpen] = useState(false);

  // Note: DemoPreview's onConnect awaits the returned promise. Resolving
  // *before* the redirect happens would put DemoPreview back into
  // 'decision' stage; instead we keep the promise pending so the spinner
  // remains until the browser actually navigates. If the user closes
  // the modal we resolve manually so DemoPreview returns to its
  // decision state.
  const handleConnect = () => {
    return new Promise((resolve) => {
      setPickerOpen(true);
      // Stash resolver on the window so we can call it from the
      // onOpenChange handler without prop-drilling.
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
    markStepSkipped('inbox');
    markStepConnected('inbox', 'demo');
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

      <ProviderConnectModal
        open={pickerOpen}
        onOpenChange={handleOpenChange}
        step="inbox"
        returnTo="/welcome/inbox"
      />
    </div>
  );
}
