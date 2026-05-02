import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, CheckCircle2, Loader2, RefreshCw, AlertTriangle, ArrowRight } from 'lucide-react';
import { toast } from 'sonner';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { es as esLocale, enUS as enLocale } from 'date-fns/locale';
import { useLanguage } from '../context/LanguageContext';
import {
  getGoogleIntegrationStatus,
  getMicrosoftIntegrationStatus,
  syncGoogleData,
  syncMicrosoftData,
} from '../lib/api';

/**
 * DataModeBanner — persistent honesty strip rendered above /smart-inbox
 * and /schedule. It has two visual states:
 *
 *   • DEMO  — neither Google nor Microsoft is connected. We tell the
 *             user the data they're seeing is sample data and offer a
 *             one-tap path to /welcome/inbox so they can connect.
 *   • REAL  — at least one provider is connected. We show the account
 *             email, the last_sync_at relative time, and a manual
 *             "Sincronizar ahora" trigger so power users don't have to
 *             wait for the 15-min scheduler.
 *
 * The banner polls the status endpoints every 60s and after each
 * manual sync to keep the relative time fresh without hammering the
 * backend. It silently degrades to demo mode if the status call fails
 * (network, 401, etc.).
 *
 * Props:
 *   - module: 'inbox' | 'schedule' — drives the copy (we say "tu
 *             bandeja" or "tu agenda" instead of generic).
 */
