import React from 'react';
import { ShieldCheck, Zap, PlugZap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useLanguage } from '../context/LanguageContext';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { authFetch } from '../lib/authFetch';

const backendUrl = process.env.REACT_APP_BACKEND_URL || '';

/**
 * LiveEmptyState
 *
 * Rendered on list/detail pages when the system is in Live Mode and
 * has no real data yet. Provides two clear next steps:
 *   1) connect real integrations (Settings → Integrations)
 *   2) try Simulation Mode to explore the product
 *
 * Never renders in Simulation Mode.
 *
 * Props:
 *   moduleKey: 'inbox' | 'crm' | 'schedule' | 'activity' | 'content' | 'generic'
 *              controls the contextual copy.
 *   className: optional wrapper styles.
 */
export default function LiveEmptyState({ moduleKey = 'generic', className = '' }) {
  const { t } = useLanguage();
  const { profile, updateProfile } = useBusinessProfile();
  const navigate = useNavigate();

  // Never render in Simulation Mode — pages should show real sim data instead.
  if (profile?.simulation_mode) return null;

  const moduleCopyMap = {
    inbox: t('simulation.live_empty_inbox'),
    crm: t('simulation.live_empty_crm'),
    schedule: t('simulation.live_empty_schedule'),
    activity: t('simulation.live_empty_activity'),
    content: t('simulation.live_empty_content'),
    onboarding: t('simulation.live_empty_onboarding'),
    generic: t('simulation.live_empty_subtitle'),
  };
  const subtitle = moduleCopyMap[moduleKey] || moduleCopyMap.generic;

  const handleTrySimulation = async () => {
    try {
      await updateProfile({
        industry: profile?.industry || 'other',
        use_case: profile?.use_case || '',
        entity_labels: profile?.entity_labels || {
          contacts: 'Contacts',
          team_members: 'Team Members',
          meetings: 'Meetings',
          events: 'Events',
          services: 'Services',
        },
        simulation_mode: true,
        language: profile?.language,
      });
      // Generate sample data now that simulation mode is on, so the
      // "Try Simulation Mode" CTA actually populates the screen.
      const res = await authFetch(`${backendUrl}/api/simulation/generate`, {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        toast.success(t('simulation.toast_on'));
      }
    } catch (e) {
      toast.error(t('simulation.toast_failed'));
    }
  };

  return (
    <div
      data-testid={`live-empty-state-${moduleKey}`}
      data-state="live-empty"
      className={`rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface-1))] p-8 md:p-10 text-center flex flex-col items-center gap-4 ${className}`}
    >
      <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-[hsl(var(--success)/0.12)] text-[hsl(var(--success))]">
        <ShieldCheck size={22} />
      </div>
      <div className="space-y-1.5 max-w-md">
        <h3 className="text-base font-semibold text-foreground">
          {t('simulation.live_empty_title')}
        </h3>
        <p className="text-sm text-muted-foreground leading-relaxed">{subtitle}</p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
        <Button
          data-testid="live-empty-cta-connect"
          onClick={() => navigate('/settings')}
          className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
        >
          <PlugZap size={16} className="mr-2" />
          {t('simulation.live_empty_cta_connect')}
        </Button>
        <Button
          data-testid="live-empty-cta-simulation"
          variant="outline"
          onClick={handleTrySimulation}
          className="border-[hsl(var(--warning)/0.4)] text-[hsl(var(--warning))] hover:bg-[hsl(var(--warning)/0.08)]"
        >
          <Zap size={16} className="mr-2" />
          {t('simulation.live_empty_cta_simulation')}
        </Button>
      </div>
    </div>
  );
}
