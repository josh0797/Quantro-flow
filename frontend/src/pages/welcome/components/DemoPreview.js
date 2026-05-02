import React, { useEffect, useRef, useState } from 'react';
import { Loader2, Sparkles, ArrowRight, SkipForward, Check } from 'lucide-react';
import { useLanguage } from '../../../context/LanguageContext';

/**
 * DemoPreview — the shared "Preview → Connect" surface used by every
 * Flow Setup step. Renders in three sequential stages:
 *
 *   1. preview        — the visual mockup is shown while three phase
 *                       lines fade in to suggest the system thinking.
 *                       A small "Vista previa" badge sits on top so we
 *                       are never claiming the data is real.
 *   2. decision       — once the timer ends, we surface BOTH a primary
 *                       "Connect <provider>" CTA and a secondary
 *                       "Continue with demo" CTA. Honesty first: we
 *                       never auto-progress from a connect action that
 *                       didn't actually happen.
 *   3. connecting     — user clicked the primary CTA. We delegate to
 *                       the parent (`onConnect`) which is responsible
 *                       for kicking off the real OAuth flow once it's
 *                       implemented; today it shows a transient state.
 *
 * The skip button is intentionally always reachable (small text under
 * the primary CTA *and* the keyboard shortcut Esc) so an impatient
 * user is never trapped.
 */
