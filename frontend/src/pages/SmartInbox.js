import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ScrollArea } from '../components/ui/scroll-area';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Checkbox } from '../components/ui/checkbox';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import {
  Mail, Zap, CheckCircle2, XCircle, Clock, Loader2, Sparkles, Shield,
  ArrowRight, ChevronRight, AlertTriangle, Eye, Play, CheckCheck, Edit3,
  SkipForward, User, Calendar, Phone, MapPin, FileText
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  getInbox, analyzeInboxItem, approveInboxAction, declineInboxAction,
  batchAnalyzeInbox, batchApproveInbox, updateInboxDetails, approveWithOverrides
} from '../lib/api';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { getEntityLabel } from '../config/industryConfig';
import { useLanguage } from '../context/LanguageContext';
import LiveEmptyState from '../components/LiveEmptyState';

// Human-friendly intent labels (no AI jargon)
const intentConfig = {
  booking: { label: 'Ready to schedule', icon: Calendar, color: 'bg-[hsl(var(--info)/0.12)] text-[hsl(var(--info))]', badgeClass: 'intent-booking' },
  onboarding: { label: 'New team member', icon: User, color: 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))]', badgeClass: 'intent-onboarding' },
  follow_up: { label: 'Needs follow-up', icon: ArrowRight, color: 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning))]', badgeClass: 'intent-follow_up' },
  inquiry: { label: 'New inquiry', icon: Eye, color: 'bg-[hsl(var(--accent)/0.12)] text-[hsl(var(--accent))]', badgeClass: 'intent-inquiry' },
  escalation: { label: 'Requires attention', icon: AlertTriangle, color: 'bg-[hsl(var(--critical)/0.12)] text-[hsl(var(--critical))]', badgeClass: 'intent-escalation' },
  spam: { label: 'Not relevant', icon: SkipForward, color: 'bg-[hsl(var(--destructive)/0.12)] text-[hsl(var(--destructive))]', badgeClass: 'intent-spam' },
  needs_review: { label: 'Needs your review', icon: Eye, color: 'bg-[hsl(var(--muted-foreground)/0.12)] text-[hsl(var(--muted-foreground))]', badgeClass: 'intent-needs_review' },
};

// Human-friendly action labels
const actionLabels = {
  schedule_meeting: 'Schedule a call',
  create_contact: 'Add to contacts',
  send_follow_up: 'Send follow-up',
  start_onboarding: 'Start onboarding',
  flag_review: 'Flag for review',
  ignore: 'No action needed',
  none: 'No action needed',
};

