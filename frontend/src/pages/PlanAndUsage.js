import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Sparkles,
  CreditCard,
  Zap,
  Receipt,
  UserCircle,
  ArrowUpRight,
  LogOut,
  ShieldCheck,
  Mail,
  Building2,
  ChevronRight,
  Database,
  RefreshCw,
  ExternalLink,
  Loader2,
  Key,
} from 'lucide-react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { supabase } from '../lib/supabaseClient';
import PlanSelectorDialog from '../components/PlanSelectorDialog';
import {
  PLAN_LIMITS,
  getPlanByKey,
  deriveSubscriptionState,
  openCustomerPortal,
  getOpenAIUsageLimit,
  getCreditsState,
  formatUsd,
} from '../lib/billing';

/**
 * PlanAndUsage — Live account & billing center backed 100% by Supabase.
 *
 * Data flow
 * ---------
 *   Auth user     → supabase.auth.getUser() (via AuthContext)
 *   Plan          → public.profiles (id = auth.uid): plan, plan_updated_at,
 *                    stripe_customer_id, stripe_subscription_id,
 *                    subscription_status, current_period_end
 *   Monthly usage → public.ai_usage rows for current month, summed by type
 *
 * Billing actions
 * ---------------
 *   • "Actualizar plan"  → open PlanSelectorDialog → startCheckout() →
 *     Supabase Edge Function `create-checkout-session` → Stripe Checkout.
 *   • "Ver mi plan" / "Gestionar suscripción" → openCustomerPortal() →
 *     Supabase Edge Function `create-portal-session` → Stripe
 *     Customer Portal. (Was calling `create-customer-portal-session`,
 *     which 404'd — that name never existed on the live project.)
 *
 * After returning from Checkout we honour the ?checkout=success query
 * param to show a toast + re-fetch the profile so the new plan shows up
 * without a full page reload.
 */
const MODULE_META = {
  ai_requests: { key: 'ai_requests', testid: 'ai_requests' },
  agent_runs: { key: 'agent_runs', testid: 'agent_runs' },
  automations: { key: 'automations', testid: 'automations' },
  inbox_ai: { key: 'inbox_ai', testid: 'inbox_ai' },
  crm: { key: 'crm', testid: 'crm' },
  content: { key: 'content', testid: 'content' },
};

