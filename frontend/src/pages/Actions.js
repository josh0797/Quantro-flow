import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  Search, Play, Loader2, CheckCircle2, XCircle, Clock, Zap, RefreshCw,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableHeader, TableBody, TableHead, TableRow, TableCell } from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import { useLanguage } from '../context/LanguageContext';
import {
  getActions, executeAction, getActionExecutions, approveActionExecution, cancelActionExecution,
} from '../lib/api';

const RISK_TONE = {
  low: 'bg-[hsl(var(--success)/0.14)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.3)]',
  medium: 'bg-[hsl(var(--info)/0.14)] text-[hsl(var(--info))] border-[hsl(var(--info)/0.3)]',
  high: 'bg-[hsl(var(--warning)/0.14)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.3)]',
  critical: 'bg-[hsl(var(--critical)/0.14)] text-[hsl(var(--critical))] border-[hsl(var(--critical)/0.3)]',
};

const STATUS_ICON = {
  succeeded: CheckCircle2, simulated: CheckCircle2, failed: XCircle,
  pending_approval: Clock, running: Loader2, cancelled: XCircle, approved: CheckCircle2, suggested: Clock,
};

function RiskBadge({ risk, t }) {
  return <Badge className={`border text-[10px] uppercase tracking-wide ${RISK_TONE[risk] || ''}`}>{t(`actions.risk.${risk}`)}</Badge>;
}

function defaultInputFor(schema) {
  const out = {};
  Object.entries(schema || {}).forEach(([key, spec]) => {
    if (spec.type === 'array') out[key] = [];
    else if (spec.type === 'object') out[key] = {};
    else if (spec.type === 'number') out[key] = 0;
    else out[key] = '';
  });
  return out;
}

