import React, { useMemo, useState } from 'react';
import { X, Check, Loader2, Sparkles, Star, Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { useLanguage } from '../context/LanguageContext';
import { PLANS, startCheckout } from '../lib/billing';

/**
 * PlanSelectorDialog — the modal that surfaces when the user clicks
 * "Actualizar plan" (or "Change plan" for active subscribers). Matches
 * the visual language of the landing's pricing page (three columns,
 * highlighted "Más popular", gradient accents) but lives inside the
 * dark product shell.
 *
 * Props:
 *   open:        dialog visibility
 *   onOpenChange: dialog close handler
 *   currentPlanKey: (optional) highlight + label for the user's active plan
 */
export default function PlanSelectorDialog({ open, onOpenChange, currentPlanKey }) {
  const { t } = useLanguage();
  const [period, setPeriod] = useState('monthly'); // 'monthly' | 'annual'
  const [selecting, setSelecting] = useState(null); // plan key currently being processed
  const [error, setError] = useState('');

  const activeKey = (currentPlanKey || '').toLowerCase();

  const plans = useMemo(() => {
    return PLANS.map((p) => {
      const price = period === 'annual' ? p.priceAnnual : p.priceMonthly;
      return { ...p, displayPrice: price };
    });
  }, [period]);

  const handleSelect = async (plan) => {
    setError('');
    setSelecting(plan.key);
    // Log the exact request payload so the user can paste it for debugging.
    // eslint-disable-next-line no-console
    console.log('[billing] selected', {
      plan: plan.key,
      billingCycle: period,
      price_id: plan.priceIds[period],
    });
    try {
      await startCheckout({
        priceId: plan.priceIds[period],
        planKey: plan.key,
        period,
      });
      // Browser is redirected before we get here; no-op.
    } catch (e) {
      const msg = e?.message || t('billing.checkout_failed');
      setError(msg);
      setSelecting(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="plan-selector-dialog"
        className="max-w-5xl bg-[hsl(var(--background))] border-[hsl(var(--border))] p-0 overflow-hidden"
      >
        <div className="relative px-6 md:px-10 pt-8 pb-6 bg-gradient-to-br from-[hsl(var(--primary)/0.08)] via-transparent to-transparent">
          <DialogHeader className="space-y-2">
            <DialogTitle className="text-2xl md:text-3xl font-semibold tracking-tight">
              {t('billing.select_plan_title')}
            </DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground">
              {t('billing.select_plan_subtitle')}
            </DialogDescription>
          </DialogHeader>

          {/* Billing period toggle */}
          <div className="mt-6 inline-flex items-center rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--surface-1))] p-1">
            <button
              type="button"
              data-testid="billing-period-monthly"
              onClick={() => setPeriod('monthly')}
              className={`px-4 py-1.5 text-xs font-medium rounded-full transition-colors ${
                period === 'monthly'
                  ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {t('billing.period_monthly')}
            </button>
            <button
              type="button"
              data-testid="billing-period-annual"
              onClick={() => setPeriod('annual')}
              className={`px-4 py-1.5 text-xs font-medium rounded-full transition-colors inline-flex items-center gap-1.5 ${
                period === 'annual'
                  ? 'bg-[hsl(var(--foreground))] text-[hsl(var(--background))]'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {t('billing.period_annual')}
              <span className="text-[10px] text-[hsl(var(--success))] font-semibold">
                {period === 'annual' ? t('billing.annual_save') : '−20%'}
              </span>
            </button>
          </div>
        </div>

        <div className="px-6 md:px-10 pb-8 pt-2">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {plans.map((p) => {
              const isCurrent = activeKey === p.key;
              const isProcessing = selecting === p.key;
              return (
                <div
                  key={p.key}
                  data-testid={`plan-card-${p.key}`}
                  className={`relative rounded-2xl border p-5 flex flex-col gap-4 transition-all ${
                    p.popular
                      ? 'border-[hsl(var(--primary)/0.45)] bg-[hsl(var(--primary)/0.05)] shadow-[0_0_0_1px_hsl(var(--primary)/0.2)]'
                      : 'border-[hsl(var(--border))] bg-[hsl(var(--surface-1))]'
                  } ${isCurrent ? 'ring-1 ring-[hsl(var(--success)/0.5)]' : ''}`}
                >
                  {p.popular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-[10px] font-semibold uppercase tracking-wider">
                      <Star size={10} className="fill-current" />
                      {t('billing.most_popular')}
                    </div>
                  )}
                  {isCurrent && (
                    <div className="absolute -top-3 right-4 inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-[hsl(var(--success))] text-[hsl(var(--background))] text-[10px] font-semibold uppercase tracking-wider">
                      <Check size={10} />
                      {t('billing.current_plan_badge')}
                    </div>
                  )}

                  <div>
                    <div className="flex items-baseline gap-2">
                      <h3 className="text-lg font-semibold text-foreground">{p.name}</h3>
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">{p.tagline}</p>
                  </div>

                  <div className="flex items-baseline gap-1">
                    <span className="text-[11px] text-muted-foreground">$</span>
                    <span className="text-4xl font-semibold tabular-nums tracking-tight text-foreground">
                      {p.displayPrice}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      USD / {t('billing.per_month_short')}
                    </span>
                  </div>
                  {period === 'annual' && (
                    <div className="text-[11px] text-muted-foreground -mt-2">
                      {t('billing.billed_annually', { total: p.annualTotal })}
                    </div>
                  )}

                  <ul className="space-y-2 flex-1">
                    {p.features.map((f, idx) => (
                      <li key={idx} className="flex items-start gap-2 text-xs text-muted-foreground">
                        <Check size={13} className={p.popular ? 'text-[hsl(var(--primary))] mt-0.5 shrink-0' : 'text-[hsl(var(--success))] mt-0.5 shrink-0'} />
                        <span className="leading-relaxed">{f}</span>
                      </li>
                    ))}
                  </ul>

                  <Button
                    data-testid={`plan-select-btn-${p.key}`}
                    onClick={() => handleSelect(p)}
                    disabled={isProcessing || isCurrent}
                    className={`w-full h-10 font-medium ${
                      p.popular
                        ? 'bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]'
                        : 'bg-[hsl(var(--foreground))] hover:bg-[hsl(var(--foreground)/0.9)] text-[hsl(var(--background))]'
                    } ${isCurrent ? 'opacity-60 cursor-not-allowed' : ''}`}
                  >
                    {isProcessing ? (
                      <span className="flex items-center gap-2">
                        <Loader2 size={14} className="animate-spin" />
                        {t('billing.redirecting')}
                      </span>
                    ) : isCurrent ? (
                      t('billing.current_plan_cta')
                    ) : (
                      <span className="flex items-center gap-2">
                        <Zap size={14} />
                        {t('billing.select_plan_cta')}
                      </span>
                    )}
                  </Button>
                </div>
              );
            })}
          </div>

          {error && (
            <div data-testid="plan-selector-error" className="mt-4 text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2 space-y-1">
              <div className="flex items-start gap-2">
                <span className="font-medium shrink-0">Error:</span>
                <span className="font-mono text-xs break-all">{error}</span>
              </div>
              <div className="text-[10px] text-muted-foreground pt-1 border-t border-[hsl(var(--destructive)/0.15)]">
                {t('billing.error_hint')}
              </div>
            </div>
          )}

          <div className="mt-6 flex items-center gap-2 text-[11px] text-muted-foreground">
            <Sparkles size={12} className="text-[hsl(var(--primary))]" />
            <span>{t('billing.secured_by_stripe')}</span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
