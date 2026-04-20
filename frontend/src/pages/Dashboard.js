import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ScrollArea } from '../components/ui/scroll-area';
import { Separator } from '../components/ui/separator';
import { Skeleton } from '../components/ui/skeleton';
import { Users, Calendar, Inbox, Activity, Zap, Clock, ArrowRight, CheckCircle2, AlertTriangle, Mail, UserPlus, PenTool, Database, Plug } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { getDashboardMetrics, getActivity, getAISuggestions, getCalendarEvents } from '../lib/api';
import { useNavigate } from 'react-router-dom';
import { format, parseISO, isToday, isTomorrow } from 'date-fns';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { getIndustryConfig, getEntityLabel } from '../config/industryConfig';

const eventTypeIcons = {
  system: Zap,
  inbox: Mail,
  ai: Zap,
  calendar: Calendar,
  crm: Users,
  onboarding: UserPlus,
  content: PenTool,
  integration: Plug,
};

const eventTypeColors = {
  system: 'text-[hsl(var(--success))]',
  inbox: 'text-[hsl(var(--info))]',
  ai: 'text-[hsl(var(--primary))]',
  calendar: 'text-[hsl(var(--warning))]',
  crm: 'text-[hsl(var(--accent))]',
  onboarding: 'text-[hsl(var(--success))]',
  content: 'text-[hsl(var(--info))]',
  integration: 'text-[hsl(var(--success))]',
};

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [activities, setActivities] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [events, setEvents] = useState([]);
  const [integrations, setIntegrations] = useState([]);
  const [simulationStatus, setSimulationStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();
  const { profile, loading: profileLoading } = useBusinessProfile();

  // Get industry-specific config
  const industry = profile?.industry || 'other';
  const industryConfig = getIndustryConfig(industry);
  const customLabels = profile?.entity_labels || {};

  const fetchData = useCallback(async () => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const [m, a, s, e, i, sim] = await Promise.all([
        getDashboardMetrics(),
        getActivity(15),
        getAISuggestions(),
        getCalendarEvents(),
        fetch(`${backendUrl}/api/integrations`).then(r => r.json()).catch(() => []),
        fetch(`${backendUrl}/api/simulation/status`).then(r => r.json()).catch(() => null),
      ]);
      setMetrics(m);
      setSimulationStatus(sim);
      
      // Use industry-specific activities if available, otherwise use fetched activities
      const industryActivities = industryConfig.activities.map((act, idx) => ({
        ...act,
        event_id: `industry-${idx}`,
        timestamp: new Date(Date.now() - idx * 60000).toISOString(),
      }));
      setActivities(industryActivities.length > 0 ? industryActivities : a);
      
      // Use industry-specific suggestions
      setSuggestions(industryConfig.aiSuggestions || s);
      
      setEvents(e);
      setIntegrations(i);
    } catch (err) {
      console.error('Dashboard fetch error:', err);
    } finally {
      setLoading(false);
    }
  }, [industryConfig]);

  useEffect(() => {
    if (!profileLoading) {
      fetchData();
      const interval = setInterval(fetchData, 15000);
      return () => clearInterval(interval);
    }
  }, [fetchData, profileLoading]);

  const todayEvents = events.filter(e => {
    try { return isToday(parseISO(e.start_time)); } catch { return false; }
  });
  const tomorrowEvents = events.filter(e => {
    try { return isTomorrow(parseISO(e.start_time)); } catch { return false; }
  });

  const connectedIntegrations = integrations.filter(i => i.status === 'connected');

  if (loading || profileLoading) {
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
          <p className="text-sm text-muted-foreground mt-1">
            {industryConfig.name} operations • Real-time overview
          </p>
        </div>
        <div className="flex items-center gap-3">
          {simulationStatus?.simulation_mode ? (
            <>
              <Badge className="bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.3)]">
                <Zap size={12} className="mr-1" />
                Simulation Mode Active
              </Badge>
            </>
          ) : (
            <>
              <span className="status-dot running animate-pulse-dot" />
              <span className="text-xs text-muted-foreground">Live Data Mode</span>
            </>
          )}
        </div>
      </div>

      {/* KPI Cards - Dynamic based on industry */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {/* KPI 1: Team/Patients/Clients/Customers */}
        <Card data-testid="kpi-team" className="card-hover cursor-pointer" onClick={() => navigate('/onboarding')}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {industryConfig.kpis.team.label}
            </CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.agents?.total || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {metrics?.agents?.active || 0} active
              </p>
            </div>
          </CardContent>
        </Card>

        {/* KPI 2: Schedule/Appointments/Calls */}
        <Card data-testid="kpi-schedule" className="card-hover cursor-pointer" onClick={() => navigate('/schedule')}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {industryConfig.kpis.schedule.label}
            </CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.calendar?.upcoming_events || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">next 7 days</p>
            </div>
          </CardContent>
        </Card>

        {/* KPI 3: Inbox/Requests/Issues */}
        <Card data-testid="kpi-inbox" className="card-hover cursor-pointer" onClick={() => navigate('/inbox')}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {industryConfig.kpis.inbox.label}
            </CardTitle>
            <Inbox className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.inbox?.new || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {metrics?.inbox?.processed || 0} processed
              </p>
            </div>
          </CardContent>
        </Card>

        {/* KPI 4: CRM/Records */}
        <Card data-testid="kpi-crm" className="card-hover cursor-pointer" onClick={() => navigate('/crm')}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              {industryConfig.kpis.crm.label}
            </CardTitle>
            <Database className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div>
              <p className="font-display text-2xl font-semibold tabular-nums">{metrics?.crm?.total_contacts || 0}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {metrics?.crm?.new_this_week || 0} new this week
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Integration Status Banner (if any connected) */}
      {connectedIntegrations.length > 0 && (
        <Card className="mb-6 border-[hsl(var(--success)/0.3)] bg-[hsl(var(--success)/0.05)]">
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-[hsl(var(--success)/0.15)]">
                <Plug size={18} className="text-[hsl(var(--success))]" />
              </div>
              <div className="flex-1">
                <p className="text-sm font-medium text-foreground">
                  {connectedIntegrations.length} Integration{connectedIntegrations.length > 1 ? 's' : ''} Connected
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {connectedIntegrations.map(i => i.provider === 'google_calendar' ? 'Calendar' : i.provider === 'gmail' ? 'Gmail' : i.provider.toUpperCase()).join(', ')} syncing in real-time
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => navigate('/settings')}>
                Manage
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Left column: Activity Feed */}
        <div className="lg:col-span-2 space-y-6">
          {/* Live Activity Feed */}
          <Card data-testid="activity-feed">
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  <Activity size={16} className="text-[hsl(var(--primary))]" />
                  Live Activity
                </CardTitle>
                <Badge variant="outline" className="text-[10px]">Real-time</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[280px] pr-4">
                <AnimatePresence mode="popLayout">
                  {activities.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-[240px] text-center">
                      <Activity size={32} className="text-muted-foreground/40 mb-3" />
                      <p className="text-sm text-muted-foreground">No recent activity</p>
                      <p className="text-xs text-muted-foreground/70 mt-1">
                        Activity will appear here as your system processes items
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {activities.map((act, idx) => {
                        const Icon = eventTypeIcons[act.type] || Activity;
                        const colorClass = eventTypeColors[act.type] || 'text-muted-foreground';
                        return (
                          <motion.div
                            key={act.event_id || idx}
                            initial={{ opacity: 0, y: -10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, x: -10 }}
                            transition={{ duration: 0.2 }}
                            className="flex items-start gap-3 p-3 rounded-lg bg-[hsl(var(--surface-1))] hover:bg-[hsl(var(--surface-2))] transition-colors"
                          >
                            <div className={`flex items-center justify-center w-8 h-8 rounded-md bg-[hsl(var(--surface-2))] shrink-0 ${colorClass}`}>
                              <Icon size={14} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className="text-sm text-foreground">{act.text || act.description}</p>
                              <p className="text-xs text-muted-foreground mt-0.5">
                                {act.time || (act.timestamp ? format(parseISO(act.timestamp), 'p') : '')}
                              </p>
                            </div>
                          </motion.div>
                        );
                      })}
                    </div>
                  )}
                </AnimatePresence>
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Today's Schedule */}
          <Card data-testid="todays-schedule">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Calendar size={16} className="text-[hsl(var(--warning))]" />
                Today's {getEntityLabel(industry, 'meetings', customLabels)}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {todayEvents.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <Clock size={32} className="text-muted-foreground/40 mb-3" />
                  <p className="text-sm text-muted-foreground">No {getEntityLabel(industry, 'meetings', customLabels).toLowerCase()} scheduled today</p>
                  <Button size="sm" variant="outline" className="mt-4" onClick={() => navigate('/schedule')}>
                    View Full Calendar
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  {todayEvents.slice(0, 3).map((event) => (
                    <div key={event.event_id} className="flex items-center gap-3 p-3 rounded-lg bg-[hsl(var(--surface-1))] hover:bg-[hsl(var(--surface-2))] transition-colors cursor-pointer" onClick={() => navigate('/schedule')}>
                      <div className="flex flex-col items-center justify-center w-12 h-12 rounded-lg bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] shrink-0">
                        <span className="text-xs font-medium">{format(parseISO(event.start_time), 'HH:mm')}</span>
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground truncate">{event.title}</p>
                        <p className="text-xs text-muted-foreground">{event.attendees?.join(', ') || 'No attendees'}</p>
                      </div>
                    </div>
                  ))}
                  {todayEvents.length > 3 && (
                    <Button size="sm" variant="ghost" className="w-full" onClick={() => navigate('/schedule')}>
                      View {todayEvents.length - 3} more
                    </Button>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right column: AI Suggestions & Quick Actions */}
        <div className="space-y-6">
          {/* AI Suggestions - Industry Specific */}
          <Card data-testid="ai-suggestions">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap size={16} className="text-[hsl(var(--primary))]" />
                AI Suggestions
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {suggestions.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-8 text-center">
                    <Zap size={32} className="text-muted-foreground/40 mb-3" />
                    <p className="text-sm text-muted-foreground">No suggestions yet</p>
                  </div>
                ) : (
                  suggestions.map((suggestion, idx) => {
                    const priorityColor = suggestion.priority === 'high' ? 'text-[hsl(var(--critical))]' : 
                                         suggestion.priority === 'medium' ? 'text-[hsl(var(--warning))]' : 
                                         'text-[hsl(var(--info))]';
                    return (
                      <div key={idx} className="flex items-start gap-3 p-3 rounded-lg bg-[hsl(var(--surface-1))] hover:bg-[hsl(var(--surface-2))] transition-colors cursor-pointer group">
                        <CheckCircle2 size={14} className={`mt-0.5 shrink-0 ${priorityColor}`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-foreground group-hover:text-[hsl(var(--primary))] transition-colors">
                            {suggestion.text}
                          </p>
                        </div>
                        <ArrowRight size={14} className="text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                      </div>
                    );
                  })
                )}
              </div>
            </CardContent>
          </Card>

          {/* Quick Actions */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">Quick Actions</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-2">
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="justify-start" 
                  onClick={() => navigate('/inbox')}
                  data-testid="quick-action-inbox"
                >
                  <Inbox size={14} className="mr-2" />
                  Process Inbox
                </Button>
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="justify-start" 
                  onClick={() => navigate('/schedule')}
                  data-testid="quick-action-schedule"
                >
                  <Calendar size={14} className="mr-2" />
                  View Calendar
                </Button>
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="justify-start" 
                  onClick={() => navigate('/crm')}
                  data-testid="quick-action-crm"
                >
                  <Users size={14} className="mr-2" />
                  Manage {getEntityLabel(industry, 'contacts', customLabels)}
                </Button>
                <Button 
                  variant="outline" 
                  size="sm" 
                  className="justify-start" 
                  onClick={() => navigate('/content')}
                  data-testid="quick-action-content"
                >
                  <PenTool size={14} className="mr-2" />
                  Create Content
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* System Health */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">System Health</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">AI Engine</span>
                  <Badge variant="outline" className="text-[10px] bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]">Running</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">Automation</span>
                  <Badge variant="outline" className="text-[10px] bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]">Active</Badge>
                </div>
                {connectedIntegrations.map((integration, idx) => (
                  <div key={idx} className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground capitalize">
                      {integration.provider === 'google_calendar' ? 'Calendar' : integration.provider === 'gmail' ? 'Gmail' : integration.provider}
                    </span>
                    <Badge variant="outline" className="text-[10px] bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]">Connected</Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