function currentMonthKey() {
  const d = new Date();
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function prettyType(type) {
  if (!type) return 'other';
  return type.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function PlanAndUsage() {
  const { t } = useLanguage();
  const { user, workspaces, logout } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const [profile, setProfile] = useState(null);
  const [usageRows, setUsageRows] = useState([]);
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [loadingUsage, setLoadingUsage] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);
  const [portalLoading, setPortalLoading] = useState(false);
  const [selectorOpen, setSelectorOpen] = useState(false);

  const loading = loadingProfile || loadingUsage;
  const currentWs = workspaces?.find((w) => w.is_current);

  const fetchProfile = useCallback(async () => {
    if (!user?.user_id) return;
    setLoadingProfile(true);
    // Use select('*') so we don't crash if optional columns
    // (subscription_status, current_period_end, etc.) haven't been added
    // to the profiles table yet. Supabase returns whatever exists.
    const { data, error } = await supabase
      .from('profiles')
      .select('*')
      .eq('id', user.user_id)
      .maybeSingle();
    if (error && error.code !== 'PGRST116') setErrorMsg(error.message);
    setProfile(data || null);
    setLoadingProfile(false);
  }, [user?.user_id]);

  const fetchUsage = useCallback(async () => {
    if (!user?.user_id) return;
    setLoadingUsage(true);
    const { data, error } = await supabase
      .from('ai_usage')
      .select('type, count, month')
      .eq('user_id', user.user_id)
      .eq('month', currentMonthKey());
    if (error) {
      setErrorMsg(error.message);
      setUsageRows([]);
    } else {
      setUsageRows(Array.isArray(data) ? data : []);
    }
    setLoadingUsage(false);
  }, [user?.user_id]);

  useEffect(() => {
    if (!user?.user_id) return;
    fetchProfile();
    fetchUsage();
  }, [user?.user_id, fetchProfile, fetchUsage]);

  // Handle Stripe checkout return via query params.
  // Intentionally fires only on first mount \u2014 we read latest closures via
  // refs implicitly through fetchProfile being stable (useCallback above).
  useEffect(() => {
    const status = searchParams.get('checkout');
    if (!status) return;
    if (status === 'success') {
      toast.success(t('billing.checkout_success_title'), {
        description: t('billing.checkout_success_desc'),
      });
      // Stripe webhook may take a few seconds to propagate \u2014 retry a few
      // times so the user sees the updated plan as soon as possible.
      let attempts = 0;
      const interval = setInterval(async () => {
        attempts += 1;
        await fetchProfile();
        if (attempts >= 5) clearInterval(interval);
      }, 2500);
    } else if (status === 'cancelled') {
      toast.info(t('billing.checkout_cancelled_title'), {
        description: t('billing.checkout_cancelled_desc'),
      });
    }
    // Clear query params so reloads don't re-trigger the toast.
    const next = new URLSearchParams(searchParams);
    next.delete('checkout');
    next.delete('plan');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, fetchProfile, t]);

  const usage = useMemo(() => {
    const byType = new Map();
    for (const row of usageRows) {
      const key = row.type || 'other';
      byType.set(key, (byType.get(key) || 0) + (row.count || 0));
    }
    const total = Array.from(byType.values()).reduce((a, b) => a + b, 0);
    // Resolve the limit through the centralized helper so test users,
    // coupon discounts and inactive subscriptions are reflected here.
    const limitInfo = getOpenAIUsageLimit({ email: user?.email, profile });
    const limit = limitInfo.limit || PLAN_LIMITS.essential;
    const percent = limit > 0 ? Math.min(100, Math.round((total / limit) * 1000) / 10) : 0;
    const breakdown = Array.from(byType.entries())
      .map(([type, calls]) => ({
        module: MODULE_META[type]?.testid || type,
        type,
        label: prettyType(type),
        calls,
        share: total > 0 ? Math.round((calls / total) * 100) : 0,
      }))
      .sort((a, b) => b.calls - a.calls);
    return {
      total,
      limit,
      percent,
      overage: Math.max(0, total - limit),
      breakdown,
      limitReason: limitInfo.reason,
      blocked: limitInfo.blocked,
    };
  }, [usageRows, profile, user?.email]);

  const planKey = (profile?.plan || '').toLowerCase();
  const planDef = getPlanByKey(planKey);
  const planName = planDef?.name || (profile?.plan ? profile.plan.charAt(0).toUpperCase() + profile.plan.slice(1) : null);
  const state = deriveSubscriptionState(profile);

  const paymentMethod = profile?.stripe_subscription_id
    ? 'Stripe'
    : profile?.paypal_subscription_id
      ? 'PayPal'
      : null;

  const handleOpenPortal = async () => {
    setPortalLoading(true);
    try {
      await openCustomerPortal();
    } catch (e) {
      toast.error(t('billing.portal_failed'), { description: e?.message });
      setPortalLoading(false);
    }
  };

  const handleUpgradeClick = () => setSelectorOpen(true);

  const handleLogout = async () => {
    try {
      await logout();
      toast.success(t('auth.signed_out_title'));
      window.location.href = '/login';
    } catch (_) {
      toast.error(t('auth.login_failed_title'));
    }
  };

  const formatDate = (iso) => {
    if (!iso) return '—';
    try {
      return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (_) {
      return iso;
    }
  };

  const statusBadge = () => {
    const map = {
      active: {
        label: t('plan_usage.status_active'),
        cls: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.3)]',
      },
      trial: {
        label: t('plan_usage.status_trial'),
        cls: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.3)]',
      },
      past_due: {
        label: t('plan_usage.status_expired'),
        cls: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.3)]',
      },
      none: {
        label: '—',
        cls: 'bg-[hsl(var(--surface-2))] text-muted-foreground border-[hsl(var(--border))]',
      },
    };
    const m = map[state] || map.none;
    return (
      <Badge data-testid="plan-status-badge" className={`text-[10px] font-medium tracking-wide uppercase ${m.cls} border`}>
        {m.label}
      </Badge>
    );
  };

  // CTA configuration: depending on subscription state.
  const primaryCta = state === 'active'
    ? { label: t('billing.manage_subscription'), onClick: handleOpenPortal, testid: 'plan-manage-btn', icon: ExternalLink }
    : { label: t('billing.upgrade_plan'), onClick: handleUpgradeClick, testid: 'plan-upgrade-btn', icon: ArrowUpRight };

  const secondaryCta = state === 'active'
    ? { label: t('billing.change_plan'), onClick: handleUpgradeClick, testid: 'plan-change-btn' }
    : { label: t('plan_usage.view_plan'), onClick: handleOpenPortal, testid: 'plan-view-btn' };

  return (
    <div data-testid="plan-usage-page" className="max-w-5xl mx-auto px-4 md:px-6 py-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('plan_usage.page_title')}</h1>
        <p className="text-sm text-muted-foreground">{t('plan_usage.page_subtitle')}</p>
      </header>

      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <Database size={12} className="text-[hsl(var(--primary))]" />
        <span data-testid="usage-source-badge">{t('plan_usage.source_supabase')}</span>
      </div>

      {/* 1. Plan actual */}
      <Card data-testid="plan-card" className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] relative overflow-hidden">
        <div className="absolute inset-0 pointer-events-none bg-gradient-to-br from-[hsl(var(--primary)/0.06)] via-transparent to-transparent" />
        <CardHeader className="relative flex flex-row items-start justify-between gap-4 pb-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] flex items-center justify-center">
              <CreditCard size={18} />
            </div>
            <div>
              <CardTitle className="text-sm font-medium text-muted-foreground">{t('plan_usage.current_plan')}</CardTitle>
              <div className="flex items-baseline gap-3 mt-1">
                <span data-testid="plan-name" className="text-xl font-semibold text-foreground">
                  {loadingProfile ? (
                    <Skeleton className="h-6 w-24 inline-block align-middle" />
                  ) : (
                    planName || t('plan_usage.plan_unavailable')
                  )}
                </span>
                {!loadingProfile && statusBadge()}
              </div>
              {planDef && (
                <p className="text-xs text-muted-foreground mt-1">{planDef.tagline}</p>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent className="relative flex flex-col md:flex-row md:items-center gap-4 md:gap-6 justify-between">
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">
              {t('plan_usage.renews_on')}{' '}
              <span data-testid="plan-renewal-date" className="text-foreground font-medium">
                {loadingProfile ? '—' : formatDate(profile?.current_period_end || profile?.plan_updated_at)}
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground max-w-md">
              {t('billing.microcopy')}
            </p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              data-testid={secondaryCta.testid}
              variant="outline"
              size="sm"
              className="border-[hsl(var(--border))]"
              onClick={secondaryCta.onClick}
              disabled={portalLoading}
            >
              {portalLoading && secondaryCta.testid === 'plan-view-btn' ? (
                <Loader2 size={14} className="animate-spin mr-1.5" />
              ) : null}
              {secondaryCta.label}
            </Button>
            <Button
              data-testid={primaryCta.testid}
              size="sm"
              onClick={primaryCta.onClick}
              disabled={portalLoading && primaryCta.testid === 'plan-manage-btn'}
              className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
            >
              {portalLoading && primaryCta.testid === 'plan-manage-btn' ? (
                <Loader2 size={14} className="animate-spin mr-1.5" />
              ) : (
                <>
                  {primaryCta.label}
                  <primaryCta.icon size={14} className="ml-1.5" />
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 2. Cr\u00e9ditos IA (USD-based) */}
      {(() => {
        const credits = getCreditsState({ email: user?.email, profile });
        return (
          <Card data-testid="credits-card" className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]">
            <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] flex items-center justify-center">
                  <Sparkles size={18} />
                </div>
                <div>
                  <CardTitle className="text-sm font-medium text-muted-foreground">{t('plan_usage.ai_credits')}</CardTitle>
                  <p className="text-[11px] text-muted-foreground mt-0.5">{t('plan_usage.ai_credits_subtitle')}</p>
                </div>
              </div>
              <Badge
                data-testid="credits-source-badge"
                className={`text-[10px] uppercase tracking-wide font-medium border ${
                  credits.source === 'quantro'
                    ? 'bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))] border-[hsl(var(--primary)/0.3)]'
                    : credits.source === 'user_api'
                      ? 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.3)]'
                      : 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.3)]'
                }`}
              >
                {credits.source === 'quantro' && t('plan_usage.credits_source_quantro')}
                {credits.source === 'user_api' && t('plan_usage.credits_source_user')}
                {credits.source === 'blocked' && t('plan_usage.credits_source_blocked')}
              </Badge>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <div className="text-2xl font-semibold text-foreground tabular-nums">
                    <span data-testid="credits-remaining">{formatUsd(credits.remaining)}</span>
                    <span className="text-sm text-muted-foreground font-normal">
                      {' '}/ <span data-testid="credits-total">{formatUsd(credits.total)}</span> {t('plan_usage.credits_unit')}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {t('plan_usage.credits_used', { used: formatUsd(credits.used) })}
                  </p>
                </div>
                <div className="text-right">
                  <div data-testid="credits-percent" className="text-sm font-semibold text-foreground">
                    {credits.percent}%
                  </div>
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
                    {t('plan_usage.credits_consumed')}
                  </div>
                </div>
              </div>
              <Progress data-testid="credits-progress" value={credits.percent} className="h-2 bg-[hsl(var(--surface-2))]" />

              {credits.source === 'quantro' && credits.remaining > 0 && credits.remaining < credits.total * 0.2 && (
                <div data-testid="credits-low-warning" className="text-xs text-[hsl(var(--warning))] bg-[hsl(var(--warning)/0.08)] border border-[hsl(var(--warning)/0.2)] rounded-md px-3 py-2">
                  {t('plan_usage.credits_low_warning')}
                </div>
              )}
              {credits.source === 'user_api' && (
                <div data-testid="credits-fallback" className="flex items-center gap-2 text-xs text-[hsl(var(--success))] bg-[hsl(var(--success)/0.08)] border border-[hsl(var(--success)/0.2)] rounded-md px-3 py-2">
                  <Key size={12} />
                  <span>{t('plan_usage.credits_fallback_user_key')}</span>
                </div>
              )}
              {credits.source === 'blocked' && (
                <div data-testid="credits-blocked" className="space-y-2 text-xs text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2">
                  <p>{t('plan_usage.credits_blocked_message')}</p>
                  <div className="flex gap-2">
                    <Button
                      data-testid="credits-add-key-btn"
                      size="sm"
                      variant="outline"
                      onClick={() => navigate('/settings')}
                      className="border-[hsl(var(--border))] h-8 text-xs"
                    >
                      <Key size={12} className="mr-1.5" />
                      {t('plan_usage.add_own_api_key')}
                    </Button>
                    <Button
                      data-testid="credits-upgrade-btn"
                      size="sm"
                      onClick={handleUpgradeClick}
                      className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))] h-8 text-xs"
                    >
                      {t('billing.upgrade_plan')}
                    </Button>
                  </div>
                </div>
              )}

              <div className="text-[10px] text-muted-foreground pt-1 border-t border-[hsl(var(--border))]">
                {t('plan_usage.credits_pricing_hint')}
              </div>
            </CardContent>
          </Card>
        );
      })()}

      {/* 3. Uso de API (legacy call counts \u2014 still useful for visibility) */}
      <Card data-testid="usage-card" className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]">
        <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning))] flex items-center justify-center">
              <Zap size={18} />
            </div>
            <CardTitle className="text-sm font-medium text-muted-foreground">{t('plan_usage.api_usage')}</CardTitle>
          </div>
          <button
            type="button"
            data-testid="usage-refresh-btn"
            onClick={() => { fetchProfile(); fetchUsage(); }}
            className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 transition-colors"
          >
            <RefreshCw size={12} />
            {t('plan_usage.refresh')}
          </button>
        </CardHeader>
        <CardContent className="space-y-5">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-64" />
              <Skeleton className="h-3 w-full" />
            </div>
          ) : (
            <>
              <div className="flex items-end justify-between gap-4">
                <div>
                  <div className="text-2xl font-semibold text-foreground tabular-nums">
                    <span data-testid="usage-total">{usage.total.toLocaleString()}</span>
                    <span className="text-sm text-muted-foreground font-normal">
                      {' '}/ <span data-testid="usage-limit">{usage.limit.toLocaleString()}</span> {t('plan_usage.calls')}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5">{t('plan_usage.api_calls_this_month')}</p>
                </div>
                <div className="text-right">
                  <div data-testid="usage-percent" className="text-sm font-semibold text-foreground">{usage.percent}%</div>
                  {usage.overage > 0 && (
                    <div data-testid="usage-overage" className="text-[10px] text-[hsl(var(--destructive))] font-medium uppercase tracking-wider">
                      +{usage.overage.toLocaleString()} {t('plan_usage.overage')}
                    </div>
                  )}
                </div>
              </div>

              <Progress data-testid="usage-progress" value={usage.percent} className="h-2 bg-[hsl(var(--surface-2))]" />

              {/* Limit reason hints (test user, coupon discount, blocked) */}
              {usage.blocked && (
                <div data-testid="usage-blocked-hint" className="text-xs text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2">
                  {t('plan_usage.limit_blocked')}
                </div>
              )}
              {!usage.blocked && usage.limitReason === 'coupon_applied' && (
                <div data-testid="usage-coupon-hint" className="text-xs text-[hsl(var(--warning))] bg-[hsl(var(--warning)/0.08)] border border-[hsl(var(--warning)/0.2)] rounded-md px-3 py-2">
                  {t('plan_usage.limit_coupon')}
                </div>
              )}
              {!usage.blocked && usage.limitReason === 'test_user' && (
                <div data-testid="usage-testuser-hint" className="text-[11px] text-muted-foreground italic">
                  {t('plan_usage.limit_test_user')}
                </div>
              )}

              <div className="pt-3 border-t border-[hsl(var(--border))]">
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3 font-medium">
                  {t('plan_usage.breakdown_title')}
                </div>
                <div className="space-y-3" data-testid="usage-breakdown">
                  {usage.breakdown.length === 0 ? (
                    <div className="text-xs text-muted-foreground py-2">{t('plan_usage.no_usage_yet')}</div>
                  ) : (
                    usage.breakdown.map((row) => (
                      <div key={row.type} className="flex items-center gap-3" data-testid={`usage-row-${row.module}`}>
                        <div className="flex-1">
                          <div className="flex items-baseline justify-between">
                            <span className="text-sm text-foreground">{row.label}</span>
                            <span className="text-xs text-muted-foreground tabular-nums">
                              {row.calls.toLocaleString()} <span className="opacity-60">({row.share}%)</span>
                            </span>
                          </div>
                          <div className="mt-1 h-1.5 bg-[hsl(var(--surface-2))] rounded-full overflow-hidden">
                            <div className="h-full bg-[hsl(var(--primary))] rounded-full transition-all duration-300" style={{ width: `${row.share}%` }} />
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </>
          )}
          {errorMsg && (
            <div data-testid="usage-error" className="text-xs text-[hsl(var(--destructive))] pt-2">{errorMsg}</div>
          )}
        </CardContent>
      </Card>

      {/* 3. Facturación */}
      <Card data-testid="billing-card" className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]">
        <CardHeader className="flex flex-row items-center gap-3 pb-3">
          <div className="w-9 h-9 rounded-lg bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))] flex items-center justify-center">
            <Receipt size={18} />
          </div>
          <CardTitle className="text-sm font-medium text-muted-foreground">{t('plan_usage.billing')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="space-y-1.5 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">{t('plan_usage.payment_method')}:</span>
              <span data-testid="billing-method" className="text-foreground font-medium">
                {loadingProfile ? '—' : (paymentMethod || t('plan_usage.no_payment_method'))}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">{t('plan_usage.next_billing')}:</span>
              <span data-testid="billing-next-date" className="text-foreground font-medium">
                {loadingProfile ? '—' : formatDate(profile?.current_period_end || profile?.plan_updated_at)}
              </span>
            </div>
          </div>
          <Button
            data-testid="billing-manage-btn"
            variant="outline"
            className="border-[hsl(var(--border))]"
            onClick={handleOpenPortal}
            disabled={portalLoading}
          >
            {portalLoading ? (
              <Loader2 size={14} className="animate-spin mr-1.5" />
            ) : null}
            {t('plan_usage.manage_payments')}
            <ChevronRight size={14} className="ml-1" />
          </Button>
        </CardContent>
      </Card>

      {/* 4. Cuenta */}
      <Card data-testid="account-card" className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]">
        <CardHeader className="flex flex-row items-center gap-3 pb-3">
          <div className="w-9 h-9 rounded-lg bg-[hsl(var(--surface-2))] text-foreground flex items-center justify-center">
            <UserCircle size={18} />
          </div>
          <CardTitle className="text-sm font-medium text-muted-foreground">{t('plan_usage.account')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-full bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] flex items-center justify-center font-semibold overflow-hidden">
              {user?.picture ? (
                <img src={user.picture} alt={user.name} className="w-full h-full object-cover" />
              ) : (
                (user?.name || user?.email || '?').slice(0, 1).toUpperCase()
              )}
            </div>
            <div className="flex-1 space-y-1.5">
              <div className="flex items-center gap-2 text-sm">
                <UserCircle size={14} className="text-muted-foreground" />
                <span className="text-muted-foreground">{t('plan_usage.user')}:</span>
                <span data-testid="account-name" className="text-foreground font-medium">{user?.name || '—'}</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Mail size={14} className="text-muted-foreground" />
                <span data-testid="account-email" className="text-foreground">{user?.email || '—'}</span>
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Building2 size={14} className="text-muted-foreground" />
                <span className="text-muted-foreground">{t('plan_usage.workspace')}:</span>
                <span data-testid="account-workspace" className="text-foreground font-medium">{currentWs?.name || t('auth.my_workspace')}</span>
              </div>
            </div>
          </div>

          <div className="pt-3 border-t border-[hsl(var(--border))] flex flex-wrap items-center gap-2">
            <Button
              data-testid="account-switch-btn"
              variant="outline"
              size="sm"
              className="border-[hsl(var(--border))]"
              onClick={() => navigate('/settings')}
            >
              {t('plan_usage.switch_account')}
            </Button>
            <Button
              data-testid="account-signout-btn"
              variant="ghost"
              size="sm"
              onClick={handleLogout}
              className="text-[hsl(var(--destructive))] hover:text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.08)]"
            >
              <LogOut size={14} className="mr-1.5" />
              {t('plan_usage.signout')}
            </Button>
          </div>

          <div className="flex items-center gap-2 pt-1 text-[11px] text-muted-foreground">
            <ShieldCheck size={12} className="text-[hsl(var(--success))]" />
            <span>{t('auth.secured_by')}</span>
          </div>
        </CardContent>
      </Card>

      {/* Plan selector dialog (upgrade / change plan) */}
      <PlanSelectorDialog
        open={selectorOpen}
        onOpenChange={setSelectorOpen}
        currentPlanKey={planKey}
      />
    </div>
  );
}
