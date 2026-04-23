import React from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Inbox, Calendar, Users, UserPlus, PenTool, ChevronLeft, ChevronRight, Zap, Bot, Settings, LogOut, Receipt, UserCircle } from 'lucide-react';
import { useState, useEffect } from 'react';
import { getSystemStatus } from '../lib/api';
import { useLanguage } from '../context/LanguageContext';
import { useAuth } from '../contexts/AuthContext';
import LanguageSwitcher from './LanguageSwitcher';
import SimulationModeToggle from './SimulationModeToggle';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import { authFetch } from '../lib/authFetch';

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, labelKey: 'sidebar.dashboard', testId: 'nav-dashboard' },
  { to: '/inbox', icon: Inbox, labelKey: 'sidebar.smart_inbox', testId: 'nav-smart-inbox' },
  { to: '/schedule', icon: Calendar, labelKey: 'sidebar.schedule', testId: 'nav-schedule' },
  { to: '/crm', icon: Users, labelKey: 'sidebar.crm', testId: 'nav-crm' },
  { to: '/onboarding', icon: UserPlus, labelKey: 'sidebar.onboarding', testId: 'nav-onboarding' },
  { to: '/content', icon: PenTool, labelKey: 'sidebar.content_engine', testId: 'nav-content-engine' },
  { to: '/automation', icon: Bot, labelKey: 'sidebar.automation', testId: 'nav-automation' },
  { to: '/plan', icon: Receipt, labelKey: 'plan_usage.nav_label', testId: 'nav-plan-usage' },
  { to: '/settings', icon: Settings, labelKey: 'sidebar.settings', testId: 'nav-settings' },
];

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [systemStatus, setSystemStatus] = useState(null);
  const [integrationStatus, setIntegrationStatus] = useState({});
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useLanguage();
  const { user, workspaces, logout } = useAuth();

  const handleLogout = async () => {
    try {
      await logout();
      toast.success(t('auth.signed_out_title'));
      // Route to login
      window.location.href = '/login';
    } catch (e) {
      toast.error('Logout failed');
    }
  };

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
        const response = await authFetch(`${backendUrl}/api/integrations`, { credentials: 'include' });
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

      {/* Language Switcher + Simulation Toggle + System Status */}
      <div className="px-3 pb-4 space-y-2">
        {!collapsed && (
          <div data-testid="sidebar-language-footer" className="px-1">
            <LanguageSwitcher variant="compact" />
          </div>
        )}

        {!collapsed && (
          <div data-testid="sidebar-simulation-toggle">
            <SimulationModeToggle variant="compact" />
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
        {/* User profile block */}
        {user && !collapsed && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                data-testid="sidebar-user-menu-trigger"
                className="w-full flex items-center gap-2.5 px-2 py-2 rounded-lg hover:bg-[hsl(var(--surface-1))] border border-transparent hover:border-[hsl(var(--border))] transition-colors"
              >
                <div className="w-8 h-8 rounded-full bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] flex items-center justify-center text-xs font-semibold shrink-0 overflow-hidden">
                  {user.picture ? (
                    <img src={user.picture} alt={user.name} className="w-full h-full object-cover" />
                  ) : (
                    (user.name || user.email || '?').slice(0, 1).toUpperCase()
                  )}
                </div>
                <div className="flex-1 min-w-0 text-left">
                  <div data-testid="sidebar-user-name" className="text-xs font-medium text-foreground truncate">
                    {user.name || user.email}
                  </div>
                  <div data-testid="sidebar-user-workspace" className="text-[10px] text-muted-foreground truncate">
                    {(workspaces?.find(w => w.is_current)?.name) || t('auth.my_workspace')}
                  </div>
                </div>
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-60" data-testid="sidebar-user-menu">
              <DropdownMenuLabel>
                <div className="flex flex-col">
                  <span className="text-xs font-medium truncate">{user.name}</span>
                  <span className="text-[10px] text-muted-foreground truncate">{user.email}</span>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                data-testid="sidebar-menu-view-account"
                onClick={() => navigate('/plan')}
              >
                <UserCircle size={14} className="mr-2" />
                {t('plan_usage.view_account')}
              </DropdownMenuItem>
              <DropdownMenuItem
                data-testid="sidebar-menu-plan-usage"
                onClick={() => navigate('/plan')}
              >
                <Receipt size={14} className="mr-2" />
                {t('plan_usage.nav_label')}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} data-testid="sidebar-logout-btn" className="text-[hsl(var(--destructive))]">
                <LogOut size={14} className="mr-2" />
                {t('auth.logout')}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="absolute -right-3 top-20 w-6 h-6 rounded-full bg-[hsl(var(--surface-2))] border border-[hsl(var(--border))] flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? <ChevronRight size={12} /> : <ChevronLeft size={12} />}
      </button>
    </aside>
  );
}
