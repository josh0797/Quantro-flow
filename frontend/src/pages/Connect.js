import React, { useCallback, useEffect, useMemo, useState } from 'react';
import LearnLink from '../components/LearnLink';
import { toast } from 'sonner';
import {
  Search, CheckCircle2, AlertTriangle, XCircle, Settings2, Loader2,
  RefreshCw, Unlink2, Mail, Receipt, Bot, Sparkles, Lock,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet';
import { useLanguage } from '../context/LanguageContext';
import {
  getConnectProviders, testConnection, syncConnection, disconnectProvider,
  requestGooglePermission, requestMicrosoftPermission, getActions, getActionExecutions,
  startGoogleOAuth, startMicrosoftOAuth,
} from '../lib/api';

const CATEGORY_ORDER = ['all', 'productivity', 'fiscal', 'ai', 'automation', 'internal'];

const PROVIDER_ICON = {
  google: Mail,
  microsoft: Mail,
  quantro_invoicing: Receipt,
  quantro_internal: Sparkles,
};

function statusTone(status) {
  switch (status) {
    case 'connected': return 'success';
    case 'connected_limited': return 'warning';
    case 'reauthorization_required': return 'warning';
    case 'error': return 'critical';
    case 'configuration_missing': return 'critical';
    default: return 'muted';
  }
}

function StatusBadge({ status, t }) {
  const tone = statusTone(status);
  const cls = {
    success: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.3)]',
    warning: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.3)]',
    critical: 'bg-[hsl(var(--critical)/0.15)] text-[hsl(var(--critical))] border-[hsl(var(--critical)/0.3)]',
    muted: 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))] border-[hsl(var(--border))]',
  }[tone];
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'muted' ? XCircle : AlertTriangle;
  return (
    <Badge data-testid={`status-badge-${status}`} className={`border ${cls}`}>
      <Icon size={12} className="mr-1" /> {t(`connect.status.${status}`)}
    </Badge>
  );
}