function ExecuteActionModal({ action, open, onClose, onExecuted, t }) {
  const [inputText, setInputText] = useState('{}');
  const [dryRun, setDryRun] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (action) setInputText(JSON.stringify(defaultInputFor(action.input_schema), null, 2));
  }, [action]);

  if (!action) return null;

  const submit = async () => {
    let parsedInput;
    try {
      parsedInput = JSON.parse(inputText);
    } catch {
      toast.error(t('actions.execute_modal.invalid_json'));
      return;
    }
    setSubmitting(true);
    try {
      const result = await executeAction(action.action_id, {
        input: parsedInput,
        dry_run: dryRun,
        idempotency_key: idempotencyKey || undefined,
      });
      if (result.status === 'pending_approval') toast.success(t('actions.toasts.pending_approval'));
      else if (result.status === 'failed') toast.error(result.error_message_sanitized || t('actions.toasts.failed'));
      else toast.success(t('actions.toasts.executed'));
      onExecuted();
      onClose();
    } catch (err) {
      const detail = err?.response?.data;
      toast.error(detail?.message || t('actions.toasts.failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="execute-action-modal" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('actions.execute_modal.title', { name: action.name })}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-2">
          <div className="space-y-1.5">
            <Label>{t('actions.execute_modal.input_label')}</Label>
            <Textarea
              data-testid="execute-action-input"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              rows={8}
              className="font-mono text-xs bg-[hsl(var(--background))]"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="idempotency-key">{t('actions.execute_modal.idempotency_label')}</Label>
            <Input
              id="idempotency-key"
              data-testid="execute-action-idempotency-key"
              value={idempotencyKey}
              onChange={(e) => setIdempotencyKey(e.target.value)}
              className="bg-[hsl(var(--background))]"
            />
          </div>
          {action.supports_dry_run && (
            <div className="flex items-center gap-2">
              <Switch data-testid="execute-action-dry-run" checked={dryRun} onCheckedChange={setDryRun} />
              <Label className="cursor-pointer text-xs" onClick={() => setDryRun((v) => !v)}>
                {t('actions.execute_modal.dry_run_label')}
              </Label>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>{t('actions.execute_modal.cancel')}</Button>
          <Button data-testid="execute-action-submit" onClick={submit} disabled={submitting}>
            {submitting ? (<><Loader2 size={14} className="animate-spin mr-2" />{t('actions.execute_modal.submitting')}</>) : (<><Play size={14} className="mr-2" />{t('actions.execute_modal.submit')}</>)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ActionCard({ action, onExecute, t }) {
  const disabled = action.connection_status === 'disconnected' || action.connection_status === 'configuration_missing';
  const limited = action.connection_status === 'connected_limited' || action.connection_status === 'reauthorization_required';
  return (
    <Card data-testid={`action-card-${action.action_id}`} className="p-4 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-foreground truncate">{action.name}</h3>
            <RiskBadge risk={action.risk_level} t={t} />
          </div>
          <p className="text-xs text-muted-foreground">{action.description}</p>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{action.provider} · {action.action_id}</p>
        </div>
      </div>
      <div className="flex items-center justify-between mt-3">
        {disabled ? (
          <Badge variant="outline" className="text-[10px] text-muted-foreground">{t('actions.connect_provider')}</Badge>
        ) : limited ? (
          <Badge variant="outline" className="text-[10px] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.3)]">{t('actions.permission_required')}</Badge>
        ) : <span />}
        <Button size="sm" onClick={() => onExecute(action)} disabled={disabled} data-testid={`execute-button-${action.action_id}`}>
          <Play size={12} className="mr-1.5" />{t('actions.execute')}
        </Button>
      </div>
    </Card>
  );
}

function ExecutionRow({ execution, onApprove, onCancel, t }) {
  const Icon = STATUS_ICON[execution.status] || Clock;
  const spinning = execution.status === 'running';
  return (
    <TableRow data-testid={`execution-row-${execution.execution_id}`}>
      <TableCell>
        <span className="inline-flex items-center gap-1.5 text-xs">
          <Icon size={13} className={spinning ? 'animate-spin' : ''} />
          {t(`actions.status.${execution.status}`)}
        </span>
      </TableCell>
      <TableCell className="text-xs">{execution.action_id}</TableCell>
      <TableCell className="text-xs">{execution.provider}</TableCell>
      <TableCell className="text-xs">{execution.source}</TableCell>
      <TableCell className="text-xs">{execution.started_at ? new Date(execution.started_at).toLocaleString() : '—'}</TableCell>
      <TableCell className="text-xs max-w-[220px] truncate">
        {execution.status === 'failed' ? execution.error_message_sanitized : JSON.stringify(execution.result_metadata || {})}
      </TableCell>
      <TableCell className="text-right">
        {execution.status === 'pending_approval' && (
          <div className="flex gap-1.5 justify-end">
            <Button size="sm" variant="outline" onClick={() => onApprove(execution)} data-testid={`approve-button-${execution.execution_id}`}>{t('actions.history.approve')}</Button>
            <Button size="sm" variant="ghost" onClick={() => onCancel(execution)} data-testid={`cancel-button-${execution.execution_id}`}>{t('actions.history.cancel')}</Button>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

export default function Actions() {
  const { t } = useLanguage();
  const [tab, setTab] = useState('available');
  const [actionsList, setActionsList] = useState([]);
  const [executions, setExecutions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState('all');
  const [riskFilter, setRiskFilter] = useState('all');
  const [executeTarget, setExecuteTarget] = useState(null);

  const loadActions = useCallback(async () => {
    setLoading(true);
    try {
      setActionsList(await getActions());
    } catch {
      toast.error(t('actions.toasts.load_failed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const loadExecutions = useCallback(async () => {
    try {
      setExecutions(await getActionExecutions({ limit: 100 }));
    } catch {
      toast.error(t('actions.toasts.load_failed'));
    }
  }, [t]);

  useEffect(() => { loadActions(); }, [loadActions]);
  useEffect(() => { if (tab === 'history') loadExecutions(); }, [tab, loadExecutions]);

  const providers = useMemo(() => [...new Set(actionsList.map((a) => a.provider))], [actionsList]);

  const filtered = useMemo(() => actionsList
    .filter((a) => providerFilter === 'all' || a.provider === providerFilter)
    .filter((a) => riskFilter === 'all' || a.risk_level === riskFilter)
    .filter((a) => a.name.toLowerCase().includes(search.toLowerCase()) || a.action_id.includes(search.toLowerCase())),
  [actionsList, providerFilter, riskFilter, search]);

  const handleApprove = async (execution) => {
    try {
      await approveActionExecution(execution.execution_id);
      toast.success(t('actions.toasts.approved'));
      loadExecutions();
    } catch {
      toast.error(t('actions.toasts.failed'));
    }
  };

  const handleCancel = async (execution) => {
    try {
      await cancelActionExecution(execution.execution_id);
      toast.success(t('actions.toasts.cancelled'));
      loadExecutions();
    } catch {
      toast.error(t('actions.toasts.failed'));
    }
  };

  return (
    <div data-testid="actions-page" className="max-w-6xl mx-auto px-4 md:px-6 py-6 space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Zap size={22} className="text-[hsl(var(--primary))]" />
          {t('actions.title')}
        </h1>
        <p className="text-sm text-muted-foreground max-w-xl">{t('actions.subtitle')}</p>
      </header>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList data-testid="actions-tabs" className="grid w-full grid-cols-2 md:w-auto md:inline-grid">
          <TabsTrigger value="available" data-testid="tab-available-actions">{t('actions.tab_available')}</TabsTrigger>
          <TabsTrigger value="history" data-testid="tab-execution-history">{t('actions.tab_history')}</TabsTrigger>
        </TabsList>

        <TabsContent value="available" className="space-y-4 mt-5">
          <div className="flex flex-col md:flex-row gap-2">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input data-testid="actions-search-input" placeholder={t('actions.search_placeholder')} value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 bg-[hsl(var(--background))]" />
            </div>
            <Select value={providerFilter} onValueChange={setProviderFilter}>
              <SelectTrigger data-testid="actions-provider-filter" className="w-full md:w-48 bg-[hsl(var(--background))]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('actions.all_providers')}</SelectItem>
                {providers.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={riskFilter} onValueChange={setRiskFilter}>
              <SelectTrigger data-testid="actions-risk-filter" className="w-full md:w-48 bg-[hsl(var(--background))]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('actions.all_risks')}</SelectItem>
                {['low', 'medium', 'high', 'critical'].map((r) => <SelectItem key={r} value={r}>{t(`actions.risk.${r}`)}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>

          {loading ? (
            <p className="text-xs text-muted-foreground">{t('common.loading') || 'Loading…'}</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3" data-testid="actions-grid">
              {filtered.map((a) => <ActionCard key={a.action_id} action={a} onExecute={setExecuteTarget} t={t} />)}
            </div>
          )}
        </TabsContent>

        <TabsContent value="history" className="space-y-4 mt-5">
          <div className="flex justify-end">
            <Button variant="outline" size="sm" onClick={loadExecutions} data-testid="refresh-executions-button">
              <RefreshCw size={13} className="mr-2" />Refresh
            </Button>
          </div>
          <Card className="bg-[hsl(var(--card))] border-[hsl(var(--border))] overflow-x-auto">
            <Table data-testid="executions-table">
              <TableHeader>
                <TableRow>
                  <TableHead>{t('actions.history.col_status')}</TableHead>
                  <TableHead>{t('actions.history.col_action')}</TableHead>
                  <TableHead>{t('actions.history.col_provider')}</TableHead>
                  <TableHead>{t('actions.history.col_source')}</TableHead>
                  <TableHead>{t('actions.history.col_time')}</TableHead>
                  <TableHead>{t('actions.history.col_result')}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {executions.length === 0 ? (
                  <TableRow><TableCell colSpan={7} className="text-center text-xs text-muted-foreground py-8">{t('actions.history.empty')}</TableCell></TableRow>
                ) : executions.map((e) => (
                  <ExecutionRow key={e.execution_id} execution={e} onApprove={handleApprove} onCancel={handleCancel} t={t} />
                ))}
              </TableBody>
            </Table>
          </Card>
        </TabsContent>
      </Tabs>

      <ExecuteActionModal
        action={executeTarget}
        open={!!executeTarget}
        onClose={() => setExecuteTarget(null)}
        onExecuted={() => { loadActions(); if (tab === 'history') loadExecutions(); }}
        t={t}
      />
    </div>
  );
}
