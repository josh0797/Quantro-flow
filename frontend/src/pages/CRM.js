import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ScrollArea } from '../components/ui/scroll-area';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Users, Mail, Phone, Clock, ArrowRight, Plus, Loader2, RefreshCw, Calendar, Activity } from 'lucide-react';
import { motion } from 'framer-motion';
import { getContacts, getContact, createContact } from '../lib/api';
import { toast } from 'sonner';
import { format, parseISO } from 'date-fns';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { getEntityLabel } from '../config/industryConfig';
import { useLanguage } from '../context/LanguageContext';
import LiveEmptyState from '../components/LiveEmptyState';

const lifecycleColors = {
  new: 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]',
  active: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]',
  nurturing: 'bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]',
  at_risk: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]',
};

const syncStatusColors = {
  synced: 'text-[hsl(var(--success))]',
  pending: 'text-[hsl(var(--warning))]',
  failed: 'text-[hsl(var(--destructive))]',
};

export default function CRM() {
  const { profile } = useBusinessProfile();
  const { t } = useLanguage();
  const industry = profile?.industry || 'other';
  const customLabels = profile?.entity_labels || {};
  const contactsLabel = getEntityLabel(industry, 'contacts', customLabels);
  
  const [contacts, setContacts] = useState([]);
  const [selectedContact, setSelectedContact] = useState(null);
  const [contactDetail, setContactDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [filter, setFilter] = useState('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', phone: '', type: 'lead', source: 'manual', notes: '' });

  const fetchContacts = useCallback(async () => {
    try {
      const data = await getContacts(filter === 'all' ? null : filter);
      setContacts(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { fetchContacts(); }, [fetchContacts, profile?.simulation_mode]);

  const selectContact = async (contact) => {
    setSelectedContact(contact);
    setDetailLoading(true);
    try {
      const detail = await getContact(contact.contact_id);
      setContactDetail(detail);
    } catch (err) {
      console.error(err);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!form.name || !form.email) {
      toast.error(t('crm.toasts.save_failed'));
      return;
    }
    setCreating(true);
    try {
      await createContact(form);
      toast.success(t('crm.toasts.created'), { description: form.name });
      setForm({ name: '', email: '', phone: '', type: 'lead', source: 'manual', notes: '' });
      setDialogOpen(false);
      fetchContacts();
    } catch (err) {
      toast.error(t('crm.toasts.save_failed'));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="page-container relative z-[1]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{contactsLabel}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t('crm.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5">
            <span className="status-dot running" />
            <span className="text-xs text-muted-foreground">CRM Sync</span>
          </span>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button size="sm"><Plus size={14} className="mr-1" /> {t('crm.add_contact')}</Button>
            </DialogTrigger>
            <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <DialogHeader><DialogTitle>{t('crm.new_contact')}</DialogTitle></DialogHeader>
              <div className="space-y-4 py-4">
                <div><Label>{t('crm.form.name_label')} *</Label><Input value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder={t('crm.form.name_label')} /></div>
                <div><Label>{t('crm.form.email_label')} *</Label><Input value={form.email} onChange={e => setForm({...form, email: e.target.value})} placeholder={t('crm.form.email_label')} /></div>
                <div><Label>{t('crm.form.phone_label')}</Label><Input value={form.phone} onChange={e => setForm({...form, phone: e.target.value})} placeholder={t('crm.form.phone_label')} /></div>
                <div><Label>{t('crm.form.status_label')}</Label>
                  <Select value={form.type} onValueChange={v => setForm({...form, type: v})}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="lead">{t('crm.status.lead')}</SelectItem>
                      <SelectItem value="client">{t('crm.status.customer')}</SelectItem>
                      <SelectItem value="investor">Investor</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div><Label>{t('crm.form.notes_label')}</Label><Input value={form.notes} onChange={e => setForm({...form, notes: e.target.value})} placeholder={t('common.optional')} /></div>
              </div>
              <DialogFooter>
                <Button variant="secondary" onClick={() => setDialogOpen(false)}>{t('common.cancel')}</Button>
                <Button onClick={handleCreate} disabled={creating}>
                  {creating ? <Loader2 size={14} className="animate-spin mr-1" /> : <Plus size={14} className="mr-1" />}
                  {t('crm.add_contact')}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Lifecycle Filter */}
      <div className="flex gap-2 mb-6">
        {['all', 'new', 'active', 'nurturing', 'at_risk'].map(f => (
          <Button
            key={f}
            variant={filter === f ? 'default' : 'secondary'}
            size="sm"
            className="text-xs capitalize"
            onClick={() => { setFilter(f); setLoading(true); }}
          >
            {f === 'at_risk' ? 'At Risk' : f}
          </Button>
        ))}
      </div>

      <div className="grid lg:grid-cols-5 gap-6">
        {/* Contacts Table */}
        <div className="lg:col-span-3">
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="p-4 space-y-3">
                  {[1,2,3,4].map(i => <Skeleton key={i} className="h-14" />)}
                </div>
              ) : contacts.length === 0 && !profile?.simulation_mode ? (
                <div className="p-4">
                  <LiveEmptyState moduleKey="crm" />
                </div>
              ) : (
                <Table data-testid="crm-contacts-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('crm.table.name')}</TableHead>
                      <TableHead>{t('crm.table.status')}</TableHead>
                      <TableHead>{t('crm.status.active')}</TableHead>
                      <TableHead>{t('integrations.groups.crm')}</TableHead>
                      <TableHead>{t('common.edit')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {contacts.map((c) => (
                      <TableRow
                        key={c.contact_id}
                        data-testid="crm-contact-row"
                        className={`cursor-pointer transition-colors ${
                          selectedContact?.contact_id === c.contact_id ? 'bg-[hsl(var(--surface-2))]' : 'hover:bg-[hsl(var(--surface-1))]'
                        }`}
                        onClick={() => selectContact(c)}
                      >
                        <TableCell>
                          <div>
                            <p className="text-sm font-medium">{c.name}</p>
                            <p className="text-xs text-muted-foreground">{c.email}</p>
                          </div>
                        </TableCell>
                        <TableCell><Badge variant="secondary" className="text-xs capitalize">{c.type}</Badge></TableCell>
                        <TableCell>
                          <Badge className={`text-xs ${lifecycleColors[c.lifecycle_stage] || ''}`}>
                            {c.lifecycle_stage?.replace('_', ' ')}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <span className={`flex items-center gap-1.5 text-xs ${syncStatusColors[c.ghl_sync_status] || ''}`}>
                            <RefreshCw size={11} />
                            {c.ghl_sync_status}
                          </span>
                        </TableCell>
                        <TableCell>
                          <span className="text-xs font-mono text-muted-foreground">
                            {(() => { try { return format(parseISO(c.updated_at), 'MMM d HH:mm'); } catch { return '-'; } })()}
                          </span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Contact Profile Panel */}
        <div className="lg:col-span-2">
          {selectedContact ? (
            <Card data-testid="crm-contact-profile">
              <CardHeader>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-[hsl(var(--primary)/0.12)] flex items-center justify-center">
                    <span className="text-sm font-semibold text-[hsl(var(--primary))]">
                      {selectedContact.name.split(' ').map(n => n[0]).join('')}
                    </span>
                  </div>
                  <div>
                    <CardTitle className="text-base">{selectedContact.name}</CardTitle>
                    <p className="text-xs text-muted-foreground capitalize">{selectedContact.type} - {selectedContact.source}</p>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {detailLoading ? (
                  <div className="space-y-3"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-3/4" /><Skeleton className="h-20" /></div>
                ) : contactDetail ? (
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2 text-sm"><Mail size={14} className="text-muted-foreground" /> {contactDetail.email}</div>
                      {contactDetail.phone && <div className="flex items-center gap-2 text-sm"><Phone size={14} className="text-muted-foreground" /> {contactDetail.phone}</div>}
                    </div>
                    {contactDetail.notes && (
                      <div className="p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                        <p className="text-xs text-muted-foreground mb-1">Notes</p>
                        <p className="text-sm">{contactDetail.notes}</p>
                      </div>
                    )}
                    <Separator />

                    {/* Related Inbox */}
                    {contactDetail.inbox_items?.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Inbox Threads</h4>
                        <div className="space-y-2">
                          {contactDetail.inbox_items.map(item => (
                            <div key={item.inbox_id} className="p-2 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                              <p className="text-xs font-medium truncate">{item.subject}</p>
                              <p className="text-[10px] text-muted-foreground">
                                {(() => { try { return format(parseISO(item.received_at), 'MMM d'); } catch { return ''; } })()}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Related Events */}
                    {contactDetail.events?.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Scheduled Meetings</h4>
                        <div className="space-y-2">
                          {contactDetail.events.map(event => (
                            <div key={event.event_id} className="flex items-center gap-2 p-2 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                              <Calendar size={12} className="text-muted-foreground" />
                              <p className="text-xs truncate flex-1">{event.title}</p>
                              <span className="text-[10px] font-mono text-muted-foreground">
                                {(() => { try { return format(parseISO(event.start_time), 'MMM d'); } catch { return ''; } })()}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Activity Timeline */}
                    <div data-testid="crm-activity-timeline">
                      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">Activity Timeline</h4>
                      {contactDetail.activities?.length > 0 ? (
                        <div className="space-y-3">
                          {contactDetail.activities.map((a, i) => (
                            <div key={a.event_id || i} data-testid="crm-activity-item" className="flex gap-3">
                              <div className="flex flex-col items-center">
                                <div className="w-2 h-2 rounded-full bg-[hsl(var(--primary))] mt-1.5" />
                                {i < contactDetail.activities.length - 1 && <div className="w-px flex-1 bg-[hsl(var(--border))]" />}
                              </div>
                              <div className="pb-3">
                                <p className="text-xs font-medium">{a.title}</p>
                                <p className="text-[10px] text-muted-foreground">{a.description}</p>
                                <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
                                  {(() => { try { return format(parseISO(a.timestamp), 'MMM d HH:mm'); } catch { return ''; } })()}
                                </p>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-muted-foreground">No activity recorded yet</p>
                      )}
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : (
            <Card className="h-full flex items-center justify-center min-h-[300px]">
              <CardContent className="text-center">
                <Users size={32} className="mx-auto text-muted-foreground mb-3" />
                <p className="text-sm text-muted-foreground">{t('crm.empty_state')}</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
