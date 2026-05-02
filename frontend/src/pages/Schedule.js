import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Calendar, Clock, MapPin, Users, Plus, Loader2, Trash2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { getCalendarEvents, createCalendarEvent, deleteCalendarEvent } from '../lib/api';
import { toast } from 'sonner';
import { format, parseISO, isToday, isTomorrow, addDays, isBefore, isAfter, startOfDay } from 'date-fns';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { getEntityLabel, getIndustryConfig } from '../config/industryConfig';
import { useLanguage } from '../context/LanguageContext';
import LiveEmptyState from '../components/LiveEmptyState';
import DataModeBanner from '../components/DataModeBanner';

export default function Schedule() {
  const { profile } = useBusinessProfile();
  const { t } = useLanguage();
  const industry = profile?.industry || 'other';
  const customLabels = profile?.entity_labels || {};
  const meetingsLabel = getEntityLabel(industry, 'meetings', customLabels);
  const industryConfig = getIndustryConfig(industry);
  
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({ title: '', description: '', start_time: '', end_time: '', location: '', attendees: '' });

  const fetchEvents = useCallback(async () => {
    try {
      const data = await getCalendarEvents();
      setEvents(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchEvents(); }, [fetchEvents, profile?.simulation_mode]);

  const handleCreate = async () => {
    if (!form.title || !form.start_time || !form.end_time) {
      toast.error(t('schedule.toasts.save_failed'));
      return;
    }
    setCreating(true);
    try {
      await createCalendarEvent({
        ...form,
        attendees: form.attendees ? form.attendees.split(',').map(s => s.trim()) : [],
      });
      toast.success(t('schedule.toasts.created'), { description: form.title });
      setForm({ title: '', description: '', start_time: '', end_time: '', location: '', attendees: '' });
      setDialogOpen(false);
      fetchEvents();
    } catch (err) {
      toast.error(t('schedule.toasts.save_failed'));
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (eventId) => {
    try {
      await deleteCalendarEvent(eventId);
      toast.success(t('schedule.toasts.cancelled'));
      fetchEvents();
    } catch (err) {
      toast.error(t('schedule.toasts.save_failed'));
    }
  };

  const groupEvents = () => {
    const today = [];
    const tomorrow = [];
    const upcoming = [];
    const past = [];
    const now = new Date();

    events.forEach(e => {
      try {
        const start = parseISO(e.start_time);
        if (isToday(start)) today.push(e);
        else if (isTomorrow(start)) tomorrow.push(e);
        else if (isAfter(start, now)) upcoming.push(e);
        else past.push(e);
      } catch {
        upcoming.push(e);
      }
    });
    return { today, tomorrow, upcoming, past };
  };

  const groups = groupEvents();

  const EventCard = ({ event, index }) => (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03 }}
      className="flex items-start gap-4 p-4 rounded-xl bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))] card-hover group"
    >
      <div className="w-14 text-center shrink-0">
        <p className="text-lg font-display font-semibold tabular-nums">
          {(() => { try { return format(parseISO(event.start_time), 'HH:mm'); } catch { return '--:--'; } })()}
        </p>
        <p className="text-[10px] text-muted-foreground">
          {(() => { try { return format(parseISO(event.end_time), 'HH:mm'); } catch { return ''; } })()}
        </p>
      </div>
      <Separator orientation="vertical" className="h-12" />
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p className="text-sm font-medium">{event.title}</p>
          <Badge variant="secondary" className="text-[10px] shrink-0">{event.status}</Badge>
        </div>
        {event.description && <p className="text-xs text-muted-foreground mt-1">{event.description}</p>}
        <div className="flex items-center gap-4 mt-2">
          {event.location && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <MapPin size={12} /> {event.location}
            </span>
          )}
          {event.attendees?.length > 0 && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <Users size={12} /> {event.attendees.join(', ')}
            </span>
          )}
        </div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
        onClick={() => handleDelete(event.event_id)}
      >
        <Trash2 size={14} />
      </Button>
    </motion.div>
  );

  const EventSection = ({ title, events, emptyText }) => (
    <div className="mb-6">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">{title}</h3>
      {events.length === 0 ? (
        <p className="text-sm text-muted-foreground py-4 text-center">{emptyText}</p>
      ) : (
        <div className="space-y-2">
          {events.map((e, i) => <EventCard key={e.event_id || i} event={e} index={i} />)}
        </div>
      )}
    </div>
  );

  return (
    <div className="page-container relative z-[1]">
      {/* Persistent honesty banner — surfaces "Modo demo / Datos
          reales" with a one-tap connect for /welcome/calendar. */}
      <DataModeBanner module="schedule" />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{meetingsLabel}</h1>
          <p className="text-sm text-muted-foreground mt-1">{industryConfig.name} · {t('schedule.subtitle')}</p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button data-testid="schedule-create-event-button" size="sm">
              <Plus size={14} className="mr-1" /> {t('schedule.add_event')}
            </Button>
          </DialogTrigger>
          <DialogContent data-testid="schedule-event-dialog" className="bg-[hsl(var(--card))] border-[hsl(var(--border))]">
            <DialogHeader>
              <DialogTitle>{t('schedule.add_event')}</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div><Label>{t('schedule.form.title_label')} *</Label><Input value={form.title} onChange={e => setForm({...form, title: e.target.value})} placeholder={t('schedule.form.title_label')} /></div>
              <div><Label>{t('schedule.form.notes_label')}</Label><Input value={form.description} onChange={e => setForm({...form, description: e.target.value})} placeholder={t('common.optional')} /></div>
              <div className="grid grid-cols-2 gap-4">
                <div><Label>{t('schedule.form.date_label')} *</Label><Input type="datetime-local" value={form.start_time} onChange={e => setForm({...form, start_time: e.target.value})} /></div>
                <div><Label>{t('schedule.form.time_label')} *</Label><Input type="datetime-local" value={form.end_time} onChange={e => setForm({...form, end_time: e.target.value})} /></div>
              </div>
              <div><Label>{t('schedule.form.location_label')}</Label><Input value={form.location} onChange={e => setForm({...form, location: e.target.value})} placeholder={t('schedule.form.location_label')} /></div>
              <div><Label>{t('schedule.form.attendees_label')}</Label><Input value={form.attendees} onChange={e => setForm({...form, attendees: e.target.value})} placeholder={t('schedule.form.attendees_label')} /></div>
            </div>
            <DialogFooter>
              <Button variant="secondary" onClick={() => setDialogOpen(false)}>{t('common.cancel')}</Button>
              <Button onClick={handleCreate} disabled={creating}>
                {creating ? <Loader2 size={14} className="animate-spin mr-1" /> : <Calendar size={14} className="mr-1" />}
                {t('common.create')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="space-y-4">
          {[1,2,3].map(i => <Skeleton key={i} className="h-20 rounded-xl" />)}
        </div>
      ) : events.length === 0 && !profile?.simulation_mode ? (
        <LiveEmptyState moduleKey="schedule" />
      ) : (
        <div data-testid="schedule-calendar">
          <EventSection title={t('schedule.today')} events={groups.today} emptyText={t('schedule.empty_hint')} />
          <EventSection title={t('schedule.tomorrow')} events={groups.tomorrow} emptyText={t('schedule.empty_hint')} />
          <EventSection title={t('schedule.upcoming')} events={groups.upcoming} emptyText={t('schedule.empty_state')} />
        </div>
      )}
    </div>
  );
}
