import React, { useCallback, useEffect, useMemo, useState } from 'react';
import LearnLink from '../components/LearnLink';
import { toast } from 'sonner';
import {
  Bot, Plus, Edit3, Trash2, AlertTriangle, Sparkles, ShieldAlert,
} from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useLanguage } from '../context/LanguageContext';
import {
  getPolicies, createPolicy, updatePolicy, deletePolicy,
  getEscalationRules, createEscalationRule, updateEscalationRule, deleteEscalationRule,
} from '../lib/api';

/**
 * AutomationPolicies — interactive command center (Phase 7a UX upgrade).
 *
 * Two tabs:
 *   1. Intent Policies — user defines how AI should act per intent (auto_execute,
 *      require_approval, suggest_only) with a confidence threshold + daily limit.
 *   2. Escalation Rules — conditions that override policies and hand off to humans.
 *
 * Full CRUD via /api/policies + /api/escalation-rules (workspace-scoped).
 */

// ──────────────────────────────────────────────────────────────────────
// Domain catalogs (labels come from i18n at render time)
// ──────────────────────────────────────────────────────────────────────
const INTENT_OPTIONS = [
  { value: 'new_lead', key: 'intent_new_lead' },
  { value: 'inbound_message', key: 'intent_inbound_msg' },
  { value: 'follow_up', key: 'intent_follow_up' },
  { value: 'scheduling', key: 'intent_schedule' },
  { value: 'crm_update', key: 'intent_crm_update' },
  { value: 'content_generation', key: 'intent_content_gen' },
  { value: 'onboarding_task', key: 'intent_onboarding' },
  { value: 'human_escalation', key: 'intent_human_escalation' },
];

const MODE_OPTIONS = [
  { value: 'auto_execute', key: 'mode_auto_execute', tone: 'success' },
  { value: 'require_approval', key: 'mode_require_approval', tone: 'warning' },
  { value: 'suggest_only', key: 'mode_suggest_only', tone: 'info' },
];

const CONDITION_OPTIONS = [
  { value: 'low_confidence', key: 'cond_low_confidence' },
  { value: 'vip_user', key: 'cond_vip_user' },
  { value: 'complaint_detected', key: 'cond_complaint' },
  { value: 'missing_data', key: 'cond_missing_data' },
  { value: 'integration_failure', key: 'cond_integration_fail' },
];

const ACTION_OPTIONS = [
  { value: 'send_to_human', key: 'action_send_human' },
  { value: 'request_confirmation', key: 'action_confirm' },
  { value: 'retry', key: 'action_retry' },
  { value: 'hold_for_review', key: 'action_hold_review' },
];

const modeBadgeClass = (tone) => {
  switch (tone) {
    case 'success': return 'bg-[hsl(var(--success)/0.14)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.3)]';
    case 'warning': return 'bg-[hsl(var(--warning)/0.14)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.3)]';
    case 'info':    return 'bg-[hsl(var(--info)/0.14)] text-[hsl(var(--info))] border-[hsl(var(--info)/0.3)]';
    default:        return 'bg-[hsl(var(--surface-2))] text-muted-foreground border-[hsl(var(--border))]';
  }
};

// Policies returned by the API use legacy fields (`intent`, `high_action`, etc.).
// This helper normalizes them into the UI-friendly shape the form uses.
const normalizePolicy = (p) => ({
  id: p.policy_id,
  name: p.name || p.intent || 'Policy',
  intent: p.intent || 'inbound_message',
  mode: p.high_action || 'require_approval',
  confidenceThreshold: Math.round((p.confidence_threshold_high ?? 0.85) * 100),
  dailyLimit: p.daily_limit ?? null,
  active: p.enabled !== false,
  raw: p,
});

const normalizeRule = (r) => ({
  id: r.rule_id,
  name: r.name,
  condition: r.condition_type || 'low_confidence',
  action: r.route_to || 'send_to_human',
  threshold: r.condition_value || '',
  active: r.enabled !== false,
  raw: r,
});

