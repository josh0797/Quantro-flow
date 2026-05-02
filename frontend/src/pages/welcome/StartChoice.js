import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../../context/LanguageContext';
import { useOnboarding } from './OnboardingContext';
import { Mail, Wrench, Compass, ArrowRight } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';

/**
 * Start Choice — three Apple-style cards. Zero forms, zero dropdowns.
 * The selection is recorded in OnboardingContext so the next steps
 * can adapt their tone, but every choice still goes through the full
 * Flow Setup (Inbox → Calendar → CRM → Automations → Ready) so we
 * preserve the "system turning on, step by step" narrative.
 */
const CHOICES = [
  { key: 'email',   icon: Mail,    primary: true  },
  { key: 'tools',   icon: Wrench,  primary: false },
  { key: 'explore', icon: Compass, primary: false },
];

export default function StartChoice() {
  const { t } = useLanguage();
  const { setStartChoice } = useOnboarding();
  const { user } = useAuth();
  const navigate = useNavigate();

  const firstName = (user?.name || '').trim().split(' ')[0];

  const handlePick = (choiceKey) => {
    setStartChoice(choiceKey);
    // Every path leads to the same Flow Setup. The choice biases tone
    // & subsequent recommendations but never bypasses Inbox setup —
    // that's the highest-value first touch.
    navigate('/welcome/checkout');
  };

  return (
    <div className="flex flex-col items-center text-center" data-testid="start-choice-page">
      <p
        className="text-sm text-muted-foreground mb-3"
        data-testid="start-choice-eyebrow"
      >
        {firstName
          ? t('welcome.start.eyebrow_with_name', { name: firstName })
          : t('welcome.start.eyebrow')}
      </p>
      <h1
        className="font-display text-4xl md:text-5xl lg:text-6xl font-semibold tracking-tight mb-4 text-balance"
        data-testid="start-choice-title"
      >
        {t('welcome.start.title')}
      </h1>
      <p className="text-base md:text-lg text-muted-foreground max-w-xl mb-14 text-balance">
        {t('welcome.start.subtitle')}
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5 w-full max-w-4xl">
        {CHOICES.map((c) => {
          const Icon = c.icon;
          return (
            <button
              key={c.key}
              type="button"
              onClick={() => handlePick(c.key)}
              data-testid={`start-choice-${c.key}`}
              className={[
                'group relative flex flex-col items-start text-left',
                'rounded-2xl border bg-[hsl(var(--card))]',
                'px-6 py-7 md:px-7 md:py-8',
                'transition-all duration-300 ease-out',
                'hover:-translate-y-1 hover:shadow-[0_12px_40px_-12px_hsl(var(--primary)/0.45)]',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary))]',
                c.primary
                  ? 'border-[hsl(var(--primary)/0.45)] bg-[hsl(var(--primary)/0.06)]'
                  : 'border-[hsl(var(--border))] hover:border-[hsl(var(--primary)/0.45)]',
              ].join(' ')}
            >
              {c.primary && (
                <span
                  className="absolute top-4 right-4 text-[10px] uppercase tracking-[0.16em] font-semibold text-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.12)] rounded-full px-2 py-0.5"
                  data-testid={`start-choice-${c.key}-recommended`}
                >
                  {t('welcome.start.recommended_badge')}
                </span>
              )}
              <div
                className={[
                  'size-11 rounded-xl flex items-center justify-center mb-5',
                  c.primary
                    ? 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]'
                    : 'bg-[hsl(var(--muted)/0.5)] text-[hsl(var(--foreground))] group-hover:bg-[hsl(var(--primary)/0.12)] group-hover:text-[hsl(var(--primary))]',
                  'transition-colors duration-300 ease-out',
                ].join(' ')}
              >
                <Icon size={22} />
              </div>
              <h3 className="text-lg font-semibold tracking-tight mb-2">
                {t(`welcome.start.choice_${c.key}_title`)}
              </h3>
              <p className="text-sm text-muted-foreground leading-relaxed mb-5">
                {t(`welcome.start.choice_${c.key}_desc`)}
              </p>
              <span
                className={[
                  'inline-flex items-center gap-1.5 text-sm font-medium mt-auto',
                  c.primary
                    ? 'text-[hsl(var(--primary))]'
                    : 'text-foreground group-hover:text-[hsl(var(--primary))] transition-colors duration-300',
                ].join(' ')}
              >
                {t('welcome.start.continue_cta')}
                <ArrowRight
                  size={14}
                  className="transition-transform duration-300 group-hover:translate-x-0.5"
                />
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
