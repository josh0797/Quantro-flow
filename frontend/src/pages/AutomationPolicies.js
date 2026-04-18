import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Switch } from '../components/ui/switch';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '../components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Slider } from '../components/ui/slider';
import {
  Settings2, Zap, Shield, AlertTriangle, ArrowRight, Plus, Loader2,
  Trash2, Edit3, User, Calendar, Mail, Eye, SkipForward, CheckCircle2, ChevronRight
} from 'lucide-react';
import { motion } from 'framer-motion';
import { getPolicies, updatePolicy, getEscalationRules, createEscalationRule, updateEscalationRule, deleteEscalationRule } from '../lib/api';
import { toast } from 'sonner';

const intentLabels = {
  booking: { label: 'Booking Request', icon: Calendar, color: 'bg-[hsl(var(--info)/0.12)] text-[hsl(var(--info))]' },
  follow_up: { label: 'Follow-up', icon: ArrowRight, color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning))]' },
  onboarding: { label: 'Onboarding', icon: User, color: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))]' },
  inquiry: { label: 'General Inquiry', icon: Eye, color: 'bg-[hsl(var(--accent)/0.12)] text-[hsl(var(--accent))]' },
  escalation: { label: 'Escalation', icon: AlertTriangle, color: 'bg-[hsl(var(--critical)/0.12)] text-[hsl(var(--critical))]' },
  spam: { label: 'Spam', icon: SkipForward, color: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))]' },
  needs_review: { label: 'Needs Review', icon: Eye, color: 'bg-[hsl(var(--muted-foreground)/0.12)] text-[hsl(var(--muted-foreground))]' },
};

const actionLabels = {
  auto_run: { label: 'Auto-execute', color: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]', desc: 'System executes automatically' },
  require_approval: { label: 'Require Approval', color: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]', desc: 'Needs user approval before executing' },
  manual_review: { label: 'Manual Review', color: 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]', desc: 'Queued for manual review' },
  escalate: { label: 'Escalate', color: 'bg-[hsl(var(--critical)/0.15)] text-[hsl(var(--critical))]', desc: 'Routed to assigned person/team' },
};

const priorityColors = {
  normal: 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]',
  high: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]',
  critical: 'bg-[hsl(var(--critical)/0.15)] text-[hsl(var(--critical))]',
};

