import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ScrollArea } from '../components/ui/scroll-area';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Mail, Zap, CheckCircle2, XCircle, Clock, AlertTriangle, Loader2, ArrowRight, Sparkles } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { getInbox, analyzeInboxItem, approveInboxAction, declineInboxAction } from '../lib/api';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';

const intentLabels = {
  booking: { label: 'Booking', className: 'intent-booking' },
  onboarding: { label: 'Onboarding', className: 'intent-onboarding' },
  follow_up: { label: 'Follow Up', className: 'intent-follow_up' },
  inquiry: { label: 'Inquiry', className: 'intent-inquiry' },
  escalation: { label: 'Escalation', className: 'intent-escalation' },
  spam: { label: 'Spam', className: 'intent-spam' },
  needs_review: { label: 'Needs Review', className: 'intent-needs_review' },
};

const statusColors = {
  new: 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]',
  processed: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]',
  actioned: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]',
  declined: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]',
};

export default function SmartInbox() {
  const [items, setItems] = useState([]);
  const [selectedItem, setSelectedItem] = useState(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(null);
  const [approving, setApproving] = useState(false);
  const [filter, setFilter] = useState('all');

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

  useEffect(() => {
    fetchInbox();
  }, [fetchInbox]);

  const handleAnalyze = async (inboxId) => {
    setAnalyzing(inboxId);
    try {
      const result = await analyzeInboxItem(inboxId);
      setItems(prev => prev.map(i => i.inbox_id === inboxId ? result : i));
      if (selectedItem?.inbox_id === inboxId) setSelectedItem(result);
      toast.success('AI analysis complete', { description: `Intent: ${result.ai_intent?.intent}` });
    } catch (err) {
      toast.error('Analysis failed', { description: err.message });
    } finally {
      setAnalyzing(null);
    }
  };

  const handleApprove = async (inboxId) => {
    setApproving(true);
    try {
      await approveInboxAction(inboxId);
      toast.success('Action approved', { description: 'The system is executing the suggested action.' });
      fetchInbox();
      setSelectedItem(null);
    } catch (err) {
      toast.error('Approve failed', { description: err.message });
    } finally {
      setApproving(false);
    }
  };

  const handleDecline = async (inboxId) => {
    try {
      await declineInboxAction(inboxId);
      toast.info('Action declined');
      fetchInbox();
      setSelectedItem(null);
    } catch (err) {
      toast.error('Decline failed');
    }
  };

  return (
    <div className="page-container relative z-[1]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Smart Inbox</h1>
          <p className="text-sm text-muted-foreground mt-1">AI-powered message analysis and action suggestions</p>
        </div>
        <Badge variant="secondary" className="text-xs">
          {items.filter(i => i.status === 'new').length} unprocessed
        </Badge>
      </div>

      {/* Filters */}
      <div data-testid="smart-inbox-filter" className="flex gap-2 mb-6">
        {['all', 'new', 'processed', 'actioned'].map(f => (
          <Button
            key={f}
            variant={filter === f ? 'default' : 'secondary'}
            size="sm"
            className="text-xs capitalize"
            onClick={() => { setFilter(f); setLoading(true); }}
          >
            {f}
          </Button>
        ))}
      </div>

      <div className="grid lg:grid-cols-5 gap-6">
        {/* Inbox List */}
        <div className="lg:col-span-2">
          <ScrollArea data-testid="smart-inbox-list" className="h-[calc(100vh-220px)]">
            {loading ? (
              <div className="space-y-3">
                {[1,2,3,4].map(i => <Skeleton key={i} className="h-24 rounded-xl" />)}
              </div>
            ) : items.length === 0 ? (
              <div className="text-center py-12">
                <Mail size={32} className="mx-auto text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">No messages found</p>
              </div>
            ) : (
              <div className="space-y-2">
                <AnimatePresence>
                  {items.map((item, i) => (
                    <motion.div
                      key={item.inbox_id}
                      data-testid="smart-inbox-item"
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.03 }}
                    >
                      <div
                        className={`p-4 rounded-xl border cursor-pointer transition-colors duration-150 ${
                          selectedItem?.inbox_id === item.inbox_id
                            ? 'bg-[hsl(var(--surface-2))] border-[hsl(var(--ring)/0.3)]'
                            : 'bg-[hsl(var(--surface-1))] border-[hsl(var(--border))] hover:bg-[hsl(var(--surface-2))]'
                        }`}
                        onClick={() => setSelectedItem(item)}
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2 min-w-0">
                            {!item.read && <div className="w-2 h-2 rounded-full bg-[hsl(var(--info))] shrink-0" />}
                            <p className="text-sm font-medium truncate">{item.from_name}</p>
                          </div>
                          <span className="text-[10px] font-mono text-muted-foreground shrink-0">
                            {(() => { try { return format(parseISO(item.received_at), 'HH:mm'); } catch { return ''; } })()}
                          </span>
                        </div>
                        <p className="text-sm truncate mb-1">{item.subject}</p>
                        <p className="text-xs text-muted-foreground line-clamp-2 mb-2">{item.body}</p>
                        <div className="flex items-center gap-2">
                          <Badge className={`text-[10px] px-2 py-0.5 ${statusColors[item.status] || ''}`}>
                            {item.status}
                          </Badge>
                          {item.ai_intent && (
                            <Badge className={`text-[10px] px-2 py-0.5 ${intentLabels[item.ai_intent.intent]?.className || ''}`}>
                              {intentLabels[item.ai_intent.intent]?.label || item.ai_intent.intent}
                            </Badge>
                          )}
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </div>
            )}
          </ScrollArea>
        </div>

        {/* Detail Panel */}
        <div className="lg:col-span-3">
          {selectedItem ? (
            <Card data-testid="smart-inbox-detail">
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-lg">{selectedItem.subject}</CardTitle>
                    <p className="text-sm text-muted-foreground mt-1">
                      From: {selectedItem.from_name} ({selectedItem.from_email})
                    </p>
                    <p className="text-xs font-mono text-muted-foreground mt-1">
                      {(() => { try { return format(parseISO(selectedItem.received_at), 'MMM d, yyyy HH:mm'); } catch { return ''; } })()}
                      {' '} via {selectedItem.source}
                    </p>
                  </div>
                  <Badge className={`${statusColors[selectedItem.status] || ''}`}>{selectedItem.status}</Badge>
                </div>
              </CardHeader>
              <CardContent>
                <Tabs defaultValue="message">
                  <TabsList className="mb-4">
                    <TabsTrigger value="message">Message</TabsTrigger>
                    <TabsTrigger value="ai">AI Analysis</TabsTrigger>
                  </TabsList>

                  <TabsContent value="message">
                    <div className="p-4 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                      <p className="text-sm leading-relaxed whitespace-pre-wrap">{selectedItem.body}</p>
                    </div>
                  </TabsContent>

                  <TabsContent value="ai">
                    {selectedItem.ai_intent ? (
                      <div className="space-y-4">
                        <div className="p-4 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                          <div className="flex items-center gap-3 mb-3">
                            <Sparkles size={16} className="text-[hsl(var(--primary))]" />
                            <span className="text-sm font-medium">AI Intent Analysis</span>
                          </div>
                          <div className="grid grid-cols-2 gap-4">
                            <div>
                              <p className="text-xs text-muted-foreground mb-1">Intent</p>
                              <Badge className={`${intentLabels[selectedItem.ai_intent.intent]?.className || ''}`}>
                                {intentLabels[selectedItem.ai_intent.intent]?.label || selectedItem.ai_intent.intent}
                              </Badge>
                            </div>
                            <div>
                              <p className="text-xs text-muted-foreground mb-1">Confidence</p>
                              <p className="text-sm font-mono font-medium">{(selectedItem.ai_intent.confidence * 100).toFixed(0)}%</p>
                            </div>
                          </div>
                          <Separator className="my-3" />
                          <p className="text-xs text-muted-foreground mb-1">Summary</p>
                          <p className="text-sm">{selectedItem.ai_intent.summary}</p>
                          {selectedItem.ai_intent.entities && (
                            <>
                              <Separator className="my-3" />
                              <p className="text-xs text-muted-foreground mb-2">Extracted Entities</p>
                              <div className="grid grid-cols-2 gap-2">
                                {Object.entries(selectedItem.ai_intent.entities).map(([key, val]) => val && (
                                  <div key={key} className="text-xs">
                                    <span className="text-muted-foreground capitalize">{key.replace('_', ' ')}:</span>
                                    <span className="ml-1 font-medium">{val}</span>
                                  </div>
                                ))}
                              </div>
                            </>
                          )}
                        </div>

                        {selectedItem.ai_suggested_action && selectedItem.status === 'processed' && (
                          <div className="p-4 rounded-lg bg-[hsl(var(--primary)/0.08)] border border-[hsl(var(--primary)/0.2)]">
                            <div className="flex items-center gap-2 mb-3">
                              <Zap size={14} className="text-[hsl(var(--primary))]" />
                              <span className="text-sm font-medium">Suggested Action</span>
                            </div>
                            <p className="text-sm mb-4">{selectedItem.ai_suggested_action.description}</p>
                            <div className="flex gap-2">
                              <Button
                                data-testid="smart-inbox-approve-button"
                                size="sm"
                                onClick={() => handleApprove(selectedItem.inbox_id)}
                                disabled={approving}
                                className="bg-[hsl(var(--success))] hover:bg-[hsl(var(--success)/0.9)] text-white"
                              >
                                {approving ? <Loader2 size={14} className="animate-spin mr-1" /> : <CheckCircle2 size={14} className="mr-1" />}
                                Approve
                              </Button>
                              <Button
                                data-testid="smart-inbox-decline-button"
                                variant="secondary"
                                size="sm"
                                onClick={() => handleDecline(selectedItem.inbox_id)}
                              >
                                <XCircle size={14} className="mr-1" /> Decline
                              </Button>
                            </div>
                          </div>
                        )}

                        {selectedItem.status === 'actioned' && (
                          <div className="p-3 rounded-lg bg-[hsl(var(--success)/0.08)] border border-[hsl(var(--success)/0.2)] flex items-center gap-2">
                            <CheckCircle2 size={16} className="text-[hsl(var(--success))]" />
                            <span className="text-sm">Action executed by the system</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-center py-8">
                        <Sparkles size={28} className="mx-auto text-muted-foreground mb-3" />
                        <p className="text-sm text-muted-foreground mb-4">This message hasn't been analyzed yet</p>
                        <Button
                          onClick={() => handleAnalyze(selectedItem.inbox_id)}
                          disabled={analyzing === selectedItem.inbox_id}
                        >
                          {analyzing === selectedItem.inbox_id ? (
                            <><Loader2 size={14} className="animate-spin mr-2" /> Analyzing...</>
                          ) : (
                            <><Zap size={14} className="mr-2" /> Run AI Analysis</>
                          )}
                        </Button>
                      </div>
                    )}
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          ) : (
            <Card className="h-full flex items-center justify-center min-h-[400px]">
              <CardContent className="text-center">
                <Mail size={40} className="mx-auto text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">Select a message to view details</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
