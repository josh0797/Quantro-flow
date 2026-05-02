import React from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import DemoPreview from './components/DemoPreview';
import InboxMockup from './components/InboxMockup';
import { Mail } from 'lucide-react';
import { startGoogleOAuth } from '../../lib/api';

/**
 * Step 1 — Inbox. Preview → Connect pattern wired to the real Google
 * OAuth flow. Click on Connect: we call /api/integrations/google/start,
 * which returns a Google authorization URL. We hand the browser to
 * Google (full-page redirect, NOT popup — popups break on Safari and
 * lose context on mobile). After consent, Google bounces the user back
 * to /api/integrations/google/callback which redirects to
 * /welcome/inbox?google_connected=success&account=... — the
 * OnboardingShell picks up that query param and triggers /sync, then
 * marks connection_mode='real'.
 *
 * Failure paths (cancel, scope deny, network) come back with
 * ?google_connected=error and we keep the user in demo mode without
 * lying.
 */
export default function StepInbox() {
  const { t } = useLanguage();
  const { markStepConnected, markStepSkipped } = useOnboarding();
  const navigate = useNavigate();

  const handleConnect = async () => {
    try {
      const { auth_url } = await startGoogleOAuth('/welcome/inbox');
      if (!auth_url) throw new Error('no auth_url returned');
      // Full-page redirect — onAuthStateChange / OnboardingShell will
      // resume the flow once Google sends the user back.
      window.location.href = auth_url;
    } catch (err) {
      // 503 = OAuth not configured server-side. We still let the user
      // proceed in demo mode rather than blocking.
      const detail = err?.response?.data?.detail;
      const desc = typeof detail === 'string' ? detail : t('welcome.preview.real_pending_desc');
      toast.error(t('welcome.preview.real_failed_title'), { description: desc });
      markStepSkipped('inbox');
      navigate('/welcome/calendar');
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
    </div>
  );
}
