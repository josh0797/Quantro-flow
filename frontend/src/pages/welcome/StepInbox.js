import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import { Mail, Loader2, Check, ArrowRight } from 'lucide-react';

/**
 * Step 1 — Inbox. The most narratively-loaded step. The brief is
 * explicit: after the user taps "Connect Google" we play a 3-line
 * micro-interaction that *implies* the system is already analysing
 * their world. This is intentionally simulated by default — the
 * actual Gmail OAuth wiring lands later but the value perception
 * starts now.
 *
 * Three states:
 *   1. idle         — hero copy + Connect button
 *   2. analyzing    — three sequential lines fade in
 *   3. ready        — brief "connected" confirmation + auto-advance
 */
const PHASES = [
  { key: 'analyzing', delay_ms: 0    },
  { key: 'detecting', delay_ms: 1200 },
  { key: 'priorit',   delay_ms: 2400 },
];

export default function StepInbox() {
  const { t } = useLanguage();
  const { markStepConnected } = useOnboarding();
  const navigate = useNavigate();
  const [stage, setStage] = useState('idle'); // idle | analyzing | ready
  const [activePhases, setActivePhases] = useState([]);
  const timersRef = useRef([]);

  useEffect(() => () => {
    timersRef.current.forEach((id) => window.clearTimeout(id));
  }, []);

  const handleConnect = () => {
    setStage('analyzing');
    setActivePhases([]);
    PHASES.forEach((p) => {
      const id = window.setTimeout(() => {
        setActivePhases((arr) => [...arr, p.key]);
      }, p.delay_ms);
      timersRef.current.push(id);
    });
    // After the third line lands, give the user a beat then advance.
    const finishId = window.setTimeout(() => {
      setStage('ready');
      markStepConnected('inbox', 'simulated');
      const advanceId = window.setTimeout(() => {
        navigate('/welcome/calendar');
      }, 1100);
      timersRef.current.push(advanceId);
    }, 3700);
    timersRef.current.push(finishId);
  };

  return (
    <div className="flex flex-col items-center text-center" data-testid="step-inbox-page">
      <div
        className={[
          'size-16 rounded-2xl flex items-center justify-center mb-7',
          'bg-[hsl(var(--primary)/0.10)] text-[hsl(var(--primary))]',
          'transition-all duration-500 ease-out',
          stage === 'analyzing' && 'animate-pulse',
        ].filter(Boolean).join(' ')}
      >
        <Mail size={28} />
      </div>

      <h1
        className="font-display text-4xl md:text-5xl font-semibold tracking-tight mb-4 text-balance"
        data-testid="step-inbox-title"
      >
        {t('welcome.inbox.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-10 leading-relaxed text-balance whitespace-pre-line">
        {t('welcome.inbox.subtitle')}
      </p>

      {stage === 'idle' && (
        <div className="flex flex-col items-center gap-3">
          <button
            type="button"
            onClick={handleConnect}
            data-testid="step-inbox-connect-btn"
            className="inline-flex items-center gap-2.5 rounded-full bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.92)] text-[hsl(var(--primary-foreground))] px-7 py-3.5 text-sm font-semibold transition-all duration-300 ease-out hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary)/0.6)]"
          >
            <GoogleGlyph />
            {t('welcome.inbox.connect_cta')}
          </button>
          <button
            type="button"
            onClick={() => { markStepConnected('inbox', 'simulated'); navigate('/welcome/calendar'); }}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors duration-200"
            data-testid="step-inbox-skip"
          >
            {t('welcome.inbox.skip_cta')}
          </button>
        </div>
      )}

      {stage === 'analyzing' && (
        <div className="w-full max-w-md" data-testid="step-inbox-analyzing">
          <ul className="space-y-3 text-left">
            {PHASES.map((p) => {
              const visible = activePhases.includes(p.key);
              return (
                <li
                  key={p.key}
                  className={[
                    'flex items-center gap-3 rounded-xl border px-4 py-3',
                    'transition-all duration-500 ease-out',
                    visible
                      ? 'opacity-100 translate-y-0 border-[hsl(var(--primary)/0.30)] bg-[hsl(var(--primary)/0.05)]'
                      : 'opacity-0 translate-y-2 border-transparent',
                  ].join(' ')}
                  data-testid={`step-inbox-phase-${p.key}`}
                >
                  <Loader2 size={14} className="animate-spin text-[hsl(var(--primary))]" />
                  <span className="text-sm text-foreground/90">
                    {t(`welcome.inbox.phase_${p.key}`)}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {stage === 'ready' && (
        <div
          className="flex flex-col items-center gap-3 animate-in fade-in slide-in-from-bottom-1 duration-500"
          data-testid="step-inbox-ready"
        >
          <div className="inline-flex items-center gap-2 rounded-full bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] px-4 py-2 text-sm font-medium">
            <Check size={14} />
            {t('welcome.inbox.ready_label')}
          </div>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            {t('welcome.inbox.advancing')}
            <ArrowRight size={12} />
          </span>
        </div>
      )}
    </div>
  );
}

function GoogleGlyph() {
  // Tiny inline-SVG of the Google G so we don't drag a logo asset into
  // the bundle. Recolored in monochrome to read on a primary button.
  return (
    <svg width="15" height="15" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="currentColor" d="M44.5 20H24v8.5h11.8C34.7 33 30 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l6-6C34.5 5.7 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.6-.5-4z"/>
    </svg>
  );
}