export default function DemoPreview({
  badge,
  microcopyPreview,
  microcopyEnd,
  phases,
  previewDurationMs = 7000,
  connectLabel,
  connectIcon: ConnectIcon = null,
  connectingLabel,
  skipLabel,
  onConnect,
  onSkip,
  testIdPrefix,
  children,
}) {
  const { t } = useLanguage();
  const [stage, setStage] = useState('preview'); // preview | decision | connecting
  const [activePhases, setActivePhases] = useState([]);
  const timersRef = useRef([]);

  useEffect(() => {
    // Schedule each phase line to fade in at its configured delay.
    phases.forEach((p) => {
      const id = window.setTimeout(() => {
        setActivePhases((arr) => [...arr, p.key]);
      }, p.delay_ms);
      timersRef.current.push(id);
    });
    // After the configured duration, transition into the decision
    // stage. We add a small grace window over the last phase so the
    // user gets to read the final line before the CTAs slide in.
    const finishId = window.setTimeout(() => setStage('decision'), previewDurationMs);
    timersRef.current.push(finishId);
    return () => {
      timersRef.current.forEach((id) => window.clearTimeout(id));
      timersRef.current = [];
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Esc to skip — power-user affordance, doesn't block anyone.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && stage !== 'connecting') {
        onSkip?.();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [stage, onSkip]);

  const handleConnect = async () => {
    setStage('connecting');
    try {
      await onConnect?.();
    } catch {
      // Parent surfaces error toasts; we just bounce back to decision
      // so the user can retry or pick the demo path.
      setStage('decision');
    }
  };

  return (
    <div className="flex flex-col items-center w-full" data-testid={`${testIdPrefix}-demo-preview`}>
      {/* Eyebrow badge — honest labelling of the current state. We swap
          the copy between "Vista previa" (during preview/decision) and
          "Conectando" (during the connect attempt). */}
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--muted)/0.6)] border border-[hsl(var(--border))] px-3 py-1 text-[10px] uppercase tracking-[0.18em] font-semibold text-muted-foreground mb-4"
        data-testid={`${testIdPrefix}-stage-badge`}
      >
        <Sparkles size={11} className="text-[hsl(var(--primary))]" />
        {stage === 'connecting' ? t('welcome.preview.badge_connecting') : badge || t('welcome.preview.badge_preview')}
      </span>

      {/* Mockup container — surface the children with a subtle border
          so the demo content reads as a snippet of the real product. */}
      <div
        className={[
          'w-full max-w-2xl rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))]',
          'p-4 md:p-5 mb-6 transition-all duration-500 ease-out',
          stage === 'connecting' ? 'opacity-70 scale-[0.98]' : 'opacity-100 scale-100',
        ].join(' ')}
        data-testid={`${testIdPrefix}-mockup"`}
        aria-hidden={stage === 'connecting'}
      >
        {children}
      </div>

      {/* Phase lines — only meaningful while we're in the preview stage.
          Stay mounted (with reduced height) during decision so the page
          height doesn't jump when CTAs appear. */}
      <ul
        className={[
          'w-full max-w-md space-y-2 transition-all duration-500 ease-out',
          stage === 'preview' ? 'opacity-100 max-h-48 mb-6' : 'opacity-0 max-h-0 mb-0 overflow-hidden',
        ].join(' ')}
        data-testid={`${testIdPrefix}-phases`}
      >
        {phases.map((p) => {
          const visible = activePhases.includes(p.key);
          return (
            <li
              key={p.key}
              className={[
                'flex items-center gap-3 rounded-xl border px-4 py-2.5 text-sm',
                'transition-all duration-500 ease-out',
                visible
                  ? 'opacity-100 translate-y-0 border-[hsl(var(--primary)/0.30)] bg-[hsl(var(--primary)/0.05)]'
                  : 'opacity-0 translate-y-1 border-transparent',
              ].join(' ')}
              data-testid={`${testIdPrefix}-phase-${p.key}`}
            >
              <Loader2 size={13} className="animate-spin text-[hsl(var(--primary))]" />
              <span className="text-foreground/90">{p.label}</span>
            </li>
          );
        })}
      </ul>

      {/* Microcopy — explains exactly what the user is looking at. The
          copy crossfades between "this is how it will look" and "now
          connect for real data". */}
      <p
        className={[
          'text-center text-sm md:text-base text-muted-foreground max-w-xl mb-8 leading-relaxed',
          'transition-all duration-500 ease-out',
        ].join(' ')}
        data-testid={`${testIdPrefix}-microcopy`}
      >
        {stage === 'preview' ? microcopyPreview : microcopyEnd}
      </p>

      {/* CTAs — only render in decision/connecting. The skip button is
          intentionally subdued but always present so we never feel
          coercive. */}
      <div
        className={[
          'flex flex-col items-center gap-3 transition-all duration-500 ease-out',
          stage === 'preview'
            ? 'opacity-0 translate-y-2 pointer-events-none'
            : 'opacity-100 translate-y-0',
        ].join(' ')}
      >
        <button
          type="button"
          onClick={handleConnect}
          disabled={stage === 'connecting'}
          data-testid={`${testIdPrefix}-connect-btn`}
          className="inline-flex items-center gap-2.5 rounded-full bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.92)] text-[hsl(var(--primary-foreground))] px-7 py-3.5 text-sm font-semibold transition-all duration-300 ease-out hover:-translate-y-0.5 disabled:opacity-70 disabled:cursor-wait disabled:hover:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary)/0.6)]"
        >
          {stage === 'connecting' ? (
            <>
              <Loader2 size={14} className="animate-spin" />
              {connectingLabel || t('welcome.preview.connecting')}
            </>
          ) : (
            <>
              {ConnectIcon ? <ConnectIcon size={15} /> : null}
              {connectLabel}
              <ArrowRight size={14} />
            </>
          )}
        </button>
        <button
          type="button"
          onClick={onSkip}
          disabled={stage === 'connecting'}
          data-testid={`${testIdPrefix}-skip-btn`}
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors duration-200 disabled:opacity-50"
        >
          <SkipForward size={12} />
          {skipLabel || t('welcome.preview.continue_demo')}
        </button>
      </div>
    </div>
  );
}

/**
 * <DemoPreviewBadge> — small reusable badge other surfaces (Smart
 * Inbox banner, dashboard widgets) can drop in to label demo data.
 */
export function DemoPreviewBadge({ mode = 'demo', testid }) {
  const { t } = useLanguage();
  const isReal = mode === 'real';
  return (
    <span
      className={[
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] uppercase tracking-[0.16em] font-semibold border',
        isReal
          ? 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.30)]'
          : 'bg-[hsl(var(--muted)/0.6)] text-muted-foreground border-[hsl(var(--border))]',
      ].join(' ')}
      data-testid={testid || 'demo-preview-badge'}
    >
      {isReal ? <Check size={10} /> : <Sparkles size={10} />}
      {isReal ? t('welcome.preview.badge_real') : t('welcome.preview.badge_demo')}
    </span>
  );
}
