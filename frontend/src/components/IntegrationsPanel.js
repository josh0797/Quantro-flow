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
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { toast } from 'sonner';

/**
 * Static manifest of supported integrations. This is the source of truth
 * for what users see — even if the backend returns an empty list, the
 * cards will still render so the Settings panel is never blank.
 * Backend `status` / `last_sync_at` / `config` values are merged on top.
 */
const INTEGRATION_MANIFEST = [
  {
    id: 'openai',
    group: 'ai',
    groupLabel: 'AI & Intelligence',
    name: 'OpenAI / LLM Provider',
    description:
      'Powers AI classification, drafting, and auto-execution across your workflows.',
    icon: Sparkles,
    gradient: 'from-emerald-500 to-teal-500',
    connectLabel: 'Save & Connect',
    fields: [
      { key: 'api_key', label: 'API Key', placeholder: 'sk-...', secret: true, required: true },
      {
        key: 'model',
        label: 'Default Model',
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
    helper:
      'This workspace is currently powered by the Emergent Universal Key. Add your own key to override it per workspace.',
  },
  {
    id: 'gmail',
    group: 'email',
    groupLabel: 'Email & Calendar',
    name: 'Gmail',
    description: 'Sync incoming email into Smart Inbox and let the system draft replies.',
    icon: Mail,
    gradient: 'from-red-500 to-orange-500',
    connectLabel: 'Connect with Google',
    oauth: true,
    fields: [
      { key: 'email', label: 'Connected Account', placeholder: 'you@company.com', required: true },
    ],
  },
  {
    id: 'google_calendar',
    group: 'email',
    groupLabel: 'Email & Calendar',
    name: 'Google Calendar',
    description: 'Two-way sync events, bookings, and availability windows.',
    icon: Calendar,
    gradient: 'from-blue-500 to-indigo-500',
    connectLabel: 'Connect with Google',
    oauth: true,
    fields: [
      {
        key: 'calendar_id',
        label: 'Calendar ID',
        placeholder: 'primary',
        default: 'primary',
        required: true,
      },
    ],
  },
  {
    id: 'crm',
    group: 'crm',
    groupLabel: 'CRM',
    name: 'CRM System',
    description:
      'Bi-directional sync with HubSpot, GoHighLevel, Pipedrive, or any CRM with an API.',
    icon: Users,
    gradient: 'from-purple-500 to-pink-500',
    connectLabel: 'Save & Connect',
    fields: [
      {
        key: 'provider',
        label: 'CRM Provider',
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
      { key: 'api_key', label: 'API Key', placeholder: 'Your CRM API key', secret: true, required: true },
      {
        key: 'base_url',
        label: 'Base URL (optional)',
        placeholder: 'https://api.yourcrm.com',
        required: false,
      },
    ],
  },
  {
    id: 'webhook',
    group: 'automation',
    groupLabel: 'Webhooks & Endpoints',
    name: 'Inbound Webhooks',
    description:
      'Forward events from any service into Business OS. Use the endpoint below in your external tools.',
    icon: Webhook,
    gradient: 'from-amber-500 to-yellow-500',
    connectLabel: 'Enable Webhooks',
    fields: [
      {
        key: 'secret',
        label: 'Shared Secret (optional)',
        placeholder: 'Generate a random string',
        secret: true,
        required: false,
      },
    ],
    showEndpoint: true,
  },
];

const GROUPS = [
  { key: 'ai', label: 'AI & Intelligence', icon: Sparkles },
  { key: 'email', label: 'Email & Calendar', icon: Mail },
  { key: 'crm', label: 'CRM', icon: Users },
  { key: 'automation', label: 'Webhooks & Endpoints', icon: Webhook },
];

const backendUrl = process.env.REACT_APP_BACKEND_URL || '';

function StatusBadge({ status }) {
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
          <CheckCircle2 size={12} className="mr-1" /> Connected
        </>
      ) : (
        <>
          <XCircle size={12} className="mr-1" /> Not Connected
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
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      toast.success('Endpoint copied to clipboard');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Failed to copy');
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

function IntegrationCard({ manifest, backendState, onConnect, onDisconnect, onTest, testingProvider }) {
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
              <h3 className="text-base font-semibold text-foreground">{manifest.name}</h3>
              <p className="text-xs text-muted-foreground mt-0.5">{manifest.description}</p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <StatusBadge status={status} />
              {backendState?.last_sync_at && (
                <span className="text-[11px] text-muted-foreground">
                  Last sync: {new Date(backendState.last_sync_at).toLocaleString()}
                </span>
              )}
            </div>
          </div>

          {manifest.helper && (
            <div className="flex gap-2 items-start rounded-md border border-[hsl(var(--primary)/0.2)] bg-[hsl(var(--primary)/0.05)] px-3 py-2">
              <AlertCircle size={14} className="text-[hsl(var(--primary))] mt-0.5 shrink-0" />
              <p className="text-xs text-muted-foreground leading-relaxed">{manifest.helper}</p>
            </div>
          )}

          {endpoint && (
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground uppercase tracking-wide">
                Your Inbound Endpoint
              </Label>
              <CopyableEndpoint url={endpoint} testId={`${manifest.id}-endpoint`} />
            </div>
          )}

          {/* Config form — always render for editability */}
          {manifest.fields && manifest.fields.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {manifest.fields.map((f) => {
                const inputId = `${manifest.id}-${f.key}`;
                const testId = `${manifest.id}-${f.key}-input`;
                const value = formValues[f.key] ?? '';
                const commonLabel = (
                  <Label
                    htmlFor={inputId}
                    className="text-xs flex items-center gap-1.5"
                  >
                    {f.secret && <Lock size={11} className="text-muted-foreground" />}
                    {f.label}
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
                  <span className="ml-2">Test Connection</span>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSubmit}
                  data-testid={`update-${manifest.id}-button`}
                >
                  Update Config
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onDisconnect(manifest.id)}
                  className="text-[hsl(var(--critical))] hover:text-[hsl(var(--critical))] hover:bg-[hsl(var(--critical)/0.1)]"
                  data-testid={`disconnect-${manifest.id}-button`}
                >
                  Disconnect
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
                {manifest.connectLabel || 'Connect'}
              </Button>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function IntegrationsPanel() {
  const [integrations, setIntegrations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testingProvider, setTestingProvider] = useState(null);

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
      toast.error('Failed to load integrations');
      setIntegrations([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIntegrations();
  }, [fetchIntegrations]);

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
        toast.success(`${provider} connected successfully`);
        fetchIntegrations();
      } else {
        toast.error(`Failed to connect ${provider}`);
      }
    } catch {
      toast.error('Network error while saving integration');
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
        toast.success(`${provider} disconnected`);
        fetchIntegrations();
      } else {
        toast.error(`Failed to disconnect ${provider}`);
      }
    } catch {
      toast.error('Network error');
    }
  };

  const handleTest = async (provider) => {
    try {
      setTestingProvider(provider);
      const res = await fetch(`${backendUrl}/api/integrations/${provider}/test`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) toast.success(data.message);
      else toast.error(data.message || 'Connection test failed');
    } catch {
      toast.error('Connection test failed');
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
    <div className="space-y-8" data-testid="integrations-panel">
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
                {group.label}
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
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