const statusConfig = {
  new: { label: 'New', color: 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]' },
  processing: { label: 'Processing', color: 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]' },
  processed: { label: 'Classified', color: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' },
  actioned: { label: 'Completed', color: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' },
  auto_actioned: { label: 'Auto-executed', color: 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]' },
  declined: { label: 'Skipped', color: 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]' },
};

const policyActionLabels = {
  auto_run: { label: 'Auto-execute', color: 'text-[hsl(var(--success))]', icon: '⚡' },
  require_approval: { label: 'Needs approval', color: 'text-[hsl(var(--warning))]', icon: '🔒' },
  manual_review: { label: 'Manual review', color: 'text-[hsl(var(--info))]', icon: '👁' },
  escalate: { label: 'Escalated', color: 'text-[hsl(var(--critical))]', icon: '🔺' },
};

function getConfidenceLabel(confidence) {
  if (confidence >= 0.85) return { label: 'High', color: 'text-[hsl(var(--success))]' };
  if (confidence >= 0.6) return { label: 'Medium', color: 'text-[hsl(var(--warning))]' };
  return { label: 'Low', color: 'text-[hsl(var(--destructive))]' };
}

export default function SmartInbox() {
  const { profile } = useBusinessProfile();
  const { t } = useLanguage();
  const industry = profile?.industry || 'other';
  const customLabels = profile?.entity_labels || {};
  
  const [items, setItems] = useState([]);
  const [selectedItem, setSelectedItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(null);
  const [approving, setApproving] = useState(false);
  const [batchProcessing, setBatchProcessing] = useState(false);
  const [batchApproving, setBatchApproving] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [filter, setFilter] = useState('all');
  const [view, setView] = useState('triage'); // 'triage' or 'review'
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  const fetchInbox = useCallback(async () => {
    try {
      const data = await getInbox(filter === 'all' ? null : filter);
      setItems(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  // Re-fetch whenever Simulation Mode flips so datasets stay coherent.
  useEffect(() => {
    setLoading(true);
    setSelectedItem(null);
    setSelectedIds(new Set());
    fetchInbox();
    const interval = setInterval(fetchInbox, 10000);
    return () => clearInterval(interval);
  }, [fetchInbox, profile?.simulation_mode]);

  // Selection helpers
  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    const eligible = items.filter(i => i.status === 'new' || i.status === 'processed');
    if (selectedIds.size === eligible.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(eligible.map(i => i.inbox_id)));
    }
  };

  const newItems = items.filter(i => i.status === 'new');
  const processedItems = items.filter(i => i.status === 'processed');
  const selectedNewIds = [...selectedIds].filter(id => items.find(i => i.inbox_id === id)?.status === 'new');
  const selectedProcessedIds = [...selectedIds].filter(id => items.find(i => i.inbox_id === id)?.status === 'processed');

  // Batch triage
  const handleBatchAnalyze = async () => {
    const idsToAnalyze = selectedNewIds.length > 0 ? selectedNewIds : newItems.map(i => i.inbox_id);
    if (idsToAnalyze.length === 0) {
      toast.info(t('smart_inbox.empty_state'));
      return;
    }
    setBatchProcessing(true);
    // Optimistically mark as processing
    setItems(prev => prev.map(item =>
      idsToAnalyze.includes(item.inbox_id) ? { ...item, status: 'processing' } : item
    ));
    try {
      const result = await batchAnalyzeInbox(idsToAnalyze);
      toast.success(t('smart_inbox.toasts.batch_done', { count: result.analyzed_count ?? result.items?.length ?? '' }), {
        description: `${result.classified} of ${result.total} messages classified`
      });
      setSelectedIds(new Set());
      fetchInbox();
    } catch (err) {
      toast.error(t('smart_inbox.toasts.batch_failed'), { description: err.message });
      fetchInbox();
    } finally {
      setBatchProcessing(false);
    }
  };

  // Batch approve
  const handleBatchApprove = async () => {
    const idsToApprove = selectedProcessedIds.length > 0 ? selectedProcessedIds : processedItems.map(i => i.inbox_id);
    if (idsToApprove.length === 0) {
      toast.info(t('smart_inbox.empty_state'));
      return;
    }
    setBatchApproving(true);
    try {
      const result = await batchApproveInbox(idsToApprove);
      toast.success(t('smart_inbox.toasts.batch_done', { count: result.approved_count ?? '' }), {
        description: `${result.actioned} of ${result.total} actions executed`
      });
      setSelectedIds(new Set());
      fetchInbox();
      setSelectedItem(null);
    } catch (err) {
      toast.error(t('smart_inbox.toasts.batch_failed'));
    } finally {
      setBatchApproving(false);
    }
  };

  // Single analyze
  const handleAnalyze = async (inboxId) => {
    setAnalyzing(inboxId);
    setItems(prev => prev.map(i => i.inbox_id === inboxId ? { ...i, status: 'processing' } : i));
    try {
      const result = await analyzeInboxItem(inboxId);
      setItems(prev => prev.map(i => i.inbox_id === inboxId ? result : i));
      if (selectedItem?.inbox_id === inboxId) setSelectedItem(result);
      toast.success(t('smart_inbox.toasts.analyzed'), { description: `${intentConfig[result.ai_intent?.intent]?.label || result.ai_intent?.intent}` });
    } catch (err) {
      toast.error(t('smart_inbox.toasts.analyze_failed'));
      fetchInbox();
    } finally {
      setAnalyzing(null);
    }
  };

  // Approve with overrides
  const handleApproveWithOverrides = async (inboxId, overrides = {}) => {
    setApproving(true);
    try {
      await approveWithOverrides(inboxId, overrides);
      toast.success(t('smart_inbox.toasts.marked_processed'), { description: t('smart_inbox.toasts.analyzed') });
      fetchInbox();
      setSelectedItem(null);
      setEditDialogOpen(false);
    } catch (err) {
      toast.error(t('smart_inbox.toasts.mark_failed'), { description: err.response?.data?.detail || err.message });
    } finally {
      setApproving(false);
    }
  };

  const handleDecline = async (inboxId) => {
    try {
      await declineInboxAction(inboxId);
      toast.info(t('smart_inbox.toasts.escalated'));
      fetchInbox();
      setSelectedItem(null);
    } catch (err) {
      toast.error(t('smart_inbox.toasts.mark_failed'));
    }
  };

  // Open edit dialog
  const openEditDialog = (item) => {
    const entities = item.ai_intent?.entities || {};
    const action = item.ai_suggested_action || {};
    setEditForm({
      person_name: entities.person_name || '',
      email: entities.email || item.from_email || '',
      phone: entities.phone || '',
      date_time: entities.date_time || '',
      property: entities.property || '',
      action_type: action.type || '',
      action_description: action.description || '',
      // For schedule overrides
      title: `Meeting - ${item.from_name}`,
      start_time: '',
      end_time: '',
      location: entities.property || '',
    });
    setEditDialogOpen(true);
  };

  // Save edits and approve
  const handleSaveAndApprove = async () => {
    if (!selectedItem) return;
    setSaving(true);
    try {
      // First update the entities
      await updateInboxDetails(selectedItem.inbox_id, {
        entities: {
          person_name: editForm.person_name || null,
          email: editForm.email || null,
          phone: editForm.phone || null,
          date_time: editForm.date_time || null,
          property: editForm.property || null,
        },
        suggested_action_type: editForm.action_type || undefined,
        suggested_action_description: editForm.action_description || undefined,
      });

      // Then approve with overrides
      const overrides = {};
      if (editForm.action_type === 'schedule_meeting') {
        if (editForm.title) overrides.title = editForm.title;
        if (editForm.start_time) overrides.start_time = editForm.start_time;
        if (editForm.end_time) overrides.end_time = editForm.end_time;
        if (editForm.location) overrides.location = editForm.location;
      }
      if (editForm.person_name) overrides.contact_name = editForm.person_name;
      if (editForm.email) overrides.contact_email = editForm.email;
      if (editForm.phone) overrides.contact_phone = editForm.phone;

      await handleApproveWithOverrides(selectedItem.inbox_id, overrides);
    } catch (err) {
      toast.error(t('smart_inbox.toasts.mark_failed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-container relative z-[1]">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{t('smart_inbox.title')}</h1>
          <p className="text-sm text-muted-foreground mt-1">Intelligent message processing and workflow automation</p>
        </div>
        <div className="flex items-center gap-3">
          {newItems.length > 0 && (
            <Badge className="bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]">
              {newItems.length} new
            </Badge>
          )}
          {processedItems.length > 0 && (
            <Badge className="bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]">
              {processedItems.length} ready for action
            </Badge>
          )}
        </div>
      </div>

      {/* View Tabs + Batch Actions */}
      <div className="flex items-center justify-between mb-4">
        <Tabs value={view} onValueChange={setView}>
          <TabsList>
            <TabsTrigger value="triage" className="gap-1.5">
              <Zap size={14} /> Triage
            </TabsTrigger>
            <TabsTrigger value="review" className="gap-1.5">
              <Shield size={14} /> Review & Control
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="flex items-center gap-2">
          {view === 'triage' && (
            <>
              <Button
                data-testid="batch-analyze-button"
                variant="secondary"
                size="sm"
                onClick={handleBatchAnalyze}
                disabled={batchProcessing || newItems.length === 0}
              >
                {batchProcessing ? (
                  <><Loader2 size={14} className="animate-spin mr-1.5" /> Processing...</>
                ) : (
                  <><Play size={14} className="mr-1.5" /> Process {selectedNewIds.length > 0 ? `${selectedNewIds.length} Selected` : `All New (${newItems.length})`}</>
                )}
              </Button>
              <Button
                data-testid="batch-approve-button"
                size="sm"
                onClick={handleBatchApprove}
                disabled={batchApproving || processedItems.length === 0}
                className="bg-[hsl(var(--success))] hover:bg-[hsl(var(--success)/0.9)] text-white"
              >
                {batchApproving ? (
                  <><Loader2 size={14} className="animate-spin mr-1.5" /> Approving...</>
                ) : (
                  <><CheckCheck size={14} className="mr-1.5" /> Approve {selectedProcessedIds.length > 0 ? `${selectedProcessedIds.length} Selected` : `All (${processedItems.length})`}</>
                )}
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Filter Bar */}
      <div data-testid="smart-inbox-filter" className="flex items-center gap-2 mb-4">
        <div className="flex items-center gap-2 mr-4">
          <Checkbox
            checked={selectedIds.size > 0 && selectedIds.size === items.filter(i => i.status === 'new' || i.status === 'processed').length}
            onCheckedChange={selectAll}
          />
          <span className="text-xs text-muted-foreground">Select all</span>
        </div>
        {['all', 'new', 'processed', 'actioned', 'declined'].map(f => (
          <Button
            key={f}
            variant={filter === f ? 'default' : 'secondary'}
            size="sm"
            className="text-xs capitalize"
            onClick={() => { setFilter(f); setLoading(true); setSelectedIds(new Set()); }}
          >
            {f === 'processed' ? 'Classified' : f === 'actioned' ? 'Completed' : f === 'declined' ? 'Skipped' : f}
          </Button>
        ))}
      </div>

      {/* Main Layout */}
      {view === 'triage' ? (
        <TriageView
          items={items}
          loading={loading}
          selectedIds={selectedIds}
          toggleSelect={toggleSelect}
          selectedItem={selectedItem}
          setSelectedItem={setSelectedItem}
          analyzing={analyzing}
          handleAnalyze={handleAnalyze}
          batchProcessing={batchProcessing}
        />
      ) : (
        <ReviewView
          items={items}
          loading={loading}
          selectedItem={selectedItem}
          setSelectedItem={setSelectedItem}
          approving={approving}
          handleApproveWithOverrides={handleApproveWithOverrides}
          handleDecline={handleDecline}
          openEditDialog={openEditDialog}
        />
      )}

      {/* Edit Dialog (Manual Override) */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))] max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Edit3 size={18} className="text-[hsl(var(--primary))]" />
              Adjust Details Before Executing
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-6 py-4">
            {/* Contact Info */}
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Contact Information</h4>
              <div className="grid grid-cols-2 gap-4">
                <div><Label>Name</Label><Input value={editForm.person_name} onChange={e => setEditForm({...editForm, person_name: e.target.value})} /></div>
                <div><Label>Email</Label><Input value={editForm.email} onChange={e => setEditForm({...editForm, email: e.target.value})} /></div>
                <div><Label>Phone</Label><Input value={editForm.phone} onChange={e => setEditForm({...editForm, phone: e.target.value})} /></div>
                <div><Label>Property</Label><Input value={editForm.property} onChange={e => setEditForm({...editForm, property: e.target.value})} /></div>
              </div>
            </div>

            {/* Schedule Details (if applicable) */}
            {editForm.action_type === 'schedule_meeting' && (
              <div>
                <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Meeting Details</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div className="col-span-2"><Label>Title</Label><Input value={editForm.title} onChange={e => setEditForm({...editForm, title: e.target.value})} /></div>
                  <div><Label>Start Time</Label><Input type="datetime-local" value={editForm.start_time} onChange={e => setEditForm({...editForm, start_time: e.target.value})} /></div>
                  <div><Label>End Time</Label><Input type="datetime-local" value={editForm.end_time} onChange={e => setEditForm({...editForm, end_time: e.target.value})} /></div>
                  <div className="col-span-2"><Label>Location</Label><Input value={editForm.location} onChange={e => setEditForm({...editForm, location: e.target.value})} /></div>
                </div>
              </div>
            )}

            {/* Action */}
            <div>
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Proposed Action</h4>
              <div className="space-y-3">
                <div>
                  <Label>Action Type</Label>
                  <Select value={editForm.action_type} onValueChange={v => setEditForm({...editForm, action_type: v})}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="schedule_meeting">Schedule a call</SelectItem>
                      <SelectItem value="create_contact">Add to contacts</SelectItem>
                      <SelectItem value="send_follow_up">Send follow-up</SelectItem>
                      <SelectItem value="start_onboarding">Start onboarding</SelectItem>
                      <SelectItem value="flag_review">Flag for review</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Description</Label>
                  <Input value={editForm.action_description} onChange={e => setEditForm({...editForm, action_description: e.target.value})} />
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setEditDialogOpen(false)}>Cancel</Button>
            <Button onClick={handleSaveAndApprove} disabled={saving}>
              {saving ? <Loader2 size={14} className="animate-spin mr-1.5" /> : <CheckCircle2 size={14} className="mr-1.5" />}
              Save & Execute
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ─── Triage View ─────────────────────────────────────────────────────
function TriageView({ items, loading, selectedIds, toggleSelect, selectedItem, setSelectedItem, analyzing, handleAnalyze, batchProcessing }) {
  const { profile } = useBusinessProfile();
  const { t } = useLanguage();
  if (loading) {
    return (
      <div className="space-y-3">
        {[1,2,3,4].map(i => <Skeleton key={i} className="h-20 rounded-xl" />)}
      </div>
    );
  }

  if (items.length === 0) {
    // Live Mode with no real data → guide the user. Simulation Mode
    // fallback keeps the original "all caught up" empty card.
    if (!profile?.simulation_mode) {
      return <LiveEmptyState moduleKey="inbox" />;
    }
    return (
      <Card className="py-16">
        <CardContent className="text-center">
          <Mail size={40} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm text-muted-foreground">{t('smart_inbox.empty_state')}</p>
          <p className="text-xs text-muted-foreground mt-1">{t('smart_inbox.empty_hint')}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-2" data-testid="smart-inbox-list">
      <AnimatePresence>
        {items.map((item, i) => {
          const isSelected = selectedIds.has(item.inbox_id);
          const isProcessing = item.status === 'processing';
          const isClassified = item.status === 'processed';
          const isActioned = item.status === 'actioned';
          const intentInfo = item.ai_intent ? intentConfig[item.ai_intent.intent] : null;
          const confidence = item.ai_intent ? getConfidenceLabel(item.ai_intent.confidence) : null;
          const statusInfo = statusConfig[item.status] || statusConfig.new;

          return (
            <motion.div
              key={item.inbox_id}
              data-testid="smart-inbox-item"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.02 }}
            >
              <div
                className={`flex items-start gap-3 p-4 rounded-xl border transition-all duration-150 ${
                  selectedItem?.inbox_id === item.inbox_id
                    ? 'bg-[hsl(var(--surface-2))] border-[hsl(var(--ring)/0.3)]'
                    : 'bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] hover:bg-[hsl(var(--surface-2))]'
                }`}
              >
                <Checkbox
                  checked={isSelected}
                  onCheckedChange={() => toggleSelect(item.inbox_id)}
                  className="mt-1"
                  disabled={isActioned || item.status === 'declined'}
                />

                <div
                  className="flex-1 min-w-0 cursor-pointer"
                  onClick={() => setSelectedItem(item)}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2 min-w-0">
                      {!item.read && <div className="w-2 h-2 rounded-full bg-[hsl(var(--info))] shrink-0" />}
                      <p className="text-sm font-medium truncate">{item.from_name}</p>
                      <span className="text-[10px] font-mono text-muted-foreground">
                        {(() => { try { return format(parseISO(item.received_at), 'MMM d HH:mm'); } catch { return ''; } })()}
                      </span>
                    </div>
                    <Badge className={`text-[10px] px-2 ${statusInfo.color}`}>
                      {statusInfo.label}
                    </Badge>
                  </div>
                  <p className="text-sm truncate">{item.subject}</p>
                  <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">{item.body}</p>

                  {/* AI Classification Row */}
                  {isClassified && intentInfo && (
                    <div className="flex items-center gap-3 mt-2 pt-2 border-t border-[hsl(var(--border)/0.5)]">
                      <Badge className={`text-[10px] ${intentInfo.badgeClass}`}>
                        {intentInfo.label}
                      </Badge>
                      <span className={`text-[10px] font-medium ${confidence?.color}`}>
                        {confidence?.label} confidence
                      </span>
                      {item.ai_suggested_action && (
                        <span className="text-[10px] text-muted-foreground">
                          → {actionLabels[item.ai_suggested_action.type] || item.ai_suggested_action.type}
                        </span>
                      )}
                      {item.policy_action && (
                        <Badge className={`text-[9px] ml-auto ${
                          item.policy_action === 'auto_run' ? 'bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))]' :
                          item.policy_action === 'require_approval' ? 'bg-[hsl(var(--warning)/0.12)] text-[hsl(var(--warning))]' :
                          item.policy_action === 'escalate' ? 'bg-[hsl(var(--critical)/0.12)] text-[hsl(var(--critical))]' :
                          'bg-[hsl(var(--info)/0.12)] text-[hsl(var(--info))]'
                        }`}>
                          {policyActionLabels[item.policy_action]?.label || item.policy_action}
                        </Badge>
                      )}
                      {item.escalation && (
                        <span className="text-[10px] text-[hsl(var(--critical))]">
                          → {item.escalation.route_to}
                        </span>
                      )}
                      {item.auto_executed && (
                        <div className="flex items-center gap-1 text-[10px] text-[hsl(var(--primary))]">
                          <Zap size={10} />
                          <span>Auto-executed</span>
                        </div>
                      )}
                    </div>
                  )}

                  {isProcessing && (
                    <div className="flex items-center gap-2 mt-2 pt-2 border-t border-[hsl(var(--border)/0.5)]">
                      <Loader2 size={12} className="animate-spin text-[hsl(var(--primary))]" />
                      <span className="text-[10px] text-[hsl(var(--primary))]">System is classifying this message...</span>
                    </div>
                  )}
                </div>

                {/* Quick Actions */}
                <div className="flex items-center gap-1 shrink-0">
                  {item.status === 'new' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={(e) => { e.stopPropagation(); handleAnalyze(item.inbox_id); }}
                      disabled={analyzing === item.inbox_id}
                      className="h-7 text-xs"
                    >
                      {analyzing === item.inbox_id ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : (
                        <><Zap size={12} className="mr-1" /> Classify</>
                      )}
                    </Button>
                  )}
                </div>
              </div>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}

// ─── Review & Control View (Manual Override UI) ──────────────────────
function ReviewView({ items, loading, selectedItem, setSelectedItem, approving, handleApproveWithOverrides, handleDecline, openEditDialog }) {
  // Only show items that have been classified or need action
  const reviewableItems = items.filter(i => i.status === 'processed' || i.status === 'new');

  if (loading) {
    return (
      <div className="grid lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2"><Skeleton className="h-[600px] rounded-xl" /></div>
        <div className="lg:col-span-3"><Skeleton className="h-[600px] rounded-xl" /></div>
      </div>
    );
  }

  return (
    <div className="grid lg:grid-cols-5 gap-6">
      {/* Left: Request List */}
      <div className="lg:col-span-2">
        <ScrollArea className="h-[calc(100vh-260px)]">
          {reviewableItems.length === 0 ? (
            <Card className="py-12">
              <CardContent className="text-center">
                <CheckCircle2 size={32} className="mx-auto text-[hsl(var(--success))] mb-3" />
                <p className="text-sm text-muted-foreground">All requests have been handled. The system is monitoring.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-2">
              {reviewableItems.map((item, i) => {
                const intentInfo = item.ai_intent ? intentConfig[item.ai_intent.intent] : null;
                const confidence = item.ai_intent ? getConfidenceLabel(item.ai_intent.confidence) : null;
                const IntentIcon = intentInfo?.icon || Mail;

                return (
                  <motion.div
                    key={item.inbox_id}
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                  >
                    <div
                      className={`p-4 rounded-xl border cursor-pointer transition-all duration-150 ${
                        selectedItem?.inbox_id === item.inbox_id
                          ? 'bg-[hsl(var(--surface-2))] border-[hsl(var(--ring)/0.3)]'
                          : 'bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] hover:bg-[hsl(var(--surface-2))]'
                      }`}
                      onClick={() => setSelectedItem(item)}
                    >
                      <div className="flex items-start gap-3">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${intentInfo?.color || 'bg-[hsl(var(--surface-2))]'}`}>
                          <IntentIcon size={14} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between mb-0.5">
                            <p className="text-sm font-medium truncate">{item.from_name}</p>
                            {confidence && (
                              <span className={`text-[10px] font-medium ${confidence.color}`}>{confidence.label}</span>
                            )}
                          </div>
                          <p className="text-xs truncate">{item.subject}</p>
                          {intentInfo && (
                            <p className="text-[10px] text-muted-foreground mt-1">{intentInfo.label}</p>
                          )}
                        </div>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </ScrollArea>
      </div>

      {/* Right: Review Detail Panel */}
      <div className="lg:col-span-3">
        {selectedItem ? (
          <ReviewDetailPanel
            item={selectedItem}
            approving={approving}
            handleApproveWithOverrides={handleApproveWithOverrides}
            handleDecline={handleDecline}
            openEditDialog={openEditDialog}
          />
        ) : (
          <Card className="h-full flex items-center justify-center min-h-[400px]">
            <CardContent className="text-center">
              <Shield size={40} className="mx-auto text-muted-foreground mb-3" />
              <p className="text-sm font-medium text-foreground mb-1">Review & Control Center</p>
              <p className="text-xs text-muted-foreground max-w-[240px]">Select a request to review the system's analysis, adjust details, and approve or skip actions.</p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

// ─── Review Detail Panel ─────────────────────────────────────────────
function ReviewDetailPanel({ item, approving, handleApproveWithOverrides, handleDecline, openEditDialog }) {
  const intentInfo = item.ai_intent ? intentConfig[item.ai_intent.intent] : null;
  const confidence = item.ai_intent ? getConfidenceLabel(item.ai_intent.confidence) : null;
  const entities = item.ai_intent?.entities || {};
  const action = item.ai_suggested_action || {};

  return (
    <Card data-testid="smart-inbox-detail" className="overflow-hidden">
      {/* Three-section layout */}
      <div className="grid grid-rows-[auto_1fr_auto]">
        {/* Section 1: Original Request */}
        <div className="p-5 border-b border-[hsl(var(--border))]">
          <div className="flex items-center gap-2 mb-3">
            <Mail size={14} className="text-muted-foreground" />
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Original Request</span>
          </div>
          <div className="flex items-start justify-between mb-2">
            <div>
              <p className="text-base font-medium">{item.subject}</p>
              <p className="text-sm text-muted-foreground mt-0.5">
                From {item.from_name} ({item.from_email})
              </p>
            </div>
            <span className="text-[10px] font-mono text-muted-foreground">
              {(() => { try { return format(parseISO(item.received_at), 'MMM d, yyyy HH:mm'); } catch { return ''; } })()}
            </span>
          </div>
          <div className="p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))] mt-3">
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{item.body}</p>
          </div>
        </div>

        {/* Section 2: System Analysis */}
        {item.ai_intent ? (
          <div className="p-5 border-b border-[hsl(var(--border))]">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles size={14} className="text-[hsl(var(--primary))]" />
              <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">System Analysis</span>
            </div>

            <div className="grid grid-cols-3 gap-4 mb-4">
              {/* Intent */}
              <div className="p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                <p className="text-[10px] text-muted-foreground mb-1">Classification</p>
                <Badge className={`${intentInfo?.badgeClass || ''} text-xs`}>
                  {intentInfo?.label || item.ai_intent.intent}
                </Badge>
              </div>
              {/* Confidence */}
              <div className="p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                <p className="text-[10px] text-muted-foreground mb-1">Confidence</p>
                <p className={`text-sm font-semibold ${confidence?.color}`}>{confidence?.label}</p>
              </div>
              {/* Proposed Action */}
              <div className="p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                <p className="text-[10px] text-muted-foreground mb-1">Proposed Action</p>
                <p className="text-sm font-medium">{actionLabels[action.type] || action.type || 'None'}</p>
              </div>
            </div>

            {/* Summary */}
            <div className="p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))] mb-4">
              <p className="text-[10px] text-muted-foreground mb-1">Summary</p>
              <p className="text-sm">{item.ai_intent.summary}</p>
            </div>

            {/* Policy Evaluation */}
            {item.policy_action && (
              <div className={`p-3 rounded-lg border mb-4 ${
                item.policy_action === 'auto_run' ? 'bg-[hsl(var(--success)/0.06)] border-[hsl(var(--success)/0.15)]' :
                item.policy_action === 'escalate' ? 'bg-[hsl(var(--critical)/0.06)] border-[hsl(var(--critical)/0.15)]' :
                item.policy_action === 'require_approval' ? 'bg-[hsl(var(--warning)/0.06)] border-[hsl(var(--warning)/0.15)]' :
                'bg-[hsl(var(--info)/0.06)] border-[hsl(var(--info)/0.15)]'
              }`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Shield size={12} className={policyActionLabels[item.policy_action]?.color || ''} />
                    <span className="text-xs font-medium">Automation Policy</span>
                  </div>
                  <Badge className={`text-[10px] ${
                    item.policy_action === 'auto_run' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' :
                    item.policy_action === 'require_approval' ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' :
                    item.policy_action === 'escalate' ? 'bg-[hsl(var(--critical)/0.15)] text-[hsl(var(--critical))]' :
                    'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]'
                  }`}>
                    {policyActionLabels[item.policy_action]?.label || item.policy_action}
                  </Badge>
                </div>
                {item.escalation && (
                  <div className="flex flex-col gap-2 mt-2 pt-2 border-t border-[hsl(var(--border)/0.5)]">
                    <div className="flex items-center gap-2">
                      <AlertTriangle size={12} className="text-[hsl(var(--critical))]" />
                      <span className="text-xs">Routed to <span className="font-semibold">{item.escalation.route_to}</span></span>
                      <Badge className={`text-[9px] ml-auto ${
                        item.escalation.priority === 'critical' ? 'bg-[hsl(var(--critical)/0.15)] text-[hsl(var(--critical))]' :
                        item.escalation.priority === 'high' ? 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]' :
                        'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]'
                      }`}>{item.escalation.priority}</Badge>
                    </div>
                    {item.escalation.reasons && item.escalation.reasons.length > 0 && (
                      <div className="pl-5 space-y-1">
                        {item.escalation.reasons.map((reason, idx) => (
                          <p key={idx} className="text-[10px] text-muted-foreground">• {reason}</p>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Auto-Execution Trail */}
            {item.auto_executed && item.execution_results && (
              <div className="p-3 rounded-lg border mb-4 bg-[hsl(var(--primary)/0.06)] border-[hsl(var(--primary)/0.15)]">
                <div className="flex items-center gap-2 mb-3">
                  <Zap size={14} className="text-[hsl(var(--primary))]" />
                  <span className="text-xs font-semibold text-foreground">Auto-Executed</span>
                  {item.auto_executed_at && (
                    <span className="text-[10px] text-muted-foreground ml-auto font-mono">
                      {new Date(item.auto_executed_at).toLocaleString()}
                    </span>
                  )}
                </div>
                <div className="space-y-2">
                  {item.execution_results.map((result, idx) => (
                    <div key={result.event_id || result.contact_id || result.agent_id || `${result.type}-${idx}`} className="flex items-start gap-2 text-xs">
                      <CheckCircle2 size={12} className="text-[hsl(var(--success))] mt-0.5 shrink-0" />
                      <div>
                        <p className="text-foreground/90">
                          {result.type === 'event_created' && 'Meeting scheduled in calendar'}
                          {result.type === 'contact_created' && 'Contact added to CRM'}
                          {result.type === 'agent_created' && 'Agent onboarding initiated'}
                          {result.type === 'follow_up_queued' && 'Follow-up queued'}
                          {result.type === 'ignored' && 'Marked as spam/ignored'}
                          {!['event_created', 'contact_created', 'agent_created', 'follow_up_queued', 'ignored'].includes(result.type) && `Action: ${result.type}`}
                        </p>
                        {result.event_id && (
                          <p className="text-[10px] text-muted-foreground font-mono">Event ID: {result.event_id.slice(0, 8)}...</p>
                        )}
                        {result.contact_id && (
                          <p className="text-[10px] text-muted-foreground font-mono">Contact ID: {result.contact_id.slice(0, 8)}...</p>
                        )}
                        {result.agent_id && (
                          <p className="text-[10px] text-muted-foreground font-mono">Agent ID: {result.agent_id.slice(0, 8)}...</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {item.execution_source && (
                  <div className="mt-2 pt-2 border-t border-[hsl(var(--border)/0.5)]">
                    <span className="text-[10px] text-muted-foreground">
                      Source: <span className="font-mono">{item.execution_source}</span>
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Extracted Info */}
            {Object.values(entities).some(v => v) && (
              <div>
                <p className="text-[10px] text-muted-foreground mb-2 uppercase tracking-wide">Extracted Information</p>
                <div className="grid grid-cols-2 gap-2">
                  {entities.person_name && (
                    <div className="flex items-center gap-2 p-2 rounded-md bg-[hsl(var(--surface-1))]">
                      <User size={12} className="text-muted-foreground" />
                      <span className="text-xs">{entities.person_name}</span>
                    </div>
                  )}
                  {entities.email && (
                    <div className="flex items-center gap-2 p-2 rounded-md bg-[hsl(var(--surface-1))]">
                      <Mail size={12} className="text-muted-foreground" />
                      <span className="text-xs">{entities.email}</span>
                    </div>
                  )}
                  {entities.phone && (
                    <div className="flex items-center gap-2 p-2 rounded-md bg-[hsl(var(--surface-1))]">
                      <Phone size={12} className="text-muted-foreground" />
                      <span className="text-xs">{entities.phone}</span>
                    </div>
                  )}
                  {entities.date_time && (
                    <div className="flex items-center gap-2 p-2 rounded-md bg-[hsl(var(--surface-1))]">
                      <Clock size={12} className="text-muted-foreground" />
                      <span className="text-xs">{entities.date_time}</span>
                    </div>
                  )}
                  {entities.property && (
                    <div className="flex items-center gap-2 p-2 rounded-md bg-[hsl(var(--surface-1))] col-span-2">
                      <MapPin size={12} className="text-muted-foreground" />
                      <span className="text-xs">{entities.property}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="p-5 border-b border-[hsl(var(--border))] flex items-center justify-center">
            <div className="text-center py-8">
              <Sparkles size={28} className="mx-auto text-muted-foreground mb-3" />
              <p className="text-sm text-muted-foreground">This request hasn't been classified yet</p>
            </div>
          </div>
        )}

        {/* Section 3: Action Controls */}
        <div className="p-5">
          {item.ai_suggested_action && item.status === 'processed' ? (
            <div>
              <div className="p-4 rounded-xl bg-[hsl(var(--primary)/0.06)] border border-[hsl(var(--primary)/0.15)] mb-4">
                <p className="text-sm font-medium mb-1">
                  {action.type === 'schedule_meeting' && 'This request is ready to be scheduled'}
                  {action.type === 'create_contact' && 'Ready to add this person to your contacts'}
                  {action.type === 'send_follow_up' && 'A follow-up message is recommended'}
                  {action.type === 'start_onboarding' && 'Ready to start onboarding for this team member'}
                  {action.type === 'flag_review' && 'This request needs your personal attention'}
                  {!['schedule_meeting', 'create_contact', 'send_follow_up', 'start_onboarding', 'flag_review'].includes(action.type) && action.description}
                </p>
                <p className="text-xs text-muted-foreground">{action.description}</p>
              </div>

              <div className="flex items-center gap-2">
                {/* Primary: Approve & Execute */}
                <Button
                  data-testid="smart-inbox-approve-button"
                  onClick={() => handleApproveWithOverrides(item.inbox_id, {})}
                  disabled={approving}
                  className="bg-[hsl(var(--success))] hover:bg-[hsl(var(--success)/0.9)] text-white flex-1"
                >
                  {approving ? (
                    <><Loader2 size={14} className="animate-spin mr-1.5" /> Executing...</>
                  ) : (
                    <><CheckCircle2 size={14} className="mr-1.5" />
                      {action.type === 'schedule_meeting' && 'Schedule Call'}
                      {action.type === 'create_contact' && 'Add Contact'}
                      {action.type === 'send_follow_up' && 'Send Follow-up'}
                      {action.type === 'start_onboarding' && 'Start Onboarding'}
                      {action.type === 'flag_review' && 'Mark Reviewed'}
                      {!['schedule_meeting', 'create_contact', 'send_follow_up', 'start_onboarding', 'flag_review'].includes(action.type) && 'Approve'}
                    </>
                  )}
                </Button>

                {/* Secondary: Adjust Details */}
                <Button
                  data-testid="smart-inbox-edit-button"
                  variant="secondary"
                  onClick={() => openEditDialog(item)}
                >
                  <Edit3 size={14} className="mr-1.5" /> Adjust
                </Button>

                {/* Tertiary: Skip */}
                <Button
                  data-testid="smart-inbox-decline-button"
                  variant="ghost"
                  onClick={() => handleDecline(item.inbox_id)}
                  className="text-muted-foreground hover:text-foreground"
                >
                  <SkipForward size={14} className="mr-1.5" /> Skip
                </Button>
              </div>
            </div>
          ) : item.status === 'actioned' ? (
            <div className="p-3 rounded-lg bg-[hsl(var(--success)/0.08)] border border-[hsl(var(--success)/0.2)] flex items-center gap-2">
              <CheckCircle2 size={16} className="text-[hsl(var(--success))]" />
              <span className="text-sm">Action completed by the system</span>
            </div>
          ) : item.status === 'declined' ? (
            <div className="p-3 rounded-lg bg-[hsl(var(--muted))] border border-[hsl(var(--border))] flex items-center gap-2">
              <SkipForward size={16} className="text-muted-foreground" />
              <span className="text-sm text-muted-foreground">This request was skipped</span>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-4">Classify this message first to see available actions</p>
          )}
        </div>
      </div>
    </Card>
  );
}
