import React, { useState } from 'react';
import { Loader2, ArrowRight } from 'lucide-react';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { useLanguage } from '../../../context/LanguageContext';
import { startGoogleOAuth, startMicrosoftOAuth } from '../../../lib/api';

/**
 * ProviderConnectModal — single, opinionated picker for the
 * Preview→Connect onboarding steps. The user clicked the primary
 * "Conectar" CTA in StepInbox / StepCalendar; we open this modal so
 * they can choose between Google (Gmail/Calendar) and Microsoft
 * (Outlook/Calendar). The pick triggers a full-page redirect to the
 * provider's OAuth consent screen — popups break on Safari and lose
 * context on mobile, so we always do a top-level navigation.
 *
 * On error (server returns 503 because credentials aren't configured,
 * or the request fails) we surface the detail through a toast and
 * keep the user inside the modal so they can pick the other provider
 * or close it.
 *
 * The modal is fully controlled (`open`, `onOpenChange`) so the parent
 * can also close it from a Skip action or when the OAuth flow takes
 * the user away.
 */
export default function ProviderConnectModal({
  open,
  onOpenChange,
  step,            // 'inbox' | 'calendar'
  returnTo,        // e.g. '/welcome/inbox'
  onProviderError,
}) {
  const { t } = useLanguage();
  const [redirecting, setRedirecting] = useState(null); // 'google' | 'microsoft' | null

  const handlePick = async (provider) => {
    setRedirecting(provider);
    try {
      const startFn = provider === 'google' ? startGoogleOAuth : startMicrosoftOAuth;
      const { auth_url } = await startFn(returnTo);
      if (!auth_url) throw new Error('no auth_url returned');
      // Top-level redirect — provider callback bounces back to
      // returnTo with ?google_connected=success / ?microsoft_connected=success.
      window.location.href = auth_url;
      // Keep the spinner active until the browser actually navigates;
      // the modal will be unmounted by the route change.
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const desc =
        typeof detail === 'string'
          ? detail
          : t(`welcome.connect_modal.${provider}_unavailable_desc`);
      toast.error(t(`welcome.connect_modal.${provider}_failed_title`), { description: desc });
      setRedirecting(null);
      onProviderError?.(provider, err);
    }
  };

  const stepTitleKey = step === 'calendar' ? 'welcome.connect_modal.title_calendar' : 'welcome.connect_modal.title_inbox';
  const stepDescKey = step === 'calendar' ? 'welcome.connect_modal.desc_calendar' : 'welcome.connect_modal.desc_inbox';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md p-0 overflow-hidden bg-[hsl(var(--card))] border-[hsl(var(--border))]"
        data-testid="provider-connect-modal"
      >
        <div className="px-6 pt-6 pb-2">
          <DialogHeader className="text-left">
            <DialogTitle className="text-xl font-semibold tracking-tight" data-testid="provider-connect-title">
              {t(stepTitleKey)}
            </DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground leading-relaxed" data-testid="provider-connect-subtitle">
              {t(stepDescKey)}
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="px-6 pb-6 pt-4 space-y-3">
          <ProviderCard
            provider="google"
            disabled={redirecting !== null}
            redirecting={redirecting === 'google'}
            title={t('welcome.connect_modal.google_title')}
            subtitle={t('welcome.connect_modal.google_subtitle')}
            onClick={() => handlePick('google')}
            testid="provider-pick-google"
          />
          <ProviderCard
            provider="microsoft"
            disabled={redirecting !== null}
            redirecting={redirecting === 'microsoft'}
            title={t('welcome.connect_modal.microsoft_title')}
            subtitle={t('welcome.connect_modal.microsoft_subtitle')}
            onClick={() => handlePick('microsoft')}
            testid="provider-pick-microsoft"
          />

          <p className="text-[11px] text-muted-foreground/80 leading-relaxed pt-2" data-testid="provider-connect-footnote">
            {t('welcome.connect_modal.footnote')}
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * ProviderCard — clickable row showing the provider logo (rendered as
 * inline SVG so we don't depend on external images), name and a short
 * subtitle ("Gmail · Calendar"). Hover lifts a 1px and border tightens
 * to the brand cyan; selected state shows a spinner replacing the
 * arrow.
 */
function ProviderCard({ provider, title, subtitle, onClick, disabled, redirecting, testid }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testid}
      className={[
        'w-full text-left flex items-center gap-4 rounded-xl border px-4 py-3.5',
        'bg-[hsl(var(--background))] border-[hsl(var(--border))]',
        'transition-all duration-200 ease-out',
        'hover:border-[hsl(var(--primary)/0.55)] hover:-translate-y-0.5 hover:bg-[hsl(var(--primary)/0.04)]',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary)/0.55)]',
        'disabled:opacity-60 disabled:cursor-wait disabled:hover:translate-y-0 disabled:hover:bg-transparent',
      ].join(' ')}
    >
      <span className="shrink-0 size-10 rounded-lg bg-[hsl(var(--muted)/0.7)] border border-[hsl(var(--border))] flex items-center justify-center">
        {provider === 'google' ? <GoogleGlyph /> : <MicrosoftGlyph />}
      </span>
      <span className="flex-1 min-w-0">
        <span className="block text-sm font-semibold text-foreground">{title}</span>
        <span className="block text-[11px] text-muted-foreground tracking-wide">{subtitle}</span>
      </span>
      {redirecting ? (
        <Loader2 size={16} className="text-[hsl(var(--primary))] animate-spin" />
      ) : (
        <ArrowRight size={16} className="text-muted-foreground" />
      )}
    </button>
  );
}

function GoogleGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.56c2.08-1.92 3.28-4.74 3.28-8.09z"/>
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.56-2.76c-.99.66-2.25 1.06-3.72 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"/>
      <path fill="#FBBC05" d="M5.84 14.11A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.44.34-2.11V7.05H2.18A11 11 0 0 0 1 12c0 1.77.42 3.45 1.18 4.95l3.66-2.84z"/>
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.07.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.05l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"/>
    </svg>
  );
}

function MicrosoftGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <rect x="2"  y="2"  width="9" height="9" fill="#F25022" />
      <rect x="13" y="2"  width="9" height="9" fill="#7FBA00" />
      <rect x="2"  y="13" width="9" height="9" fill="#00A4EF" />
      <rect x="13" y="13" width="9" height="9" fill="#FFB900" />
    </svg>
  );
}