export default function DataModeBanner({ module = 'inbox' }) {
  const { t, language } = useLanguage();
  const navigate = useNavigate();
  const [google, setGoogle] = useState(null);
  const [microsoft, setMicrosoft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const [g, m] = await Promise.all([
        getGoogleIntegrationStatus().catch(() => null),
        getMicrosoftIntegrationStatus().catch(() => null),
      ]);
      setGoogle(g);
      setMicrosoft(m);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    // Refresh every 60s so the "hace X min" label stays accurate
    // without forcing the user to refresh the page.
    const id = window.setInterval(fetchStatus, 60_000);
    return () => window.clearInterval(id);
  }, [fetchStatus]);

  // Pick the active provider. If both are connected we honour Google
  // first (more common in our user base) but the UI surfaces only the
  // active one to avoid confusion.
  const active =
    google?.connected ? { name: 'google', label: 'Google', status: google } :
    microsoft?.connected ? { name: 'microsoft', label: 'Microsoft', status: microsoft } :
    null;

  const handleConnect = () => {
    navigate(module === 'schedule' ? '/welcome/calendar' : '/welcome/inbox');
  };

  const handleSync = async () => {
    if (!active || syncing) return;
    setSyncing(true);
    try {
      const fn = active.name === 'google' ? syncGoogleData : syncMicrosoftData;
      const res = await fn();
      const counts = res?.counts || {};
      toast.success(t('data_mode_banner.sync_success_title'), {
        description: t('data_mode_banner.sync_success_desc', {
          emails: counts.emails ?? 0,
          events: counts.events ?? 0,
          provider: active.label,
        }),
      });
      await fetchStatus();
    } catch (err) {
      toast.error(t('data_mode_banner.sync_failed_title'), {
        description: err?.response?.data?.detail || t('data_mode_banner.sync_failed_desc'),
      });
    } finally {
      setSyncing(false);
    }
  };

  // Avoid a layout flash while we figure out the mode.
  if (loading) {
    return (
      <div
        className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted)/0.3)] h-12 mb-4 animate-pulse"
        data-testid="data-mode-banner-loading"
      />
    );
  }

  const localeObj = language === 'es' ? esLocale : enLocale;
  const lastSyncLabel = active?.status?.last_sync_at
    ? formatDistanceToNow(parseISO(active.status.last_sync_at), { addSuffix: true, locale: localeObj })
    : t('data_mode_banner.last_sync_never');

  // ── REAL mode ────────────────────────────────────────────────────
  if (active) {
    const hasError = !!active.status?.last_sync_error;
    const isPaused = !!active.status?.auto_sync_paused;
    return (
      <div
        className={[
          'rounded-xl border px-4 py-3 mb-5 flex items-center gap-3',
          'bg-[hsl(var(--primary)/0.06)] border-[hsl(var(--primary)/0.30)]',
        ].join(' ')}
        data-testid="data-mode-banner-real"
        data-mode="real"
      >
        <div className="shrink-0 size-8 rounded-lg bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] flex items-center justify-center">
          <CheckCircle2 size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-foreground" data-testid="data-mode-banner-title">
              {t('data_mode_banner.real_title', { provider: active.label })}
            </span>
            <span className="text-[10px] uppercase tracking-[0.16em] font-semibold rounded-full px-2 py-0.5 bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] border border-[hsl(var(--primary)/0.30)]">
              {t('welcome.preview.badge_real')}
            </span>
            {isPaused && (
              <span className="text-[10px] uppercase tracking-[0.16em] font-semibold rounded-full px-2 py-0.5 bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] border border-[hsl(var(--warning)/0.30)]">
                {t('data_mode_banner.paused_badge')}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5 truncate" data-testid="data-mode-banner-meta">
            {active.status?.account_email ? `${active.status.account_email} · ` : ''}
            {t('data_mode_banner.last_sync_label', { when: lastSyncLabel })}
          </p>
          {hasError && (
            <p className="text-xs text-[hsl(var(--warning))] mt-1 flex items-center gap-1.5" data-testid="data-mode-banner-error">
              <AlertTriangle size={12} />
              {t('data_mode_banner.last_sync_error_label')}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={handleSync}
          disabled={syncing}
          data-testid="data-mode-banner-sync-btn"
          className="shrink-0 inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--primary)/0.30)] bg-[hsl(var(--primary)/0.10)] hover:bg-[hsl(var(--primary)/0.18)] text-[hsl(var(--primary))] px-3 py-1.5 text-xs font-semibold transition-colors duration-200 disabled:opacity-60 disabled:cursor-wait focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary)/0.55)]"
        >
          {syncing ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          {syncing ? t('data_mode_banner.syncing') : t('data_mode_banner.sync_now')}
        </button>
      </div>
    );
  }

  // ── DEMO mode ────────────────────────────────────────────────────
  const demoTitleKey = module === 'schedule'
    ? 'data_mode_banner.demo_title_schedule'
    : 'data_mode_banner.demo_title_inbox';
  const demoDescKey = module === 'schedule'
    ? 'data_mode_banner.demo_desc_schedule'
    : 'data_mode_banner.demo_desc_inbox';
  const demoCtaKey = module === 'schedule'
    ? 'data_mode_banner.demo_cta_schedule'
    : 'data_mode_banner.demo_cta_inbox';

  return (
    <div
      className={[
        'rounded-xl border px-4 py-3 mb-5 flex items-center gap-3',
        'bg-[hsl(var(--warning)/0.06)] border-[hsl(var(--warning)/0.30)]',
      ].join(' ')}
      data-testid="data-mode-banner-demo"
      data-mode="demo"
    >
      <div className="shrink-0 size-8 rounded-lg bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] flex items-center justify-center">
        <Sparkles size={16} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-semibold text-foreground" data-testid="data-mode-banner-title">
            {t(demoTitleKey)}
          </span>
          <span className="text-[10px] uppercase tracking-[0.16em] font-semibold rounded-full px-2 py-0.5 bg-[hsl(var(--muted)/0.6)] text-muted-foreground border border-[hsl(var(--border))]">
            {t('welcome.preview.badge_demo')}
          </span>
        </div>
        <p className="text-xs text-muted-foreground mt-0.5" data-testid="data-mode-banner-meta">
          {t(demoDescKey)}
        </p>
      </div>
      <button
        type="button"
        onClick={handleConnect}
        data-testid="data-mode-banner-connect-btn"
        className="shrink-0 inline-flex items-center gap-1.5 rounded-full bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.92)] text-[hsl(var(--primary-foreground))] px-3.5 py-1.5 text-xs font-semibold transition-all duration-200 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--primary)/0.6)]"
      >
        {t(demoCtaKey)}
        <ArrowRight size={12} />
      </button>
    </div>
  );
}
