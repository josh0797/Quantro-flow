import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
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

/**
 * PlanAndUsage — Live account center backed 100% by Supabase.
 *
 * Data sources (single source of truth = Supabase):
 *   • Auth user     → supabase.auth.getUser() (via AuthContext)
 *   • Plan          → public.profiles (id = auth.uid) columns:
 *                        - plan, plan_updated_at,
 *                          stripe_subscription_id, paypal_subscription_id
 *   • Monthly usage → public.ai_usage rows where user_id = auth.uid AND
 *                        month = YYYY-MM (current month), aggregated by type.
 *
 * MongoDB is intentionally NOT queried here — the landing and Quantro Flow
 * share the same Supabase project, so this page reflects whatever the
 * rest of the Quantro ecosystem already knows about the user.
 */
const PLAN_LIMITS = {
  starter: 1000,
  pro: 10000,
  business: 50000,
  enterprise: 250000,
};

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
  return type
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function PlanAndUsage() {
  const { t } = useLanguage();
  const { user, workspaces, logout } = useAuth();
  const navigate = useNavigate();

  const [profile, setProfile] = useState(null);
  const [usageRows, setUsageRows] = useState([]);
  const [loadingProfile, setLoadingProfile] = useState(true);
  const [loadingUsage, setLoadingUsage] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);

  const loading = loadingProfile || loadingUsage;
  const currentWs = workspaces?.find((w) => w.is_current);

  // Pull profile + monthly usage from Supabase directly.
  useEffect(() => {
    if (!user?.user_id) return;
    let cancelled = false;

    (async () => {
      setLoadingProfile(true);
      const { data, error } = await supabase
        .from('profiles')
        .select('id, plan, plan_updated_at, stripe_subscription_id, paypal_subscription_id')
        .eq('id', user.user_id)
        .maybeSingle();
      if (cancelled) return;
      if (error && error.code !== 'PGRST116') {
        // PGRST116 = no rows; treat gracefully.
        setErrorMsg(error.message);
      }
      setProfile(data || null);
      setLoadingProfile(false);
    })();

    (async () => {
      setLoadingUsage(true);
      const { data, error } = await supabase
        .from('ai_usage')
        .select('type, count, month')
        .eq('user_id', user.user_id)
        .eq('month', currentMonthKey());
      if (cancelled) return;
      if (error) {
        setErrorMsg(error.message);
        setUsageRows([]);
      } else {
        setUsageRows(Array.isArray(data) ? data : []);
      }
      setLoadingUsage(false);
    })();

    return () => { cancelled = true; };
  }, [user?.user_id]);

  // Aggregate usage rows by `type`.
  const usage = useMemo(() => {
    const byType = new Map();
    for (const row of usageRows) {
      const key = row.type || 'other';
      byType.set(key, (byType.get(key) || 0) + (row.count || 0));
    }
    const total = Array.from(byType.values()).reduce((a, b) => a + b, 0);
    const planKey = (profile?.plan || 'starter').toLowerCase();
    const limit = PLAN_LIMITS[planKey] || PLAN_LIMITS.starter;
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
      byType: Object.fromEntries(byType),
      breakdown,
    };
  }, [usageRows, profile]);

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

  const planName = profile?.plan
    ? profile.plan.charAt(0).toUpperCase() + profile.plan.slice(1)
    : null;

  const hasSubscription = !!(profile?.stripe_subscription_id || profile?.paypal_subscription_id);

  const planStatus = hasSubscription ? 'active' : (profile?.plan ? 'trial' : 'unavailable');

  const statusBadge = () => {
    const map = {
      active: { label: t('plan_usage.status_active'), cls: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.3)]' },
      trial: { label: t('plan_usage.status_trial'), cls: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.3)]' },
      expired: { label: t('plan_usage.status_expired'), cls: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))] border-[hsl(var(--destructive)/0.3)]' },
      unavailable: { label: '—', cls: 'bg-[hsl(var(--surface-2))] text-muted-foreground border-[hsl(var(--border))]' },
    };
    const m = map[planStatus] || map.unavailable;
    return (
      <Badge data-testid="plan-status-badge" className={`text-[10px] font-medium tracking-wide uppercase ${m.cls} border`}>
        {m.label}
      </Badge>
    );
  };

  const paymentMethod = profile?.stripe_subscription_id
    ? 'Stripe'
    : profile?.paypal_subscription_id
      ? 'PayPal'
      : null;

  return (
    <div data-testid="plan-usage-page" className="max-w-5xl mx-auto px-4 md:px-6 py-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">{t('plan_usage.page_title')}</h1>
        <p className="text-sm text-muted-foreground">{t('plan_usage.page_subtitle')}</p>
      </header>

      {/* Supabase data source signal */}
      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
        <Database size={12} className="text-[hsl(var(--primary))]" />
        <span data-testid="usage-source-badge">
          {t('plan_usage.source_supabase') || 'Datos en vivo desde Supabase · ai_usage'}
        </span>
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
                    planName || (t('plan_usage.plan_unavailable') || 'Plan no disponible')
                  )}
                </span>
                {!loadingProfile && statusBadge()}
              </div>
            </div>
          </div>
        </CardHeader>
        <CardContent className="relative flex flex-col md:flex-row md:items-center gap-4 md:gap-6 justify-between">
          <div className="text-xs text-muted-foreground">
            {t('plan_usage.renews_on')}{' '}
            <span data-testid="plan-renewal-date" className="text-foreground font-medium">
              {loadingProfile ? '—' : formatDate(profile?.plan_updated_at)}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <Button data-testid="plan-view-btn" variant="outline" size="sm" className="border-[hsl(var(--border))]">
              {t('plan_usage.view_plan')}
            </Button>
            <Button
              data-testid="plan-upgrade-btn"
              size="sm"
              className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
            >
              {t('plan_usage.upgrade_plan')}
              <ArrowUpRight size={14} className="ml-1.5" />
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* 2. Uso de API */}
      <Card data-testid="usage-card" className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))]">
        <CardHeader className="flex flex-row items-center gap-3 pb-3">
          <div className="w-9 h-9 rounded-lg bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning))] flex items-center justify-center">
            <Zap size={18} />
          </div>
          <CardTitle className="text-sm font-medium text-muted-foreground">{t('plan_usage.api_usage')}</CardTitle>
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
                  <div data-testid="usage-percent" className="text-sm font-semibold text-foreground">
                    {usage.percent}%
                  </div>
                  {usage.overage > 0 && (
                    <div data-testid="usage-overage" className="text-[10px] text-[hsl(var(--destructive))] font-medium uppercase tracking-wider">
                      +{usage.overage.toLocaleString()} {t('plan_usage.overage')}
                    </div>
                  )}
                </div>
              </div>

              <Progress
                data-testid="usage-progress"
                value={usage.percent}
                className="h-2 bg-[hsl(var(--surface-2))]"
              />

              <div className="pt-3 border-t border-[hsl(var(--border))]">
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-3 font-medium">
                  {t('plan_usage.breakdown_title')}
                </div>
                <div className="space-y-3" data-testid="usage-breakdown">
                  {usage.breakdown.length === 0 ? (
                    <div className="text-xs text-muted-foreground py-2">
                      {t('plan_usage.no_usage_yet') || 'Aún no hay consumo este mes.'}
                    </div>
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
                            <div
                              className="h-full bg-[hsl(var(--primary))] rounded-full transition-all duration-300"
                              style={{ width: `${row.share}%` }}
                            />
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
            <div data-testid="usage-error" className="text-xs text-[hsl(var(--destructive))] pt-2">
              {errorMsg}
            </div>
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
                {loadingProfile ? '—' : formatDate(profile?.plan_updated_at)}
              </span>
            </div>
          </div>
          <Button
            data-testid="billing-manage-btn"
            variant="outline"
            className="border-[hsl(var(--border))]"
          >
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
                <span data-testid="account-workspace" className="text-foreground font-medium">
                  {currentWs?.name || t('auth.my_workspace')}
                </span>
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
    </div>
  );
}