export default function AutomationPolicies() {
  const [policies, setPolicies] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(null);
  const [ruleDialogOpen, setRuleDialogOpen] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [ruleForm, setRuleForm] = useState({ name: '', condition_type: 'intent', condition_value: '', route_to: '', priority: 'normal', enabled: true });
  const [savingRule, setSavingRule] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [p, r] = await Promise.all([getPolicies(), getEscalationRules()]);
      setPolicies(p);
      setRules(r);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleUpdatePolicy = async (policy, field, value) => {
    setSaving(policy.policy_id);
    try {
      const updated = { ...policy, [field]: value };
      await updatePolicy(policy.policy_id, updated);
      setPolicies(prev => prev.map(p => p.policy_id === policy.policy_id ? { ...p, [field]: value } : p));
      toast.success('Policy updated');
    } catch (err) {
      toast.error('Failed to update policy');
    } finally {
      setSaving(null);
    }
  };

  const handleSaveRule = async () => {
    if (!ruleForm.name || !ruleForm.condition_value || !ruleForm.route_to) {
      toast.error('Please fill in all required fields');
      return;
    }
    setSavingRule(true);
    try {
      if (editingRule) {
        await updateEscalationRule(editingRule.rule_id, ruleForm);
        toast.success('Rule updated');
      } else {
        await createEscalationRule(ruleForm);
        toast.success('Rule created');
      }
      setRuleDialogOpen(false);
      setEditingRule(null);
      setRuleForm({ name: '', condition_type: 'intent', condition_value: '', route_to: '', priority: 'normal', enabled: true });
      fetchData();
    } catch (err) {
      toast.error('Failed to save rule');
    } finally {
      setSavingRule(false);
    }
  };

  const handleDeleteRule = async (ruleId) => {
    try {
      await deleteEscalationRule(ruleId);
      toast.success('Rule deleted');
      fetchData();
    } catch (err) {
      toast.error('Failed to delete rule');
    }
  };

  const openEditRule = (rule) => {
    setEditingRule(rule);
    setRuleForm({
      name: rule.name,
      condition_type: rule.condition_type,
      condition_value: rule.condition_value,
      route_to: rule.route_to,
      priority: rule.priority,
      enabled: rule.enabled,
    });
    setRuleDialogOpen(true);
  };

  if (loading) {
    return (
      <div className="page-container relative z-[1]">
        <Skeleton className="h-8 w-48 mb-6" />
        <div className="space-y-4">{[1,2,3].map(i => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>
      </div>
    );
  }

  return (
    <div className="page-container relative z-[1]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Automation Policies</h1>
          <p className="text-sm text-muted-foreground mt-1">Configure how the system handles different request types and escalations</p>
        </div>
      </div>

      <Tabs defaultValue="policies">
        <TabsList className="mb-6">
          <TabsTrigger value="policies" className="gap-1.5">
            <Zap size={14} /> Intent Policies
          </TabsTrigger>
          <TabsTrigger value="escalation" className="gap-1.5">
            <Shield size={14} /> Escalation Rules
          </TabsTrigger>
        </TabsList>

        {/* Intent Policies Tab */}
        <TabsContent value="policies">
          <div className="mb-6">
            <Card className="bg-[hsl(var(--primary)/0.04)] border-[hsl(var(--primary)/0.15)]">
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <Zap size={16} className="text-[hsl(var(--primary))] mt-0.5" />
                  <div>
                    <p className="text-sm font-medium">How automation policies work</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Each intent type has rules based on AI confidence level. High confidence messages can be auto-executed,
                      medium confidence requires your approval, and low confidence gets escalated to the right person.
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          <div data-testid="automation-policies-list" className="space-y-3">
            {policies.map((policy, i) => {
              const intentInfo = intentLabels[policy.intent] || { label: policy.intent, icon: Eye, color: '' };
              const IntentIcon = intentInfo.icon;
              return (
                <motion.div key={policy.policy_id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                  <Card data-testid="automation-policy-card" className="overflow-hidden">
                    <CardContent className="p-0">
                      <div className="flex items-center gap-4 p-5">
                        {/* Intent info */}
                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${intentInfo.color}`}>
                          <IntentIcon size={18} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-semibold">{intentInfo.label}</p>
                            <Switch
                              checked={policy.enabled}
                              onCheckedChange={(v) => handleUpdatePolicy(policy, 'enabled', v)}
                            />
                          </div>
                          <p className="text-xs text-muted-foreground mt-0.5">
                            Default: {actionLabels[policy.action]?.desc || policy.action}
                          </p>
                        </div>
                        {saving === policy.policy_id && <Loader2 size={14} className="animate-spin text-muted-foreground" />}
                      </div>

                      {/* Confidence-based rules */}
                      <div className="border-t border-[hsl(var(--border))] bg-[hsl(var(--surface-1))] px-5 py-4">
                        <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-3">Confidence-Based Actions</p>
                        <div className="grid grid-cols-3 gap-3">
                          {/* High confidence */}
                          <div className="p-3 rounded-lg bg-[hsl(var(--surface-2))] border border-[hsl(var(--border))]">
                            <div className="flex items-center gap-2 mb-2">
                              <div className="w-2 h-2 rounded-full bg-[hsl(var(--success))]" />
                              <span className="text-xs font-medium text-[hsl(var(--success))]">High ({(policy.confidence_threshold_high * 100).toFixed(0)}%+)</span>
                            </div>
                            <Select
                              value={policy.high_action}
                              onValueChange={(v) => handleUpdatePolicy(policy, 'high_action', v)}
                            >
                              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="auto_run">Auto-execute</SelectItem>
                                <SelectItem value="require_approval">Require approval</SelectItem>
                                <SelectItem value="manual_review">Manual review</SelectItem>
                                <SelectItem value="escalate">Escalate</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>

                          {/* Medium confidence */}
                          <div className="p-3 rounded-lg bg-[hsl(var(--surface-2))] border border-[hsl(var(--border))]">
                            <div className="flex items-center gap-2 mb-2">
                              <div className="w-2 h-2 rounded-full bg-[hsl(var(--warning))]" />
                              <span className="text-xs font-medium text-[hsl(var(--warning))]">Medium ({(policy.confidence_threshold_medium * 100).toFixed(0)}%+)</span>
                            </div>
                            <Select
                              value={policy.medium_action}
                              onValueChange={(v) => handleUpdatePolicy(policy, 'medium_action', v)}
                            >
                              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="auto_run">Auto-execute</SelectItem>
                                <SelectItem value="require_approval">Require approval</SelectItem>
                                <SelectItem value="manual_review">Manual review</SelectItem>
                                <SelectItem value="escalate">Escalate</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>

                          {/* Low confidence */}
                          <div className="p-3 rounded-lg bg-[hsl(var(--surface-2))] border border-[hsl(var(--border))]">
                            <div className="flex items-center gap-2 mb-2">
                              <div className="w-2 h-2 rounded-full bg-[hsl(var(--destructive))]" />
                              <span className="text-xs font-medium text-[hsl(var(--destructive))]">Low (&lt;{(policy.confidence_threshold_medium * 100).toFixed(0)}%)</span>
                            </div>
                            <Select
                              value={policy.low_action}
                              onValueChange={(v) => handleUpdatePolicy(policy, 'low_action', v)}
                            >
                              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="auto_run">Auto-execute</SelectItem>
                                <SelectItem value="require_approval">Require approval</SelectItem>
                                <SelectItem value="manual_review">Manual review</SelectItem>
                                <SelectItem value="escalate">Escalate</SelectItem>
                              </SelectContent>
                            </Select>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              );
            })}
          </div>
        </TabsContent>

        {/* Escalation Rules Tab */}
        <TabsContent value="escalation">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-sm text-muted-foreground">
                Define routing rules for escalated items. Rules are evaluated in order.
              </p>
            </div>
            <Dialog open={ruleDialogOpen} onOpenChange={(v) => { setRuleDialogOpen(v); if (!v) { setEditingRule(null); setRuleForm({ name: '', condition_type: 'intent', condition_value: '', route_to: '', priority: 'normal', enabled: true }); } }}>
              <DialogTrigger asChild>
                <Button data-testid="add-escalation-rule-button" size="sm">
                  <Plus size={14} className="mr-1" /> Add Rule
                </Button>
              </DialogTrigger>
              <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))]">
                <DialogHeader>
                  <DialogTitle>{editingRule ? 'Edit' : 'Add'} Escalation Rule</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div><Label>Rule Name *</Label><Input value={ruleForm.name} onChange={e => setRuleForm({...ruleForm, name: e.target.value})} placeholder="e.g. Urgent recruiting leads" /></div>
                  <div><Label>Condition Type</Label>
                    <Select value={ruleForm.condition_type} onValueChange={v => setRuleForm({...ruleForm, condition_type: v})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="intent">Intent Match</SelectItem>
                        <SelectItem value="keyword">Keyword Match</SelectItem>
                        <SelectItem value="confidence">Confidence Level</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label>Condition Value *</Label>
                    <Input
                      value={ruleForm.condition_value}
                      onChange={e => setRuleForm({...ruleForm, condition_value: e.target.value})}
                      placeholder={ruleForm.condition_type === 'intent' ? 'e.g. onboarding' : ruleForm.condition_type === 'keyword' ? 'e.g. urgent,conflict,cancel' : 'e.g. low'}
                    />
                    <p className="text-[10px] text-muted-foreground mt-1">
                      {ruleForm.condition_type === 'keyword' ? 'Comma-separated keywords to match in message' : ruleForm.condition_type === 'intent' ? 'Intent type to match' : 'Confidence level: low, medium, high'}
                    </p>
                  </div>
                  <div><Label>Route To *</Label><Input value={ruleForm.route_to} onChange={e => setRuleForm({...ruleForm, route_to: e.target.value})} placeholder="Person name or team" /></div>
                  <div><Label>Priority</Label>
                    <Select value={ruleForm.priority} onValueChange={v => setRuleForm({...ruleForm, priority: v})}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="normal">Normal</SelectItem>
                        <SelectItem value="high">High</SelectItem>
                        <SelectItem value="critical">Critical</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <DialogFooter>
                  <Button variant="secondary" onClick={() => { setRuleDialogOpen(false); setEditingRule(null); }}>Cancel</Button>
                  <Button onClick={handleSaveRule} disabled={savingRule}>
                    {savingRule ? <Loader2 size={14} className="animate-spin mr-1" /> : <CheckCircle2 size={14} className="mr-1" />}
                    {editingRule ? 'Update' : 'Create'} Rule
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>

          <div data-testid="escalation-rules-list" className="space-y-2">
            {rules.length === 0 ? (
              <Card className="py-12">
                <CardContent className="text-center">
                  <Shield size={32} className="mx-auto text-muted-foreground mb-3" />
                  <p className="text-sm text-muted-foreground">No escalation rules defined yet</p>
                </CardContent>
              </Card>
            ) : (
              rules.map((rule, i) => (
                <motion.div key={rule.rule_id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                  <Card data-testid="escalation-rule-card" className="card-hover">
                    <CardContent className="p-4">
                      <div className="flex items-center gap-4">
                        <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${priorityColors[rule.priority] || ''}`}>
                          <AlertTriangle size={16} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-0.5">
                            <p className="text-sm font-medium">{rule.name}</p>
                            <Badge className={`text-[10px] ${priorityColors[rule.priority] || ''}`}>{rule.priority}</Badge>
                            {!rule.enabled && <Badge variant="secondary" className="text-[10px]">Disabled</Badge>}
                          </div>
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <span className="capitalize">{rule.condition_type}</span>
                            <span>=</span>
                            <span className="font-mono">{rule.condition_value}</span>
                            <ChevronRight size={12} />
                            <span className="font-medium text-foreground">{rule.route_to}</span>
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <Switch checked={rule.enabled} onCheckedChange={(v) => {
                            updateEscalationRule(rule.rule_id, { ...rule, enabled: v }).then(() => {
                              toast.success(v ? 'Rule enabled' : 'Rule disabled');
                              fetchData();
                            });
                          }} />
                          <Button variant="ghost" size="sm" onClick={() => openEditRule(rule)} className="h-8 w-8 p-0">
                            <Edit3 size={14} />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => handleDeleteRule(rule.rule_id)} className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive">
                            <Trash2 size={14} />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              ))
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