// ──────────────────────────────────────────────────────────────────────
// Page
// ──────────────────────────────────────────────────────────────────────
export default function AutomationPolicies() {
  const { t } = useLanguage();
  const [tab, setTab] = useState('policies');
  const [policies, setPolicies] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [policyDialog, setPolicyDialog] = useState({ open: false, editing: null });
  const [ruleDialog, setRuleDialog] = useState({ open: false, editing: null });
  const [deleteTarget, setDeleteTarget] = useState(null); // {type: 'policy'|'rule', id, name}

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, r] = await Promise.all([getPolicies(), getEscalationRules()]);
      setPolicies((p || []).map(normalizePolicy));
      setRules((r || []).map(normalizeRule));
    } catch (err) {
      console.error('Load automation:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ─── Policy handlers ────────────────────────────────────────────────
  const savePolicy = async (form) => {
    const payload = {
      name: form.name,
      intent: form.intent,
      action: form.mode,
      confidence_threshold_high: form.confidenceThreshold / 100,
      confidence_threshold_medium: Math.max(0.4, (form.confidenceThreshold / 100) - 0.3),
      high_action: form.mode,
      medium_action: form.mode === 'auto_execute' ? 'require_approval' : form.mode,
      low_action: 'escalate',
      enabled: form.active,
      daily_limit: form.dailyLimit || null,
    };
    try {
      if (form.id) {
        await updatePolicy(form.id, payload);
      } else {
        await createPolicy(payload);
      }
      toast.success(t('automation_policies.saved_toast'));
      setPolicyDialog({ open: false, editing: null });
      load();
    } catch (err) {
      toast.error(t('automation_policies.save_failed'));
    }
  };

  const togglePolicy = async (policy) => {
    const next = !policy.active;
    setPolicies((prev) => prev.map((p) => (p.id === policy.id ? { ...p, active: next } : p)));
    try {
      await updatePolicy(policy.id, { ...policy.raw, enabled: next });
    } catch (err) {
      toast.error(t('automation_policies.save_failed'));
      setPolicies((prev) => prev.map((p) => (p.id === policy.id ? { ...p, active: !next } : p)));
    }
  };

  // ─── Rule handlers ──────────────────────────────────────────────────
  const saveRule = async (form) => {
    const payload = {
      name: form.name,
      condition_type: form.condition,
      condition_value: form.threshold || '',
      route_to: form.action,
      priority: 'normal',
      enabled: form.active,
    };
    try {
      if (form.id) {
        await updateEscalationRule(form.id, payload);
      } else {
        await createEscalationRule(payload);
      }
      toast.success(t('automation_policies.saved_toast'));
      setRuleDialog({ open: false, editing: null });
      load();
    } catch (err) {
      toast.error(t('automation_policies.save_failed'));
    }
  };

  const toggleRule = async (rule) => {
    const next = !rule.active;
    setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, active: next } : r)));
    try {
      await updateEscalationRule(rule.id, { ...rule.raw, enabled: next });
    } catch (err) {
      toast.error(t('automation_policies.save_failed'));
      setRules((prev) => prev.map((r) => (r.id === rule.id ? { ...r, active: !next } : r)));
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      if (deleteTarget.type === 'policy') {
        await deletePolicy(deleteTarget.id);
      } else {
        await deleteEscalationRule(deleteTarget.id);
      }
      toast.success(t('automation_policies.deleted_toast'));
      setDeleteTarget(null);
      load();
    } catch (err) {
      toast.error(t('automation_policies.save_failed'));
    }
  };

  return (
    <div data-testid="automation-policies-page" className="max-w-6xl mx-auto px-4 md:px-6 py-6 space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
            <Bot size={22} className="text-[hsl(var(--primary))]" />
            {t('automation_policies.page_title')}
            <LearnLink route="automation" className="ml-1" />
          </h1>
          <p className="text-sm text-muted-foreground max-w-xl">
            {t('automation_policies.page_subtitle')}
          </p>
        </div>
      </header>

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <TabsList data-testid="automation-tabs" className="grid w-full grid-cols-2 md:w-auto md:inline-grid">
          <TabsTrigger value="policies" data-testid="tab-policies">
            <Sparkles size={14} className="mr-2" />
            {t('automation_policies.tab_policies')}
          </TabsTrigger>
          <TabsTrigger value="rules" data-testid="tab-rules">
            <ShieldAlert size={14} className="mr-2" />
            {t('automation_policies.tab_rules')}
          </TabsTrigger>
        </TabsList>

        {/* ─── Intent Policies tab ─────────────────────────── */}
        <TabsContent value="policies" className="space-y-4 mt-5">
          <div className="flex justify-end">
            <Button
              data-testid="new-policy-btn"
              onClick={() => setPolicyDialog({ open: true, editing: null })}
              className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
            >
              <Plus size={14} className="mr-1.5" />
              {t('automation_policies.new_policy')}
            </Button>
          </div>

          {loading ? (
            <ListSkeleton />
          ) : policies.length === 0 ? (
            <EmptyState
              testId="empty-policies"
              title={t('automation_policies.empty_policies_title')}
              desc={t('automation_policies.empty_policies_desc')}
              actionLabel={t('automation_policies.new_policy')}
              onAction={() => setPolicyDialog({ open: true, editing: null })}
            />
          ) : (
            <div className="space-y-2" data-testid="policy-list">
              {policies.map((p) => (
                <PolicyRow
                  key={p.id}
                  policy={p}
                  t={t}
                  onEdit={() => setPolicyDialog({ open: true, editing: p })}
                  onDelete={() => setDeleteTarget({ type: 'policy', id: p.id, name: p.name })}
                  onToggle={() => togglePolicy(p)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ─── Escalation Rules tab ────────────────────────── */}
        <TabsContent value="rules" className="space-y-4 mt-5">
          <div className="flex justify-end">
            <Button
              data-testid="new-rule-btn"
              onClick={() => setRuleDialog({ open: true, editing: null })}
              className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
            >
              <Plus size={14} className="mr-1.5" />
              {t('automation_policies.new_rule')}
            </Button>
          </div>

          {loading ? (
            <ListSkeleton />
          ) : rules.length === 0 ? (
            <EmptyState
              testId="empty-rules"
              title={t('automation_policies.empty_rules_title')}
              desc={t('automation_policies.empty_rules_desc')}
              actionLabel={t('automation_policies.new_rule')}
              onAction={() => setRuleDialog({ open: true, editing: null })}
            />
          ) : (
            <div className="space-y-2" data-testid="rule-list">
              {rules.map((r) => (
                <RuleRow
                  key={r.id}
                  rule={r}
                  t={t}
                  onEdit={() => setRuleDialog({ open: true, editing: r })}
                  onDelete={() => setDeleteTarget({ type: 'rule', id: r.id, name: r.name })}
                  onToggle={() => toggleRule(r)}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* ─── Policy dialog ──────────────────────────────────── */}
      <PolicyDialog
        t={t}
        state={policyDialog}
        onClose={() => setPolicyDialog({ open: false, editing: null })}
        onSave={savePolicy}
      />

      {/* ─── Rule dialog ────────────────────────────────────── */}
      <RuleDialog
        t={t}
        state={ruleDialog}
        onClose={() => setRuleDialog({ open: false, editing: null })}
        onSave={saveRule}
      />

      {/* ─── Delete confirmation ────────────────────────────── */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(o) => !o && setDeleteTarget(null)}>
        <AlertDialogContent data-testid="delete-confirm-dialog">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('automation_policies.confirm_delete_title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('automation_policies.confirm_delete_desc')}
              {deleteTarget?.name && <div className="mt-2 text-xs font-medium text-foreground">{deleteTarget.name}</div>}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel data-testid="delete-cancel-btn">{t('automation_policies.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              data-testid="delete-confirm-btn"
              onClick={confirmDelete}
              className="bg-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.9)] text-[hsl(var(--destructive-foreground))]"
            >
              {t('automation_policies.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Row components
// ──────────────────────────────────────────────────────────────────────
function PolicyRow({ policy, t, onEdit, onDelete, onToggle }) {
  const mode = MODE_OPTIONS.find((m) => m.value === policy.mode);
  const intentLabel = INTENT_OPTIONS.find((i) => i.value === policy.intent);
  return (
    <Card data-testid={`policy-row-${policy.id}`} className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))] transition-colors">
      <CardContent className="p-4 flex flex-col md:flex-row md:items-center gap-4">
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-foreground truncate">{policy.name}</span>
            <Badge className={`border text-[10px] uppercase tracking-wide ${modeBadgeClass(mode?.tone)}`}>
              {mode ? t(`automation_policies.${mode.key}`) : policy.mode}
            </Badge>
            {!policy.active && (
              <Badge variant="outline" className="text-[10px] text-muted-foreground">
                {t('automation_policies.inactive')}
              </Badge>
            )}
          </div>
          <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>
              <span className="opacity-70">{t('automation_policies.policy_intent')}:</span>{' '}
              <span className="text-foreground">{intentLabel ? t(`automation_policies.${intentLabel.key}`) : policy.intent}</span>
            </span>
            <span>
              <span className="opacity-70">{t('automation_policies.policy_confidence')}:</span>{' '}
              <span className="text-foreground tabular-nums">{policy.confidenceThreshold}%</span>
            </span>
            {policy.dailyLimit != null && (
              <span>
                <span className="opacity-70">{t('automation_policies.policy_daily_limit')}:</span>{' '}
                <span className="text-foreground tabular-nums">{policy.dailyLimit}</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Switch
            data-testid={`policy-toggle-${policy.id}`}
            checked={policy.active}
            onCheckedChange={onToggle}
          />
          <Button data-testid={`policy-edit-${policy.id}`} variant="outline" size="sm" onClick={onEdit}>
            <Edit3 size={14} className="mr-1.5" />
            {t('automation_policies.edit')}
          </Button>
          <Button
            data-testid={`policy-delete-${policy.id}`}
            variant="ghost"
            size="sm"
            onClick={onDelete}
            className="text-[hsl(var(--destructive))] hover:text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.08)]"
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function RuleRow({ rule, t, onEdit, onDelete, onToggle }) {
  const condition = CONDITION_OPTIONS.find((c) => c.value === rule.condition);
  const action = ACTION_OPTIONS.find((a) => a.value === rule.action);
  return (
    <Card data-testid={`rule-row-${rule.id}`} className="bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] hover:border-[hsl(var(--border-strong))] transition-colors">
      <CardContent className="p-4 flex flex-col md:flex-row md:items-center gap-4">
        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <AlertTriangle size={14} className="text-[hsl(var(--warning))]" />
            <span className="font-medium text-foreground truncate">{rule.name}</span>
            {!rule.active && (
              <Badge variant="outline" className="text-[10px] text-muted-foreground">
                {t('automation_policies.inactive')}
              </Badge>
            )}
          </div>
          <div className="text-xs text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1">
            <span>
              <span className="opacity-70">{t('automation_policies.rule_condition')}:</span>{' '}
              <span className="text-foreground">{condition ? t(`automation_policies.${condition.key}`) : rule.condition}</span>
            </span>
            <span>
              <span className="opacity-70">{t('automation_policies.rule_action')}:</span>{' '}
              <span className="text-foreground">{action ? t(`automation_policies.${action.key}`) : rule.action}</span>
            </span>
            {rule.threshold && (
              <span>
                <span className="opacity-70">{t('automation_policies.rule_threshold')}:</span>{' '}
                <span className="text-foreground tabular-nums">{rule.threshold}</span>
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Switch
            data-testid={`rule-toggle-${rule.id}`}
            checked={rule.active}
            onCheckedChange={onToggle}
          />
          <Button data-testid={`rule-edit-${rule.id}`} variant="outline" size="sm" onClick={onEdit}>
            <Edit3 size={14} className="mr-1.5" />
            {t('automation_policies.edit')}
          </Button>
          <Button
            data-testid={`rule-delete-${rule.id}`}
            variant="ghost"
            size="sm"
            onClick={onDelete}
            className="text-[hsl(var(--destructive))] hover:text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.08)]"
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Dialogs (create/edit forms)
// ──────────────────────────────────────────────────────────────────────
function PolicyDialog({ state, onClose, onSave, t }) {
  const editing = state.editing;
  const [form, setForm] = useState(() => defaultPolicyForm(editing));
  useEffect(() => { if (state.open) setForm(defaultPolicyForm(editing)); }, [state.open, editing]);

  const canSave = form.name?.trim().length > 0 && form.intent && form.mode;

  return (
    <Dialog open={state.open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="policy-dialog" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t('automation_policies.edit') : t('automation_policies.new_policy')}</DialogTitle>
          <DialogDescription className="text-xs">
            {t('automation_policies.page_subtitle')}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="policy-name">{t('automation_policies.policy_name')}</Label>
            <Input
              id="policy-name"
              data-testid="policy-form-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Auto-confirm new bookings"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>{t('automation_policies.policy_intent')}</Label>
              <Select value={form.intent} onValueChange={(v) => setForm({ ...form, intent: v })}>
                <SelectTrigger data-testid="policy-form-intent"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {INTENT_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{t(`automation_policies.${o.key}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>{t('automation_policies.policy_mode')}</Label>
              <Select value={form.mode} onValueChange={(v) => setForm({ ...form, mode: v })}>
                <SelectTrigger data-testid="policy-form-mode"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {MODE_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{t(`automation_policies.${o.key}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>{t('automation_policies.policy_confidence')} ({form.confidenceThreshold}%)</Label>
              <Input
                type="range"
                min={50} max={100} step={5}
                value={form.confidenceThreshold}
                onChange={(e) => setForm({ ...form, confidenceThreshold: Number(e.target.value) })}
                data-testid="policy-form-confidence"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="policy-limit">{t('automation_policies.policy_daily_limit')}</Label>
              <Input
                id="policy-limit"
                data-testid="policy-form-daily-limit"
                type="number"
                min={0}
                value={form.dailyLimit ?? ''}
                onChange={(e) => setForm({ ...form, dailyLimit: e.target.value === '' ? null : Number(e.target.value) })}
                placeholder="—"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Switch
              data-testid="policy-form-active"
              checked={form.active}
              onCheckedChange={(v) => setForm({ ...form, active: v })}
            />
            <Label className="cursor-pointer" onClick={() => setForm({ ...form, active: !form.active })}>
              {form.active ? t('automation_policies.active') : t('automation_policies.inactive')}
            </Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} data-testid="policy-form-cancel">
            {t('automation_policies.cancel')}
          </Button>
          <Button
            disabled={!canSave}
            onClick={() => onSave(form)}
            data-testid="policy-form-save"
            className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
          >
            {t('automation_policies.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RuleDialog({ state, onClose, onSave, t }) {
  const editing = state.editing;
  const [form, setForm] = useState(() => defaultRuleForm(editing));
  useEffect(() => { if (state.open) setForm(defaultRuleForm(editing)); }, [state.open, editing]);

  const canSave = form.name?.trim().length > 0 && form.condition && form.action;

  return (
    <Dialog open={state.open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent data-testid="rule-dialog" className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? t('automation_policies.edit') : t('automation_policies.new_rule')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 pt-2">
          <div className="space-y-1.5">
            <Label htmlFor="rule-name">{t('automation_policies.rule_name')}</Label>
            <Input
              id="rule-name"
              data-testid="rule-form-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Route VIPs to Sales"
            />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label>{t('automation_policies.rule_condition')}</Label>
              <Select value={form.condition} onValueChange={(v) => setForm({ ...form, condition: v })}>
                <SelectTrigger data-testid="rule-form-condition"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {CONDITION_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{t(`automation_policies.${o.key}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>{t('automation_policies.rule_action')}</Label>
              <Select value={form.action} onValueChange={(v) => setForm({ ...form, action: v })}>
                <SelectTrigger data-testid="rule-form-action"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ACTION_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value}>{t(`automation_policies.${o.key}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rule-threshold">{t('automation_policies.rule_threshold')}</Label>
            <Input
              id="rule-threshold"
              data-testid="rule-form-threshold"
              value={form.threshold}
              onChange={(e) => setForm({ ...form, threshold: e.target.value })}
              placeholder="—"
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch
              data-testid="rule-form-active"
              checked={form.active}
              onCheckedChange={(v) => setForm({ ...form, active: v })}
            />
            <Label className="cursor-pointer" onClick={() => setForm({ ...form, active: !form.active })}>
              {form.active ? t('automation_policies.active') : t('automation_policies.inactive')}
            </Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} data-testid="rule-form-cancel">
            {t('automation_policies.cancel')}
          </Button>
          <Button
            disabled={!canSave}
            onClick={() => onSave(form)}
            data-testid="rule-form-save"
            className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
          >
            {t('automation_policies.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function defaultPolicyForm(editing) {
  if (!editing) return { id: null, name: '', intent: 'inbound_message', mode: 'require_approval', confidenceThreshold: 85, dailyLimit: null, active: true };
  return {
    id: editing.id,
    name: editing.name,
    intent: editing.intent,
    mode: editing.mode,
    confidenceThreshold: editing.confidenceThreshold,
    dailyLimit: editing.dailyLimit,
    active: editing.active,
  };
}

function defaultRuleForm(editing) {
  if (!editing) return { id: null, name: '', condition: 'low_confidence', action: 'send_to_human', threshold: '', active: true };
  return {
    id: editing.id,
    name: editing.name,
    condition: editing.condition,
    action: editing.action,
    threshold: editing.threshold,
    active: editing.active,
  };
}

function ListSkeleton() {
  return (
    <div className="space-y-2">
      {[1, 2, 3].map((i) => <Skeleton key={i} className="h-20 rounded-xl" />)}
    </div>
  );
}

function EmptyState({ testId, title, desc, actionLabel, onAction }) {
  return (
    <Card data-testid={testId} className="bg-[hsl(var(--surface-1))] border-dashed border-[hsl(var(--border))]">
      <CardContent className="p-10 text-center space-y-4">
        <div className="mx-auto w-12 h-12 rounded-xl flex items-center justify-center bg-[hsl(var(--primary)/0.08)] text-[hsl(var(--primary))]">
          <Sparkles size={22} />
        </div>
        <div className="space-y-1">
          <h3 className="text-base font-semibold">{title}</h3>
          <p className="text-sm text-muted-foreground max-w-sm mx-auto">{desc}</p>
        </div>
        <Button
          onClick={onAction}
          className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
        >
          <Plus size={14} className="mr-1.5" />
          {actionLabel}
        </Button>
      </CardContent>
    </Card>
  );
}