function ProviderCard({ provider, onOpen, t }) {
  const Icon = PROVIDER_ICON[provider.provider_id] || Settings2;
  return (
    <Card
      data-testid={`connect-provider-card-${provider.provider_id}`}
      className="p-5 bg-[hsl(var(--card))] border-[hsl(var(--border))] hover:border-[hsl(var(--primary)/0.4)] transition-colors cursor-pointer"
      onClick={() => onOpen(provider)}
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 shrink-0 rounded-lg bg-[hsl(var(--primary)/0.1)] flex items-center justify-center text-[hsl(var(--primary))]">
          <Icon size={18} />
        </div>
        <div className="flex-1 min-w-0 space-y-2">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-semibold text-foreground truncate">{provider.name}</h3>
            <StatusBadge status={provider.status} t={t} />
          </div>
          {provider.account?.label && (
            <p className="text-xs text-muted-foreground truncate">{provider.account.label}{provider.account?.environment ? ` · ${provider.account.environment}` : ''}</p>
          )}
          <p className="text-xs text-muted-foreground">
            {t('connect.card.actions_available', { count: (provider.actions_available || []).length })}
          </p>
          {provider.supports_sync && (
            <p className="text-[11px] text-muted-foreground">
              {provider.last_sync_at
                ? t('connect.card.last_sync', { time: new Date(provider.last_sync_at).toLocaleString() })
                : t('connect.card.never_synced')}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}

function ProviderDrawer({ provider, open, onClose, onChanged, t }) {
  const [tab, setTab] = useState('overview');
  const [busy, setBusy] = useState(false);
  const [providerActions, setProviderActions] = useState([]);
  const [activity, setActivity] = useState([]);

  useEffect(() => {
    if (!open || !provider) return;
    setTab('overview');
    getActions({ provider: provider.provider_id }).then(setProviderActions).catch(() => setProviderActions([]));
    getActionExecutions({ provider: provider.provider_id, limit: 20 }).then(setActivity).catch(() => setActivity([]));
  }, [open, provider]);

  if (!provider) return null;

  const handleTest = async () => {
    setBusy(true);
    try {
      const res = await testConnection(provider.provider_id);
      if (res.success) toast.success(res.message || t('connect.toasts.test_ok'));
      else toast.error(res.message || t('connect.toasts.test_fail'));
    } catch {
      toast.error(t('connect.toasts.test_fail'));
    } finally {
      setBusy(false);
    }
  };

  const handleSync = async () => {
    setBusy(true);
    try {
      await syncConnection(provider.provider_id);
      toast.success(t('connect.toasts.sync_ok'));
      onChanged();
    } catch {
      toast.error(t('connect.toasts.sync_fail'));
    } finally {
      setBusy(false);
    }
  };

  const handleDisconnect = async () => {
    setBusy(true);
    try {
      await disconnectProvider(provider.provider_id);
      toast.success(t('connect.toasts.disconnected', { provider: provider.name }));
      onChanged();
      onClose();
    } catch {
      toast.error(t('connect.toasts.action_failed'));
    } finally {
      setBusy(false);
    }
  };

  const handleGrantPermission = async (providerId, actionId) => {
    try {
      const returnTo = '/connect';
      const req =
        providerId === 'microsoft'
          ? requestMicrosoftPermission(actionId, returnTo)
          : requestGooglePermission(actionId, returnTo);
      const { auth_url } = await req;
      window.location.href = auth_url;
    } catch {
      toast.error(t('connect.toasts.action_failed'));
    }
  };

  const isQuantroInternal = provider.provider_id === 'quantro_internal';
  const isInvoicing = provider.provider_id === 'quantro_invoicing';

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent data-testid="connect-provider-drawer" className="sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{provider.name}</SheetTitle>
          <SheetDescription>{provider.description}</SheetDescription>
        </SheetHeader>

        <Tabs value={tab} onValueChange={setTab} className="mt-4">
          <TabsList className="grid grid-cols-4 w-full">
            <TabsTrigger value="overview" data-testid="drawer-tab-overview">{t('connect.drawer.tab_overview')}</TabsTrigger>
            <TabsTrigger value="permissions" data-testid="drawer-tab-permissions">{t('connect.drawer.tab_permissions')}</TabsTrigger>
            <TabsTrigger value="actions" data-testid="drawer-tab-actions">{t('connect.drawer.tab_actions')}</TabsTrigger>
            <TabsTrigger value="activity" data-testid="drawer-tab-activity">{t('connect.drawer.tab_activity')}</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-3 mt-4">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{t('connect.drawer.overview_status')}</span>
              <StatusBadge status={provider.status} t={t} />
            </div>
            {provider.account?.label && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{t('connect.drawer.overview_account')}</span>
                <span className="text-foreground truncate max-w-[60%]">{provider.account.label}</span>
              </div>
            )}
            {provider.supports_sync && (
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{t('connect.drawer.overview_last_sync')}</span>
                <span className="text-foreground">{provider.last_sync_at ? new Date(provider.last_sync_at).toLocaleString() : t('connect.card.never_synced')}</span>
              </div>
            )}
            <div className="flex flex-wrap gap-2 pt-2">
              {provider.status === 'disconnected' && provider.provider_id === 'google' && (
                <Button size="sm" onClick={() => startGoogleOAuth('/connect').then(({ auth_url }) => { window.location.href = auth_url; })}>{t('connect.card.connect')}</Button>
              )}
              {provider.status === 'disconnected' && provider.provider_id === 'microsoft' && (
                <Button size="sm" onClick={() => startMicrosoftOAuth('/connect').then(({ auth_url }) => { window.location.href = auth_url; })}>{t('connect.card.connect')}</Button>
              )}
              {provider.status !== 'disconnected' && !isQuantroInternal && !isInvoicing && (
                <>
                  <Button size="sm" variant="outline" onClick={handleTest} disabled={busy} data-testid="drawer-test-button">
                    {busy ? <Loader2 size={14} className="animate-spin mr-2" /> : <RefreshCw size={14} className="mr-2" />}
                    {t('connect.drawer.overview_test')}
                  </Button>
                  {provider.supports_sync && (
                    <Button size="sm" variant="outline" onClick={handleSync} disabled={busy} data-testid="drawer-sync-button">
                      {t('connect.drawer.overview_sync')}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={handleDisconnect} disabled={busy}
                    className="text-[hsl(var(--critical))] hover:text-[hsl(var(--critical))] hover:bg-[hsl(var(--critical)/0.1)]" data-testid="drawer-disconnect-button">
                    <Unlink2 size={14} className="mr-2" />{t('connect.drawer.overview_disconnect')}
                  </Button>
                </>
              )}
              {isInvoicing && (
                <Button size="sm" variant="outline" onClick={handleTest} disabled={busy} data-testid="drawer-test-button">
                  {busy ? <Loader2 size={14} className="animate-spin mr-2" /> : <RefreshCw size={14} className="mr-2" />}
                  {t('connect.drawer.overview_test')}
                </Button>
              )}
            </div>
          </TabsContent>

          <TabsContent value="permissions" className="space-y-3 mt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('connect.drawer.permissions_current')}</p>
            <div className="flex flex-wrap gap-1.5">
              {(provider.capabilities || []).map((c) => (
                <Badge key={c} variant="outline" className="text-[11px]">{c}</Badge>
              ))}
              {(provider.capabilities || []).length === 0 && <span className="text-xs text-muted-foreground">—</span>}
            </div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground pt-2">{t('connect.drawer.permissions_missing')}</p>
            {(provider.missing_scopes || []).length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('connect.drawer.permissions_none_missing')}</p>
            ) : (
              <div className="space-y-2">
                {provider.missing_scopes.map((scope) => {
                  const actionForScope = providerActions.find((a) => (a.required_scopes || []).includes(scope));
                  return (
                    <div key={scope} className="flex items-center justify-between gap-2 rounded-lg border border-[hsl(var(--warning)/0.3)] bg-[hsl(var(--warning)/0.06)] px-3 py-2">
                      <span className="text-xs font-mono text-foreground truncate">{scope}</span>
                      {(provider.provider_id === 'google' || provider.provider_id === 'microsoft') && actionForScope && (
                        <Button size="sm" variant="outline" onClick={() => handleGrantPermission(provider.provider_id, actionForScope.action_id)} data-testid="drawer-grant-permission-button">
                          <Lock size={12} className="mr-1.5" />{t('connect.drawer.grant_permission')}
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </TabsContent>

          <TabsContent value="actions" className="space-y-2 mt-4">
            {providerActions.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('connect.drawer.actions_none')}</p>
            ) : providerActions.map((a) => (
              <div key={a.action_id} data-testid={`drawer-action-${a.action_id}`} className="flex items-center justify-between gap-2 rounded-lg border border-[hsl(var(--border))] px-3 py-2">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-foreground truncate">{a.name}</p>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{a.risk_level}</p>
                </div>
                {a.connection_status === 'connected' ? (
                  <CheckCircle2 size={14} className="text-[hsl(var(--success))] shrink-0" />
                ) : a.connection_status === 'connected_limited' ? (
                  <span className="text-[10px] text-[hsl(var(--warning))] shrink-0">{t('actions.permission_required')}</span>
                ) : (
                  <XCircle size={14} className="text-muted-foreground shrink-0" />
                )}
              </div>
            ))}
          </TabsContent>

          <TabsContent value="activity" className="space-y-2 mt-4">
            {activity.length === 0 ? (
              <p className="text-xs text-muted-foreground">{t('connect.drawer.activity_none')}</p>
            ) : activity.map((e) => (
              <div key={e.execution_id} className="flex items-center justify-between gap-2 rounded-lg border border-[hsl(var(--border))] px-3 py-2 text-xs">
                <span className="text-foreground truncate">{e.action_id}</span>
                <Badge variant="outline" className="text-[10px]">{t(`actions.status.${e.status}`)}</Badge>
              </div>
            ))}
          </TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}

export default function Connect() {
  const { t } = useLanguage();
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('all');
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getConnectProviders();
      setProviders(data || []);
    } catch {
      toast.error(t('connect.toasts.load_failed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const filteredProviders = useMemo(
    () => providers
      .filter((p) => category === 'all' || p.category === category)
      .filter((p) => p.name.toLowerCase().includes(search.toLowerCase())),
    [providers, category, search],
  );

  // Hide empty categories (crm etc.) that have no live providers after removals.
  const visibleCategories = useMemo(() => {
    const present = new Set(providers.map((p) => p.category));
    return CATEGORY_ORDER.filter((c) => c === 'all' || present.has(c));
  }, [providers]);

  return (
    <div data-testid="connect-page" className="max-w-6xl mx-auto px-4 md:px-6 py-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Bot size={22} className="text-[hsl(var(--primary))]" />
          {t('connect.title')}
          <LearnLink route="connect" className="ml-1" />
        </h1>
        <p className="text-sm text-muted-foreground max-w-xl">{t('connect.subtitle')}</p>
      </header>

      <div className="flex flex-col md:flex-row gap-3">
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="connect-search-input"
            placeholder={t('connect.search_placeholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-[hsl(var(--background))]"
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-2" data-testid="connect-category-filters">
        {visibleCategories.map((cat) => (
          <button
            key={cat}
            data-testid={`connect-category-${cat}`}
            onClick={() => setCategory(cat)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
              category === cat
                ? 'bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] border-[hsl(var(--primary))]'
                : 'bg-transparent text-muted-foreground border-[hsl(var(--border))] hover:text-foreground'
            }`}
          >
            {t(`connect.categories.${cat}`)}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="connect-loading">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="connect-provider-grid">
          {filteredProviders.map((p) => (
            <ProviderCard key={p.provider_id} provider={p} onOpen={setSelected} t={t} />
          ))}
        </div>
      )}

      <ProviderDrawer
        provider={selected}
        open={!!selected}
        onClose={() => setSelected(null)}
        onChanged={load}
        t={t}
      />
    </div>
  );
}
