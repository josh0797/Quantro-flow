import React, { useState, useEffect, useCallback } from 'react';
import {
  Plug,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  Copy,
  Check,
  Eye,
  EyeOff,
  Mail,
  Calendar,
  Users,
  Sparkles,
  Webhook,
  ExternalLink,
  AlertCircle,
  Lock,
  ShieldCheck,
  Activity,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';
import { useLanguage } from '../context/LanguageContext';

/**
 * Static manifest of supported integrations. This is the source of truth
 * for what users see — even if the backend returns an empty list, the
 * cards will still render so the Settings panel is never blank.
 * Backend `status` / `last_sync_at` / `config` values are merged on top.
 */
const INTEGRATION_MANIFEST = [
  {
    id: 'openai',
    i18nKey: 'integrations.openai',
    group: 'ai',
    name: 'OpenAI / LLM Provider',
    description: 'Powers AI classification, drafting, and auto-execution across your workflows.',
    helper: 'This workspace is currently powered by the Emergent Universal Key. Add your own key to override it per workspace.',
    icon: Sparkles,
    gradient: 'from-emerald-500 to-teal-500',
    connectLabelKey: 'integrations.actions.save_and_connect',
    fields: [
      { key: 'api_key', labelKey: 'integrations.openai.api_key', placeholder: 'sk-...', secret: true, required: true },
      {
        key: 'model',
        labelKey: 'integrations.openai.default_model',
        type: 'select',
        required: false,
        options: [
          { value: 'gpt-4o', label: 'gpt-4o (recommended)' },
          { value: 'gpt-4o-mini', label: 'gpt-4o-mini (fast, low cost)' },
          { value: 'gpt-4-turbo', label: 'gpt-4-turbo' },
        ],
        default: 'gpt-4o',
      },
    ],
  },
  {
    id: 'gmail',
    i18nKey: 'integrations.gmail',
    group: 'email',
    name: 'Gmail',
    description: 'Sync incoming email into Smart Inbox and let the system draft replies.',
    icon: Mail,
    gradient: 'from-red-500 to-orange-500',
    connectLabelKey: 'integrations.actions.connect_google',
    oauth: true,
    fields: [
      { key: 'email', labelKey: 'integrations.gmail.account', placeholder: 'you@company.com', required: true },
    ],
  },
  {
    id: 'google_calendar',
    i18nKey: 'integrations.calendar',
    group: 'email',
    name: 'Google Calendar',
    description: 'Two-way sync events, bookings, and availability windows.',
    icon: Calendar,
    gradient: 'from-blue-500 to-indigo-500',
    connectLabelKey: 'integrations.actions.connect_google',
    oauth: true,
    fields: [
      {
        key: 'calendar_id',
        labelKey: 'integrations.calendar.calendar_id',
        placeholder: 'primary',
        default: 'primary',
        required: true,
      },
    ],
  },
  {
    id: 'crm',
    i18nKey: 'integrations.crm',
    group: 'crm',
    name: 'CRM System',
    description: 'Bi-directional sync with HubSpot, GoHighLevel, Pipedrive, or any CRM with an API.',
    icon: Users,
    gradient: 'from-purple-500 to-pink-500',
    connectLabelKey: 'integrations.actions.save_and_connect',
    fields: [
      {
        key: 'provider',
        labelKey: 'integrations.crm.provider',
        type: 'select',
        required: true,
        options: [
          { value: 'hubspot', label: 'HubSpot' },
          { value: 'gohighlevel', label: 'GoHighLevel' },
          { value: 'pipedrive', label: 'Pipedrive' },
          { value: 'salesforce', label: 'Salesforce' },
          { value: 'custom', label: 'Custom / Other' },
        ],
      },
      { key: 'api_key', labelKey: 'integrations.crm.api_key', placeholder: 'Your CRM API key', secret: true, required: true },
      {
        key: 'base_url',
        labelKey: 'integrations.crm.base_url',
        placeholder: 'https://api.yourcrm.com',
        required: false,
      },
    ],
  },
  {
    id: 'webhook',
    i18nKey: 'integrations.webhook',
    group: 'automation',
    name: 'Inbound Webhooks',
    description: 'Forward events from any service into Business OS. Use the endpoint below in your external tools.',
    icon: Webhook,
    gradient: 'from-amber-500 to-yellow-500',
    connectLabelKey: 'integrations.actions.enable_webhooks',
    fields: [
      {
        key: 'secret',
        labelKey: 'integrations.webhook.shared_secret',
        placeholder: 'Generate a random string',
        secret: true,
        required: false,
      },
    ],
    showEndpoint: true,
  },
];

const GROUPS = [
  { key: 'ai', i18nKey: 'integrations.groups.ai', icon: Sparkles },
  { key: 'email', i18nKey: 'integrations.groups.email', icon: Mail },
  { key: 'crm', i18nKey: 'integrations.groups.crm', icon: Users },
  { key: 'automation', i18nKey: 'integrations.groups.automation', icon: Webhook },
];

const backendUrl = process.env.REACT_APP_BACKEND_URL || '';

/**
 * SystemStatusBanner
 * Surfaces the Quantro OS self-healing layer as a trust signal.
 * Polls /api/system/health and displays an Apple/Stripe-style status panel.
 * Also fires a one-time per-session toast when a repair was applied on last startup.
 */
function SystemStatusBanner({ health, t }) {
  if (!health) return null;
  const { status, checks = [], latest_check } = health;
  const isHealthy = status === 'healthy';
  const isRepaired = status === 'repaired';
  const isDegraded = status === 'degraded';

  const stateStyles = isDegraded
    ? 'border-[hsl(var(--critical)/0.35)] bg-[hsl(var(--critical)/0.06)]'
    : isRepaired
    ? 'border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.06)]'
    : 'border-[hsl(var(--success)/0.35)] bg-[hsl(var(--success)/0.05)]';
  const iconTint = isDegraded
    ? 'text-[hsl(var(--critical))] bg-[hsl(var(--critical)/0.15)]'
    : isRepaired
    ? 'text-[hsl(var(--warning))] bg-[hsl(var(--warning)/0.15)]'
    : 'text-[hsl(var(--success))] bg-[hsl(var(--success)/0.15)]';

  const StateIcon = isDegraded ? AlertCircle : isRepaired ? Activity : ShieldCheck;
  const headline = isDegraded
    ? t('system_health.status_degraded')
    : isRepaired
    ? t('system_health.status_repaired')
    : t('system_health.status_healthy');
  const subcopy = isDegraded
    ? t('system_health.subcopy_degraded')
    : isRepaired
    ? t('system_health.subcopy_repaired')
    : t('system_health.subcopy_healthy');

  // Map backend check.id → localized label
  const checkLabelKey = {
    integrations: 'system_health.checks.integrations_stable',
    data_consistency: 'system_health.checks.data_consistency',
    issues: 'system_health.checks.no_issues',
  };

  return (
    <div
      data-testid="system-status-banner"
      data-status={status}
      className={`rounded-xl border ${stateStyles} p-5 transition-colors`}
    >
      <div className="flex items-start gap-4">
        <div
          className={`w-10 h-10 shrink-0 rounded-lg flex items-center justify-center ${iconTint}`}
        >
          <StateIcon size={20} />
        </div>
        <div className="flex-1 min-w-0 space-y-3">
          <div className="flex items-baseline gap-2 flex-wrap">
            <h2 className="text-sm font-semibold text-foreground">{headline}</h2>
            {isHealthy && (
              <span className="inline-flex items-center gap-1 text-[hsl(var(--success))] text-xs font-medium">
                <CheckCircle2 size={12} /> {t('system_health.all_operational')}
              </span>
            )}
            {latest_check?.checked_at && (
              <span className="text-[11px] text-muted-foreground ml-auto">
                {t('system_health.last_check', { time: new Date(latest_check.checked_at).toLocaleString() })}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed max-w-3xl">{subcopy}</p>

          {/* Check summary grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1">
            {checks.map((c) => {
              const localizedLabel = checkLabelKey[c.id] ? t(checkLabelKey[c.id]) : c.label;
              return (
                <div
                  key={c.id}
                  data-testid={`system-check-${c.id}`}
                  className="flex items-start gap-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background)/0.5)] px-3 py-2"
                >
                  {c.ok ? (
                    <CheckCircle2 size={14} className="text-[hsl(var(--success))] mt-0.5 shrink-0" />
                  ) : (
                    <AlertCircle size={14} className="text-[hsl(var(--critical))] mt-0.5 shrink-0" />
                  )}
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-foreground">{localizedLabel}</p>
                    <p className="text-[11px] text-muted-foreground truncate">{c.detail}</p>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Recent repairs breakdown */}
          {isRepaired && latest_check?.repairs?.length > 0 && (
            <div
              data-testid="recent-repairs-list"
              className="pt-2 border-t border-[hsl(var(--border))] mt-2"
            >
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
                {t('system_health.auto_resolved_header')}
              </p>
              <ul className="space-y-1">
                {latest_check.repairs.map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                    <Activity size={12} className="text-[hsl(var(--warning))] mt-0.5 shrink-0" />
                    <span>{r.detail}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Tagline */}
          <p className="text-[11px] text-muted-foreground/70 italic pt-1">— {t('system_health.tagline')}</p>
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status, t }) {
  const isConnected = status === 'connected';
  return (
    <Badge
      data-testid={`status-badge-${status}`}
      className={
        isConnected
          ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] border border-[hsl(var(--success)/0.3)]'
          : 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))] border border-[hsl(var(--border))]'
      }
    >
      {isConnected ? (
        <>
          <CheckCircle2 size={12} className="mr-1" /> {t('integrations.status.connected')}
        </>
      ) : (
        <>
          <XCircle size={12} className="mr-1" /> {t('integrations.status.not_connected')}
        </>
      )}
    </Badge>
  );
}

function SecretInput({ value, onChange, placeholder, testId }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="bg-[hsl(var(--background))] pr-10 font-mono text-sm"
        data-testid={testId}
        autoComplete="off"
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
        aria-label={visible ? 'Hide secret' : 'Show secret'}
        data-testid={`${testId}-toggle`}
      >
        {visible ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}

function CopyableEndpoint({ url, testId }) {
  const { t } = useLanguage();
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    const copyViaFallback = () => {
      try {
        const ta = document.createElement('textarea');
        ta.value = url;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
      } catch {
        return false;
      }
    };

    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
      } else if (!copyViaFallback()) {
        throw new Error('clipboard unavailable');
      }
      setCopied(true);
      toast.success(t('integrations.toasts.endpoint_copied'));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t('integrations.toasts.copy_failed'));
    }
  };
  return (
    <div className="flex items-center gap-2">
      <code
        className="flex-1 text-xs font-mono bg-[hsl(var(--muted)/0.4)] border border-[hsl(var(--border))] rounded-md px-3 py-2 truncate"
        data-testid={`${testId}-url`}
      >
        {url}
      </code>
      <Button
        variant="outline"
        size="sm"
        onClick={handleCopy}
        data-testid={`${testId}-copy-button`}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </Button>
    </div>
  );
}

