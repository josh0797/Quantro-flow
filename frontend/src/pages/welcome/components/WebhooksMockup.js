import React from 'react';
import { Webhook, ArrowRight, CheckCircle2 } from 'lucide-react';
import { useLanguage } from '../../../context/LanguageContext';

/**
 * WebhooksMockup — a left-to-right reactive flow: external event →
 * Quantro classification → automated action. Each node fades in in
 * sequence to suggest "the system is reacting in real time".
 */
const NODES = [
  { key: 'event',  icon: Webhook,        delay: 0   },
  { key: 'brain',  icon: null,           delay: 220, isQuantro: true },
  { key: 'action', icon: CheckCircle2,   delay: 440 },
];

export default function WebhooksMockup() {
  const { t } = useLanguage();
  return (
    <div className="text-left" data-testid="webhooks-mockup">
      <div className="flex items-center gap-2 mb-3 px-1">
        <Webhook size={14} className="text-[hsl(var(--primary))]" />
        <span className="text-xs uppercase tracking-[0.16em] font-semibold text-muted-foreground">
          {t('welcome.automations.preview_header')}
        </span>
        <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-emerald-400">
          <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
          {t('welcome.automations.live_indicator')}
        </span>
      </div>
      <div className="flex items-stretch gap-2">
        {NODES.map((n, i) => (
          <React.Fragment key={n.key}>
            <div
              className={[
                'flex-1 rounded-xl border px-3 py-3 min-h-[88px]',
                'transition-all duration-500 ease-out animate-in fade-in slide-in-from-bottom-1',
                n.isQuantro
                  ? 'border-[hsl(var(--primary)/0.40)] bg-[hsl(var(--primary)/0.06)]'
                  : 'border-[hsl(var(--border))] bg-[hsl(var(--background)/0.6)]',
              ].join(' ')}
              style={{ animationDelay: `${n.delay}ms`, animationFillMode: 'both' }}
              data-testid={`webhooks-node-${n.key}`}
            >
              <div className="flex items-center gap-2 mb-1.5">
                {n.isQuantro ? (
                  <span className="text-[10px] font-bold uppercase tracking-[0.16em] text-[hsl(var(--primary))]">Q</span>
                ) : (
                  <n.icon size={13} className="text-[hsl(var(--primary))]" />
                )}
                <span className="text-[10px] uppercase tracking-[0.14em] font-semibold text-muted-foreground">
                  {t(`welcome.automations.node_${n.key}_label`)}
                </span>
              </div>
              <p className="text-[12px] font-semibold tracking-tight">
                {t(`welcome.automations.node_${n.key}_title`)}
              </p>
              <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                {t(`welcome.automations.node_${n.key}_detail`)}
              </p>
            </div>
            {i < NODES.length - 1 && (
              <ArrowRight
                size={14}
                className="self-center text-muted-foreground shrink-0"
                aria-hidden="true"
              />
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}
