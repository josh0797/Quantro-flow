import React, { useEffect, useState, useCallback } from 'react';
import { ShieldCheck, Activity, AlertCircle, CheckCircle2, Loader2, ArrowRight } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../context/LanguageContext';

const backendUrl = process.env.REACT_APP_BACKEND_URL || '';

/**
 * SystemHealthCard
 * Dashboard surface for the Quantro OS self-healing layer.
 * Polls /api/system/health and displays a compact, trust-building status card.
 * Clickable → navigates to Settings → Integrations for details.
 */
export default function SystemHealthCard() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const { t } = useLanguage();

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch(`${backendUrl}/api/system/health`);
      if (res.ok) {
        const data = await res.json();
        setHealth(data);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  if (loading) {
    return (
      <Card data-testid="system-health-card" className="card-hover">
        <CardContent className="pt-6 flex items-center gap-3 text-sm text-muted-foreground">
          <Loader2 size={16} className="animate-spin" />
          <span>{t('common.loading')}</span>
        </CardContent>
      </Card>
    );
  }

  if (!health) return null;

  const { status, checks = [], latest_check } = health;
  const isHealthy = status === 'healthy';
  const isRepaired = status === 'repaired';
  const isDegraded = status === 'degraded';

  const borderTint = isDegraded
    ? 'border-[hsl(var(--critical)/0.35)]'
    : isRepaired
    ? 'border-[hsl(var(--warning)/0.35)]'
    : 'border-[hsl(var(--success)/0.3)]';
  const bgTint = isDegraded
    ? 'bg-[hsl(var(--critical)/0.04)]'
    : isRepaired
    ? 'bg-[hsl(var(--warning)/0.04)]'
    : 'bg-[hsl(var(--success)/0.04)]';
  const iconTint = isDegraded
    ? 'bg-[hsl(var(--critical)/0.15)] text-[hsl(var(--critical))]'
    : isRepaired
    ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'
    : 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]';
  const StateIcon = isDegraded ? AlertCircle : isRepaired ? Activity : ShieldCheck;
  const headline = isDegraded
    ? t('system_health.status_degraded')
    : isRepaired
    ? t('system_health.status_repaired')
    : t('system_health.title');
  const statusBadge = isDegraded
    ? t('system_health.checks.issues_detected')
    : isRepaired
    ? t('system_health.status_repaired').replace(/^.*?:\s*/, '')
    : t('system_health.all_operational');

  // Localize checks — map backend check.id to translation keys
  const checkLabelKey = {
    integrations: 'system_health.checks.integrations_stable',
    data_consistency: 'system_health.checks.data_consistency',
    issues: 'system_health.checks.no_issues',
  };

  return (
    <Card
      data-testid="system-health-card"
      data-status={status}
      className={`card-hover cursor-pointer ${borderTint} ${bgTint}`}
      onClick={() => navigate('/settings')}
    >
      <CardContent className="pt-6">
        <div className="flex items-start gap-3">
          <div className={`flex items-center justify-center w-10 h-10 shrink-0 rounded-lg ${iconTint}`}>
            <StateIcon size={18} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold text-foreground">{headline}</h3>
                <span
                  className={
                    isDegraded
                      ? 'text-[11px] font-medium text-[hsl(var(--critical))]'
                      : isRepaired
                      ? 'text-[11px] font-medium text-[hsl(var(--warning))]'
                      : 'text-[11px] font-medium text-[hsl(var(--success))]'
                  }
                >
                  · {statusBadge}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="text-xs h-7 px-2 text-muted-foreground hover:text-foreground"
                onClick={(e) => {
                  e.stopPropagation();
                  navigate('/settings');
                }}
                data-testid="system-health-details-button"
              >
                {t('common.details')} <ArrowRight size={12} className="ml-1" />
              </Button>
            </div>

            <ul className="mt-3 space-y-1.5">
              {checks.map((c) => {
                const localizedLabel = checkLabelKey[c.id]
                  ? t(checkLabelKey[c.id])
                  : c.label;
                return (
                  <li
                    key={c.id}
                    data-testid={`dash-system-check-${c.id}`}
                    className="flex items-center gap-2 text-xs"
                  >
                    {c.ok ? (
                      <CheckCircle2 size={12} className="text-[hsl(var(--success))] shrink-0" />
                    ) : (
                      <AlertCircle size={12} className="text-[hsl(var(--critical))] shrink-0" />
                    )}
                    <span className="text-foreground/90">{localizedLabel}</span>
                    <span className="text-muted-foreground">— {c.detail}</span>
                  </li>
                );
              })}
            </ul>

            {isRepaired && latest_check?.repairs?.length > 0 && (
              <div
                data-testid="dash-repairs-detail"
                className="mt-3 pt-2 border-t border-[hsl(var(--border))]"
              >
                <p className="text-[11px] text-muted-foreground">
                  <Activity size={10} className="inline mr-1 text-[hsl(var(--warning))]" />
                  {latest_check.repairs[0].detail}
                  {latest_check.repairs.length > 1 && (
                    <span> (+{latest_check.repairs.length - 1} more)</span>
                  )}
                </p>
              </div>
            )}

            {isHealthy && (
              <p className="text-[11px] text-muted-foreground/70 italic mt-3">
                {t('system_health.tagline')}
              </p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