function IntegrationCard({ manifest, backendState, onConnect, onDisconnect, onTest, testingProvider, t }) {
  const Icon = manifest.icon;
  const status = backendState?.status || 'disconnected';
  const isConnected = status === 'connected';
  const existingConfig = backendState?.config || {};

  const [formValues, setFormValues] = useState(() => {
    const init = {};
    for (const f of manifest.fields || []) {
      init[f.key] = existingConfig[f.key] ?? f.default ?? '';
    }
    return init;
  });

  // Resync form values when backendState changes (e.g., after fetch or disconnect)
  useEffect(() => {
    const next = {};
    for (const f of manifest.fields || []) {
      next[f.key] = (backendState?.config || {})[f.key] ?? f.default ?? '';
    }
    setFormValues(next);
  }, [backendState, manifest]);

  const setValue = (key, val) => setFormValues((prev) => ({ ...prev, [key]: val }));

  const requiredFilled = (manifest.fields || [])
    .filter((f) => f.required)
    .every((f) => (formValues[f.key] || '').toString().trim().length > 0);

  const handleSubmit = async () => {
    await onConnect(manifest.id, formValues);
  };

  const endpoint = manifest.showEndpoint ? `${backendUrl}/api/webhooks/${manifest.id}` : null;

  // Localized name/description/helper from translation keys (falls back to manifest defaults)
  const localName = manifest.i18nKey ? t(`${manifest.i18nKey}.name`) : manifest.name;
  const localDescription = manifest.i18nKey
    ? t(`${manifest.i18nKey}.description`)
    : manifest.description;
  const localHelper = manifest.i18nKey && manifest.helper
    ? t(`${manifest.i18nKey}.helper`)
    : manifest.helper;
  const localConnectLabel = manifest.connectLabelKey
    ? t(manifest.connectLabelKey)
    : manifest.connectLabel;

  return (
    <Card
      data-testid={`${manifest.id}-integration-card`}
      className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))] transition-colors hover:border-[hsl(var(--primary)/0.4)]"
    >
      <div className="flex items-start gap-4">
        <div
          className={`w-11 h-11 shrink-0 rounded-lg bg-gradient-to-br ${manifest.gradient} flex items-center justify-center text-white shadow-sm`}
        >
          <Icon size={20} />
        </div>

        <div className="flex-1 min-w-0 space-y-4">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <h3 className="text-base font-semibold text-foreground">{localName}</h3>
              <p className="text-xs text-muted-foreground mt-0.5">{localDescription}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <StatusBadge status={status} t={t} />
              {backendState?.last_sync_at && (
                <span className="text-[11px] text-muted-foreground">
                  {t('integrations.status.last_sync', { time: new Date(backendState.last_sync_at).toLocaleString() })}
                </span>
              )}
            </div>
          </div>

          {localHelper && (
            <div className="flex gap-2 items-start rounded-md border border-[hsl(var(--primary)/0.2)] bg-[hsl(var(--primary)/0.05)] px-3 py-2">
              <AlertCircle size={14} className="text-[hsl(var(--primary))] mt-0.5 shrink-0" />
              <p className="text-xs text-muted-foreground leading-relaxed">{localHelper}</p>
            </div>
          )}

          {endpoint && (
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground uppercase tracking-wide">
                {t('integrations.webhook.endpoint_label')}
              </Label>
              <CopyableEndpoint url={endpoint} testId={`${manifest.id}-endpoint`} />
            </div>
          )}

          {/* Config form */}
          {manifest.fields && manifest.fields.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {manifest.fields.map((f) => {
                const inputId = `${manifest.id}-${f.key}`;
                const testId = `${manifest.id}-${f.key}-input`;
                const value = formValues[f.key] ?? '';
                const localFieldLabel = f.labelKey ? t(f.labelKey) : f.label;
                const commonLabel = (
                  <Label
                    htmlFor={inputId}
                    className="text-xs flex items-center gap-1.5"
                  >
                    {f.secret && <Lock size={11} className="text-muted-foreground" />}
                    {localFieldLabel}
                    {f.required && <span className="text-[hsl(var(--critical))]">*</span>}
                  </Label>
                );
                return (
                  <div
                    key={f.key}
                    className={f.type === 'select' || !f.secret ? 'sm:col-span-1' : 'sm:col-span-2'}
                  >
                    {commonLabel}
                    <div className="mt-1">
                      {f.type === 'select' ? (
                        <Select
                          value={value || ''}
                          onValueChange={(v) => setValue(f.key, v)}
                        >
                          <SelectTrigger
                            id={inputId}
                            className="bg-[hsl(var(--background))]"
                            data-testid={testId}
                          >
                            <SelectValue placeholder="Select..." />
                          </SelectTrigger>
                          <SelectContent>
                            {f.options.map((opt) => (
                              <SelectItem key={opt.value} value={opt.value}>
                                {opt.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : f.secret ? (
                        <SecretInput
                          value={value}
                          onChange={(v) => setValue(f.key, v)}
                          placeholder={f.placeholder}
                          testId={testId}
                        />
                      ) : (
                        <Input
                          id={inputId}
                          value={value}
                          onChange={(e) => setValue(f.key, e.target.value)}
                          placeholder={f.placeholder}
                          className="bg-[hsl(var(--background))]"
                          data-testid={testId}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            {isConnected ? (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => onTest(manifest.id)}
                  disabled={testingProvider === manifest.id}
                  data-testid={`test-${manifest.id}-button`}
                >
                  {testingProvider === manifest.id ? (
                    <Loader2 className="animate-spin" size={14} />
                  ) : (
                    <RefreshCw size={14} />
                  )}
                  <span className="ml-2">{t('integrations.actions.test_connection')}</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSubmit}
                  data-testid={`update-${manifest.id}-button`}
                >
                  {t('integrations.actions.update_config')}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDisconnect(manifest.id)}
                  className="text-[hsl(var(--critical))] hover:text-[hsl(var(--critical))] hover:bg-[hsl(var(--critical)/0.1)]"
                  data-testid={`disconnect-${manifest.id}-button`}
                >
                  {t('integrations.actions.disconnect')}
                </Button>
              </>
            ) : (
              <Button
                size="sm"
                onClick={handleSubmit}
                disabled={!requiredFilled}
                data-testid={`connect-${manifest.id}-button`}
              >
                {manifest.oauth ? (
                  <ExternalLink size={14} className="mr-2" />
                ) : (
                  <Plug size={14} className="mr-2" />
                )}
                {localConnectLabel}
              </Button>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function IntegrationsPanel() {
  const { t } = useLanguage();
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testingProvider, setTestingProvider] = useState(null);
  const [systemHealth, setSystemHealth] = useState(null);

  const fetchIntegrations = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${backendUrl}/api/integrations`);
      if (res.ok) {
        const data = await res.json();
        setIntegrations(Array.isArray(data) ? data : []);
      } else {
        setIntegrations([]);
      }
    } catch (err) {
      console.error('Failed to load integrations:', err);
      toast.error(t('integrations.toasts.load_failed'));
      setIntegrations([]);
    } finally {
      setLoading(false);
    }
  }, [t]);

  const fetchSystemHealth = useCallback(async (retry = 0) => {
    try {
      const res = await fetch(`${backendUrl}/api/system/health`);
      if (res.ok) {
        const data = await res.json();
        setSystemHealth(data);

        if (data?.status === 'repaired' && data?.latest_check?.event_id) {
          const seenKey = `qos_repair_seen_${data.latest_check.event_id}`;
          if (!sessionStorage.getItem(seenKey)) {
            const count = data.latest_check.repair_count || 0;
            toast.success(
              count > 1
                ? t('system_health.repair_toast_multi', { count })
                : t('system_health.repair_toast_single'),
              { duration: 5000 }
            );
            sessionStorage.setItem(seenKey, '1');
          }
        }
      } else if (retry < 2) {
        setTimeout(() => fetchSystemHealth(retry + 1), 500);
      }
    } catch (err) {
      console.warn('system health check unavailable:', err);
      if (retry < 2) setTimeout(() => fetchSystemHealth(retry + 1), 500);
    }
  }, [t]);

  useEffect(() => {
    fetchIntegrations();
    fetchSystemHealth();
  }, [fetchIntegrations, fetchSystemHealth]);

  const getBackendState = (provider) =>
    integrations.find((i) => i.provider === provider) || null;

  const handleConnect = async (provider, config) => {
    try {
      const res = await fetch(`${backendUrl}/api/integrations/${provider}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'connected', config }),
      });
      if (res.ok) {
        toast.success(t('integrations.toasts.connected', { provider }));
        fetchIntegrations();
      } else {
        toast.error(t('integrations.toasts.connect_failed', { provider }));
      }
    } catch {
      toast.error(t('integrations.toasts.load_failed'));
    }
  };

  const handleDisconnect = async (provider) => {
    try {
      const res = await fetch(`${backendUrl}/api/integrations/${provider}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'disconnected', config: {} }),
      });
      if (res.ok) {
        toast.success(t('integrations.toasts.disconnected', { provider }));
        fetchIntegrations();
      } else {
        toast.error(t('integrations.toasts.connect_failed', { provider }));
      }
    } catch {
      toast.error(t('integrations.toasts.load_failed'));
    }
  };

  const handleTest = async (provider) => {
    try {
      setTestingProvider(provider);
      const res = await fetch(`${backendUrl}/api/integrations/${provider}/test`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) toast.success(t('integrations.toasts.test_ok', { provider }));
      else toast.error(t('integrations.toasts.test_fail', { provider }));
    } catch {
      toast.error(t('integrations.toasts.test_fail', { provider }));
    } finally {
      setTestingProvider(null);
    }
  };

  if (loading) {
    return (
      <div
        className="flex items-center justify-center py-16"
        data-testid="integrations-loading"
      >
        <Loader2 className="animate-spin text-muted-foreground" size={32} />
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="integrations-panel">
      <SystemStatusBanner health={systemHealth} t={t} />

      {GROUPS.map((group) => {
        const items = INTEGRATION_MANIFEST.filter((m) => m.group === group.key);
        if (items.length === 0) return null;
        const GroupIcon = group.icon;
        return (
          <section
            key={group.key}
            data-testid={`integration-group-${group.key}`}
            className="space-y-3"
          >
            <div className="flex items-center gap-2 px-1">
              <GroupIcon size={14} className="text-muted-foreground" />
              <h3 className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                {t(group.i18nKey)}
              </h3>
              <Separator className="flex-1 bg-[hsl(var(--border))]" />
            </div>
            <div className="space-y-3">
              {items.map((m) => (
                <IntegrationCard
                  key={m.id}
                  manifest={m}
                  backendState={getBackendState(m.id)}
                  onConnect={handleConnect}
                  onDisconnect={handleDisconnect}
                  onTest={handleTest}
                  testingProvider={testingProvider}
                  t={t}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
