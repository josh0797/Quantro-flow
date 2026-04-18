import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ScrollArea } from '../components/ui/scroll-area';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Users, Calendar, Inbox, Activity, Zap, Clock, ArrowRight, CheckCircle2, AlertTriangle, Mail, UserPlus, PenTool } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { getDashboardMetrics, getActivity, getAISuggestions, getCalendarEvents } from '../lib/api';
import { useNavigate } from 'react-router-dom';
import { format, parseISO, isToday, isTomorrow } from 'date-fns';

const eventTypeIcons = {
  system: Zap,
  inbox: Mail,
  ai: Zap,
  calendar: Calendar,
  crm: Users,
  onboarding: UserPlus,
  content: PenTool,
};

const eventTypeColors = {
  system: 'text-[hsl(var(--success))]',
  inbox: 'text-[hsl(var(--info))]',
  ai: 'text-[hsl(var(--primary))]',
  calendar: 'text-[hsl(var(--warning))]',
  crm: 'text-[hsl(var(--accent))]',
  onboarding: 'text-[hsl(var(--success))]',
  content: 'text-[hsl(var(--info))]',
};

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [activities, setActivities] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchData = useCallback(async () => {
    try {
      const [m, a, s, e] = await Promise.all([
        getDashboardMetrics(),
        getActivity(15),
        getAISuggestions(),
        getCalendarEvents(),
      ]);
      setMetrics(m);
      setActivities(a);
      setSuggestions(s);
      setEvents(e);
    } catch (err) {
      console.error('Dashboard fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const todayEvents = events.filter(e => {
    try { return isToday(parseISO(e.start_time)); } catch { return false; }
  });
  const tomorrowEvents = events.filter(e => {
    try { return isTomorrow(parseISO(e.start_time)); } catch { return false; }
  });

  if (loading) {
    return (
      <div className="page-container relative z-[1]">
        <div className="space-y-6">
          <Skeleton className="h-8 w-48" />
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[1,2,3,4].map(i => <Skeleton key={i} className="h-32 rounded-xl" />)}
          </div>
          <div className="grid lg:grid-cols-3 gap-4">
            <Skeleton className="h-80 rounded-xl lg:col-span-2" />
            <Skeleton className="h-80 rounded-xl" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container relative z-[1]">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground mt-1">System overview and real-time activity</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="status-dot running animate-pulse-dot" />
          <span className="text-xs font-mono text-muted-foreground">All systems operational</span>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-8">
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0 }}>
          <Card data-testid="kpi-agents" className="card-hover cursor-pointer" onClick={() => navigate('/onboarding')}>
            <CardContent className="pt-5 pb-4 px-5">
              <div className="flex items-center justify-between mb-3">
                <div className="w-9 h-9 rounded-lg bg-[hsl(var(--success)/0.12)] flex items-center justify-center">
                  <Users size={18} className="text-[hsl(var(--success))]" />
                </div>
                <Badge variant="secondary" className="text-xs">+1 this week</Badge>
              </div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.agents?.total || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">{metrics?.agents?.active || 0} active agents</p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
          <Card data-testid="kpi-meetings" className="card-hover cursor-pointer" onClick={() => navigate('/schedule')}>
            <CardContent className="pt-5 pb-4 px-5">
              <div className="flex items-center justify-between mb-3">
                <div className="w-9 h-9 rounded-lg bg-[hsl(var(--warning)/0.12)] flex items-center justify-center">
                  <Calendar size={18} className="text-[hsl(var(--warning))]" />
                </div>
                <Badge variant="secondary" className="text-xs">{todayEvents.length} today</Badge>
              </div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.events?.today || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">Upcoming events</p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <Card data-testid="kpi-inbox" className="card-hover cursor-pointer" onClick={() => navigate('/inbox')}>
            <CardContent className="pt-5 pb-4 px-5">
              <div className="flex items-center justify-between mb-3">
                <div className="w-9 h-9 rounded-lg bg-[hsl(var(--info)/0.12)] flex items-center justify-center">
                  <Inbox size={18} className="text-[hsl(var(--info))]" />
                </div>
                {metrics?.inbox?.unread > 0 && (
                  <Badge className="bg-[hsl(var(--info))] text-[hsl(var(--primary-foreground))] text-xs">{metrics.inbox.unread} new</Badge>
                )}
              </div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.inbox?.total || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">Inbox messages</p>
            </CardContent>
          </Card>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}>
          <Card data-testid="kpi-sync-health" className="card-hover cursor-pointer" onClick={() => navigate('/crm')}>
            <CardContent className="pt-5 pb-4 px-5">
              <div className="flex items-center justify-between mb-3">
                <div className="w-9 h-9 rounded-lg bg-[hsl(var(--primary)/0.12)] flex items-center justify-center">
                  <Activity size={18} className="text-[hsl(var(--primary))]" />
                </div>
                <span className="flex items-center gap-1.5">
                  <span className="status-dot running" />
                  <span className="text-xs text-muted-foreground">Synced</span>
                </span>
              </div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.contacts?.synced || 0}/{metrics?.contacts?.total || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">CRM contacts synced</p>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Main Content Grid */}
      <div className="grid lg:grid-cols-3 gap-4 sm:gap-6">
        {/* Left: Today's Schedule + AI Suggestions */}
        <div className="lg:col-span-2 space-y-4 sm:space-y-6">
          {/* Today's Schedule */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Clock size={16} className="text-[hsl(var(--warning))]" />
                  Today's Schedule
                </CardTitle>
                <Button variant="ghost" size="sm" className="text-xs text-muted-foreground" onClick={() => navigate('/schedule')}>
                  View all <ArrowRight size={14} className="ml-1" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              {todayEvents.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">No events scheduled for today. The system is monitoring for new requests.</p>
              ) : (
                <div className="space-y-3">
                  {todayEvents.map((event, i) => (
                    <motion.div key={event.event_id || i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}>
                      <div className="flex items-start gap-3 p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                        <div className="w-10 text-center">
                          <p className="text-xs font-mono text-muted-foreground">
                            {(() => { try { return format(parseISO(event.start_time), 'HH:mm'); } catch { return '--:--'; } })()}
                          </p>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">{event.title}</p>
                          <p className="text-xs text-muted-foreground truncate">{event.location}</p>
                        </div>
                        <Badge variant="secondary" className="text-xs shrink-0">{event.status}</Badge>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
              {tomorrowEvents.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs text-muted-foreground mb-2 uppercase tracking-wide">Tomorrow</p>
                  <div className="space-y-2">
                    {tomorrowEvents.slice(0, 2).map((event, i) => (
                      <div key={event.event_id || i} className="flex items-center gap-3 p-2 rounded-md">
                        <p className="text-xs font-mono text-muted-foreground w-10 text-center">
                          {(() => { try { return format(parseISO(event.start_time), 'HH:mm'); } catch { return '--:--'; } })()}
                        </p>
                        <p className="text-sm text-muted-foreground truncate">{event.title}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* AI Suggestions */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Zap size={16} className="text-[hsl(var(--primary))]" />
                  AI Suggestions
                </CardTitle>
                <Badge variant="secondary" className="text-xs">{suggestions.length} pending</Badge>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              {suggestions.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">All caught up. The system is monitoring new messages.</p>
              ) : (
                <div className="space-y-2">
                  {suggestions.map((suggestion, i) => (
                    <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
                      <div
                        className="flex items-start gap-3 p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))] card-hover cursor-pointer"
                        onClick={() => navigate('/inbox')}
                      >
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                          suggestion.priority === 'high' ? 'bg-[hsl(var(--warning)/0.12)]' : 'bg-[hsl(var(--primary)/0.12)]'
                        }`}>
                          {suggestion.type === 'analyze' ? (
                            <Zap size={14} className={suggestion.priority === 'high' ? 'text-[hsl(var(--warning))]' : 'text-[hsl(var(--primary))]'} />
                          ) : (
                            <CheckCircle2 size={14} className="text-[hsl(var(--success))]" />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate">{suggestion.title}</p>
                          <p className="text-xs text-muted-foreground truncate">{suggestion.description}</p>
                        </div>
                        {suggestion.priority === 'high' && (
                          <Badge className="bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] text-xs shrink-0">Urgent</Badge>
                        )}
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right Rail: Activity Feed */}
        <div className="lg:col-span-1">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Activity size={16} className="text-[hsl(var(--success))]" />
                  Live Activity
                </CardTitle>
                <span className="flex items-center gap-1.5">
                  <span className="status-dot running animate-pulse-dot" />
                  <span className="text-xs font-mono text-muted-foreground">Live</span>
                </span>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <ScrollArea data-testid="live-activity-feed" className="h-[500px]">
                <AnimatePresence>
                  {activities.map((event, i) => {
                    const Icon = eventTypeIcons[event.event_type] || Activity;
                    const colorClass = eventTypeColors[event.event_type] || 'text-muted-foreground';
                    return (
                      <motion.div
                        key={event.event_id || i}
                        data-testid="activity-feed-item"
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.03, duration: 0.18 }}
                        className="flex gap-3 py-3"
                      >
                        <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 bg-[hsl(var(--surface-2))]`}>
                          <Icon size={13} className={colorClass} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium leading-tight">{event.title}</p>
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{event.description}</p>
                          <p className="text-[10px] font-mono text-muted-foreground mt-1">
                            {(() => { try { return format(parseISO(event.timestamp), 'HH:mm'); } catch { return ''; } })()}
                          </p>
                        </div>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
