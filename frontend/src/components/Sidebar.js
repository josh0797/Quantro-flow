import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, Inbox, Calendar, Users, UserPlus, PenTool, ChevronLeft, ChevronRight, Zap, Bot, Settings } from 'lucide-react';
import { useState, useEffect } from 'react';
import { getSystemStatus } from '../lib/api';
import { useLanguage } from '../context/LanguageContext';
import LanguageSwitcher from './LanguageSwitcher';

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, labelKey: 'sidebar.dashboard', testId: 'nav-dashboard' },
  { to: '/inbox', icon: Inbox, labelKey: 'sidebar.smart_inbox', testId: 'nav-smart-inbox' },
  { to: '/schedule', icon: Calendar, labelKey: 'sidebar.schedule', testId: 'nav-schedule' },
  { to: '/crm', icon: Users, labelKey: 'sidebar.crm', testId: 'nav-crm' },
  { to: '/onboarding', icon: UserPlus, labelKey: 'sidebar.onboarding', testId: 'nav-onboarding' },
  { to: '/content', icon: PenTool, labelKey: 'sidebar.content_engine', testId: 'nav-content-engine' },
  { to: '/automation', icon: Bot, labelKey: 'sidebar.automation', testId: 'nav-automation' },
  { to: '/settings', icon: Settings, labelKey: 'sidebar.settings', testId: 'nav-settings' },
];

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [systemStatus, setSystemStatus] = useState(null);
  const [integrationStatus, setIntegrationStatus] = useState({});
  const location = useLocation();
  const { t } = useLanguage();

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const status = await getSystemStatus();
        setSystemStatus(status);
      } catch (e) { /* ignore */ }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const fetchIntegrations = async () => {
      try {
        const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
        const response = await fetch(`${backendUrl}/api/integrations`);
        if (response.ok) {
          const data = await response.json();
          const status = {};
          data.forEach(integration => {
            status[integration.provider] = integration.status === 'connected';
          });
          setIntegrationStatus(status);
        }
      } catch (e) { /* ignore */ }
    };
    fetchIntegrations();
  }, []);

  return (
    <aside
      data-testid="app-sidebar"
      className={`flex flex-col border-r border-[hsl(var(--sidebar-border))] bg-[hsl(var(--sidebar-background))] transition-all duration-300 ease-out relative z-10 ${
        collapsed ? 'w-[68px]' : 'w-64'
      }`}
      style={{ height: '100vh', position: 'sticky', top: 0 }}
    >
      {/* Logo / Brand */}
      <div className="flex items-center gap-3 px-4 h-16 border-b border-[hsl(var(--sidebar-border))]">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]">
          <Zap size={18} />
        </div>
        {!collapsed && (
          <div className="flex flex-col">
            <span className="font-display text-sm font-semibold text-foreground tracking-tight">{t('sidebar.brand')}</span>
            <span className="text-[10px] text-muted-foreground tracking-wide uppercase">{t('sidebar.brand_subtitle')}</span>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = location.pathname === item.to;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={item.testId}
              className={`group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors duration-150 ${
                isActive
                  ? 'bg-[hsl(var(--sidebar-accent))] text-foreground'
                  : 'text-muted-foreground hover:text-foreground hover:bg-[hsl(var(--sidebar-accent))]'
              }`}
            >
              <Icon size={18} className={isActive ? 'text-[hsl(var(--primary))]' : ''} />
              {!collapsed && <span>{t(item.labelKey)}</span>}
              {isActive && !collapsed && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-[hsl(var(--primary))]" />
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Language Switcher + System Status */}
      <div className="px-3 pb-4 space-y-2">
        {!collapsed && (
          <div data-testid="sidebar-language-footer" className="px-1">
            <LanguageSwitcher variant="compact" />
          </div>
        )}

        <div data-testid="system-status" className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
          <span className={`status-dot ${systemStatus?.overall || 'running'} animate-pulse-dot`} />
          {!collapsed && (
            <div className="flex flex-col flex-1 min-w-0">
              <span className="text-xs font-medium text-foreground">{t('sidebar.system_running')}</span>
              <span data-testid="system-status-last-sync" className="text-[10px] font-mono text-muted-foreground truncate">
                {systemStatus ? t('sidebar.synced', { time: new Date(systemStatus.timestamp).toLocaleTimeString() }) : t('common.loading')}
              </span>
            </div>
          )}
        </div>

        {/* Integration Status */}
        {!collapsed && (integrationStatus.gmail || integrationStatus.google_calendar || integrationStatus.crm) && (
          <div className="px-3 py-2 rounded-lg bg-[hsl(var(--surface-1)/0.5)] border border-[hsl(var(--border))]">
            <div className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">{t('sidebar.integrations_label')}</div>
            <div className="space-y-1">
              {integrationStatus.gmail && (
                <div className="flex items-center gap-1.5 text-[10px]">
                  <div className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--success))]"></div>
                  <span className="text-muted-foreground">Gmail</span>
                </div>
              )}
              {integrationStatus.google_calendar && (
                <div className="flex items-center gap-1.5 text-[10px]">
                  <div className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--success))]"></div>
                  <span className="text-muted-foreground">Calendar</span>
                </div>
              )}
              {integrationStatus.crm && (
                <div className="flex items-center gap-1.5 text-[10px]">
                  <div className="w-1.5 h-1.5 rounded-full bg-[hsl(var(--success))]"></div>
                  <span className="text-muted-foreground">CRM</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="absolute -right-3 top-20 w-6 h-6 rounded-full bg-[hsl(var(--surface-2))] border border-[hsl(var(--border))] flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
      </button>
    </aside>
  );
}
