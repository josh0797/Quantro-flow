import React, { useState, useEffect, useCallback } from 'react';
import { Zap, ShieldCheck, Loader2 } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { toast } from 'sonner';
import { useLanguage } from '../context/LanguageContext';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';

const STORAGE_KEY = 'realtyos_mode';
const backendUrl = process.env.REACT_APP_BACKEND_URL || '';

/**
 * SimulationModeToggle
 *
 * A first-class product-status control that surfaces the app's current
 * data source mode (Simulation vs Live). Persists locally and syncs to the
 * backend business profile. Confirms only when switching ON → OFF (which is
 * a perceptually destructive transition from the user's perspective even
 * though it never deletes real data).
 *
 * Variants:
 *   - compact  (sidebar): row layout, small badge, no description
 *   - banner   (settings top-of-page): full card with title, description, badge, switch
 *   - inline   (misc): simple pill + switch
 */
export default function SimulationModeToggle({ variant = 'compact' }) {
  const { t } = useLanguage();
  const { profile, updateProfile, refetch } = useBusinessProfile();
  const [saving, setSaving] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingValue, setPendingValue] = useState(null);

  // Backend is the source of truth; localStorage mirrors it for fast first paint.
  const isOn = !!profile?.simulation_mode;

  // Keep localStorage in sync whenever the backend value changes.
  useEffect(() => {
    if (profile) {
      try {
        localStorage.setItem(STORAGE_KEY, isOn ? 'simulation' : 'live');
      } catch {
        /* ignore */
      }
    }
  }, [isOn, profile]);

  const writeValue = useCallback(
    async (nextOn) => {
      if (!profile) return;
      setSaving(true);
      try {
        // Preserve the rest of the profile — only simulation_mode is changing here.
        await updateProfile({
          industry: profile.industry || 'other',
          use_case: profile.use_case || '',
          entity_labels:
            profile.entity_labels || {
              contacts: 'Contacts',
              team_members: 'Team Members',
              meetings: 'Meetings',
              events: 'Events',
              services: 'Services',
            },
          simulation_mode: nextOn,
          language: profile.language,
        });
        try {
          localStorage.setItem(STORAGE_KEY, nextOn ? 'simulation' : 'live');
        } catch {
          /* ignore */
        }
        toast.success(nextOn ? t('simulation.toast_on') : t('simulation.toast_off'));
        refetch();
      } catch (err) {
        toast.error(t('simulation.toast_failed'));
      } finally {
        setSaving(false);
      }
    },
    [profile, updateProfile, refetch, t]
  );

  const handleChange = (nextOn) => {
    // OFF → ON: no confirmation (non-destructive).
    if (nextOn) {
      writeValue(true);
      return;
    }
    // ON → OFF: ask for confirmation.
    setPendingValue(false);
    setConfirmOpen(true);
  };

  const confirmGoLive = () => {
    setConfirmOpen(false);
    if (pendingValue === false) writeValue(false);
    setPendingValue(null);
  };

  const cancelGoLive = () => {
    setConfirmOpen(false);
    setPendingValue(null);
  };

  // ─── BADGE ───
  const Badge = (
    <span
      data-testid="simulation-badge"
      data-state={isOn ? 'simulation' : 'live'}
      className={
        isOn
          ? 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide border bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))] border-[hsl(var(--warning)/0.35)]'
          : 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide border bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))] border-[hsl(var(--success)/0.35)]'
      }
    >
      <span
        className={
          isOn
            ? 'w-1.5 h-1.5 rounded-full bg-[hsl(var(--warning))] animate-pulse'
            : 'w-1.5 h-1.5 rounded-full bg-[hsl(var(--success))]'
        }
      />
      {isOn ? t('simulation.badge_simulation') : t('simulation.badge_live')}
    </span>
  );

  // ─── CONFIRMATION MODAL ───
  const ConfirmModal = (
    <AlertDialog open={confirmOpen} onOpenChange={(o) => !o && cancelGoLive()}>
      <AlertDialogContent
        data-testid="simulation-confirm-dialog"
        className="bg-[hsl(var(--card))] border-[hsl(var(--border))]"
      >
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <ShieldCheck size={18} className="text-[hsl(var(--primary))]" />
            {t('simulation.confirm_title')}
          </AlertDialogTitle>
          <AlertDialogDescription className="pt-2 text-sm text-muted-foreground">
            {t('simulation.confirm_body')}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel
            onClick={cancelGoLive}
            data-testid="simulation-confirm-cancel"
          >
            {t('simulation.confirm_stay')}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={confirmGoLive}
            data-testid="simulation-confirm-go-live"
            className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary)/0.9)] text-[hsl(var(--primary-foreground))]"
          >
            {t('simulation.confirm_go_live')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );

  // ─── VARIANTS ───
  if (variant === 'banner') {
    return (
      <div
        data-testid="simulation-toggle-banner"
        data-state={isOn ? 'simulation' : 'live'}
        className={
          isOn
            ? 'rounded-xl border border-[hsl(var(--warning)/0.35)] bg-[hsl(var(--warning)/0.04)] p-5 transition-colors'
            : 'rounded-xl border border-[hsl(var(--success)/0.25)] bg-[hsl(var(--success)/0.03)] p-5 transition-colors'
        }
      >
        <div className="flex items-start gap-4">
          <div
            className={
              isOn
                ? 'w-10 h-10 shrink-0 rounded-lg flex items-center justify-center bg-[hsl(var(--warning)/0.15)] text-[hsl(var(--warning))]'
                : 'w-10 h-10 shrink-0 rounded-lg flex items-center justify-center bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]'
            }
          >
            {isOn ? <Zap size={20} /> : <ShieldCheck size={20} />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-semibold text-foreground">
                {t('simulation.banner_title')}
              </h2>
              {Badge}
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed max-w-3xl mt-2">
              {isOn
                ? t('simulation.banner_description_on')
                : t('simulation.banner_description_off')}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {saving && <Loader2 size={14} className="animate-spin text-muted-foreground" />}
            <Switch
              checked={isOn}
              onCheckedChange={handleChange}
              disabled={saving}
              data-testid="simulation-toggle-switch"
              aria-label={t('simulation.label')}
            />
          </div>
        </div>
        {ConfirmModal}
      </div>
    );
  }

  if (variant === 'inline') {
    return (
      <div
        data-testid="simulation-toggle-inline"
        className="flex items-center gap-2"
      >
        <span className="text-xs font-medium text-muted-foreground">
          {t('simulation.label')}
        </span>
        {Badge}
        <Switch
          checked={isOn}
          onCheckedChange={handleChange}
          disabled={saving}
          data-testid="simulation-toggle-switch"
        />
        {ConfirmModal}
      </div>
    );
  }

  // compact (sidebar default)
  return (
    <div
      data-testid="simulation-toggle-compact"
      data-state={isOn ? 'simulation' : 'live'}
      className={
        isOn
          ? 'flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-[hsl(var(--warning)/0.30)] bg-[hsl(var(--warning)/0.04)]'
          : 'flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--surface-1))]'
      }
      title={isOn ? t('simulation.tooltip_on') : t('simulation.tooltip_off')}
    >
      <div className="flex flex-col min-w-0 gap-0.5">
        <span className="text-[11px] font-medium text-foreground truncate">
          {t('simulation.label')}
        </span>
        {Badge}
      </div>
      <Switch
        checked={isOn}
        onCheckedChange={handleChange}
        disabled={saving}
        data-testid="simulation-toggle-switch"
        aria-label={t('simulation.label')}
      />
      {ConfirmModal}
    </div>
  );
}
