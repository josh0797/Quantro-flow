import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Checkbox } from '../components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { UserPlus, User, CheckCircle2, Clock, Loader2, Plus, ChevronDown, ChevronRight } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { getAgents, createAgent, updateOnboardingTask } from '../lib/api';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { getEntityLabel } from '../config/industryConfig';

const statusColors = {
  onboarding: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]',
  active: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]',
  inactive: 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]',
};

export default function Onboarding() {
  const { profile } = useBusinessProfile();
  const industry = profile?.industry || 'other';
  const customLabels = profile?.entity_labels || {};
  const teamLabel = getEntityLabel(industry, 'team_members', customLabels);
  
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedAgent, setExpandedAgent] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', phone: '', role: 'agent' });

  const fetchAgents = useCallback(async () => {
    try {
      const data = await getAgents();
      setAgents(data);
      // Auto-expand first onboarding agent
      const onboarding = data.find(a => a.status === 'onboarding');
      if (onboarding && !expandedAgent) setExpandedAgent(onboarding.agent_id);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAgents(); }, [fetchAgents]);

  const handleCreate = async () => {
    if (!form.name || !form.email) {
      toast.error('Name and email are required');
      return;
    }
    setCreating(true);
    try {
      await createAgent(form);
      toast.success('Agent added', { description: `${form.name} onboarding initiated.` });
      setForm({ name: '', email: '', phone: '', role: 'agent' });
      setDialogOpen(false);
      fetchAgents();
    } catch (err) {
      toast.error('Failed to add agent');
    } finally {
      setCreating(false);
    }
  };

  const handleTaskToggle = async (taskId, currentStatus) => {
    const newStatus = currentStatus === 'completed' ? 'pending' : 'completed';
    try {
      await updateOnboardingTask(taskId, newStatus);
      fetchAgents();
    } catch (err) {
      toast.error('Failed to update task');
    }
  };

  const onboardingAgents = agents.filter(a => a.status === 'onboarding');
  const activeAgents = agents.filter(a => a.status === 'active');

  return (
    <div className="page-container relative z-[1]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{teamLabel} Onboarding</h1>
          <p className="text-sm text-muted-foreground mt-1">Track and manage team setup workflows</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button data-testid="onboarding-add-agent" size="sm">
              <Plus size={14} className="mr-1" /> Add {teamLabel.slice(0, -1)}
            </Button>
          </DialogTrigger>
          <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))]">
            <DialogHeader><DialogTitle>Add New {teamLabel.slice(0, -1)}</DialogTitle></DialogHeader>
            <div className="space-y-4 py-4">
              <div><Label>Full Name *</Label><Input value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="Full name" /></div>
              <div><Label>Email *</Label><Input value={form.email} onChange={e => setForm({...form, email: e.target.value})} placeholder="Email address" /></div>
              <div><Label>Phone</Label><Input value={form.phone} onChange={e => setForm({...form, phone: e.target.value})} placeholder="Phone number" /></div>
              <div><Label>Role</Label>
                <Select value={form.role} onValueChange={v => setForm({...form, role: v})}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="agent">Agent</SelectItem>
                    <SelectItem value="senior_agent">Senior Agent</SelectItem>
                    <SelectItem value="team_lead">Team Lead</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button variant="secondary" onClick={() => setDialogOpen(false)}>Cancel</Button>
              <Button onClick={handleCreate} disabled={creating}>
                {creating ? <Loader2 size={14} className="animate-spin mr-1" /> : <UserPlus size={14} className="mr-1" />}
                Add Agent
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="space-y-4">
          {[1,2,3].map(i => <Skeleton key={i} className="h-24 rounded-xl" />)}
        </div>
      ) : (
        <div data-testid="onboarding-agent-list" className="space-y-6">
          {/* Onboarding Agents */}
          {onboardingAgents.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Currently Onboarding</h3>
              <div className="space-y-3">
                {onboardingAgents.map((agent, i) => (
                  <motion.div key={agent.agent_id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
                    <Card data-testid="onboarding-agent-row" className="overflow-hidden">
                      <div
                        className="flex items-center gap-4 p-4 cursor-pointer hover:bg-[hsl(var(--surface-1))] transition-colors"
                        onClick={() => setExpandedAgent(expandedAgent === agent.agent_id ? null : agent.agent_id)}
                      >
                        <div className="w-10 h-10 rounded-full bg-[hsl(var(--warning)/0.12)] flex items-center justify-center">
                          <User size={18} className="text-[hsl(var(--warning))]" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium">{agent.name}</p>
                            <Badge className={`text-[10px] ${statusColors[agent.status] || ''}`}>{agent.status}</Badge>
                            <Badge variant="secondary" className="text-[10px] capitalize">{agent.role?.replace('_', ' ')}</Badge>
                          </div>
                          <p className="text-xs text-muted-foreground">{agent.email}</p>
                        </div>
                        <div className="flex items-center gap-4">
                          <div className="text-right">
                            <p data-testid="onboarding-progress" className="text-sm font-display font-semibold tabular-nums">{Math.round(agent.onboarding_progress)}%</p>
                            <Progress value={agent.onboarding_progress} className="w-20 h-1.5 mt-1" />
                          </div>
                          {expandedAgent === agent.agent_id ? <ChevronDown size={16} className="text-muted-foreground" /> : <ChevronRight size={16} className="text-muted-foreground" />}
                        </div>
                      </div>

                      <AnimatePresence>
                        {expandedAgent === agent.agent_id && agent.onboarding_tasks && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2 }}
                          >
                            <Separator />
                            <div className="p-4 bg-[hsl(var(--surface-1))]">
                              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Onboarding Steps</p>
                              <div className="space-y-3">
                                {agent.onboarding_tasks.map((task) => (
                                  <div key={task.task_id} className="flex items-start gap-3">
                                    <Checkbox
                                      checked={task.status === 'completed'}
                                      onCheckedChange={() => handleTaskToggle(task.task_id, task.status)}
                                      className="mt-0.5"
                                    />
                                    <div className="flex-1">
                                      <p className={`text-sm ${task.status === 'completed' ? 'line-through text-muted-foreground' : ''}`}>
                                        {task.title}
                                      </p>
                                      <p className="text-xs text-muted-foreground">{task.description}</p>
                                      {task.completed_at && (
                                        <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
                                          Completed {(() => { try { return format(parseISO(task.completed_at), 'MMM d HH:mm'); } catch { return ''; } })()}
                                        </p>
                                      )}
                                    </div>
                                    {task.auto_generated && (
                                      <Badge variant="secondary" className="text-[9px] shrink-0">Auto</Badge>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </Card>
                  </motion.div>
                ))}
              </div>
            </div>
          )}

          {/* Active Agents */}
          {activeAgents.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">Active Agents</h3>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {activeAgents.map((agent, i) => (
                  <motion.div key={agent.agent_id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
                    <Card className="card-hover">
                      <CardContent className="p-4">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-full bg-[hsl(var(--success)/0.12)] flex items-center justify-center">
                            <User size={16} className="text-[hsl(var(--success))]" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate">{agent.name}</p>
                            <p className="text-xs text-muted-foreground capitalize">{agent.role?.replace('_', ' ')}</p>
                          </div>
                          <Badge className={`text-[10px] ${statusColors[agent.status] || ''}`}>{agent.status}</Badge>
                        </div>
                      </CardContent>
                    </Card>
                  </motion.div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
