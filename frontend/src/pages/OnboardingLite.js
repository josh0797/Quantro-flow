import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2, Globe2, Building2, Briefcase, ArrowRight, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { supabase } from '../lib/supabaseClient';

/**
 * OnboardingLite — 3-question intake shown right after signup and before
 * the user reaches the main platform.
 *
 * Goals:
 *   1. Capture the country the business operates in.
 *   2. Capture the industry (giro) so the AI agent can tailor its
 *      recommendations / content generation.
 *   3. Capture the company name.
 *
 * Persistence strategy (user's directive — do not invent columns):
 *   • user_metadata is the always-on store (Supabase guarantees it).
 *   • profiles.full_name is the only confirmed profile column we touch.
 *   • country / industry / company_name are written best-effort to
 *     profiles.* — if the column doesn't exist Supabase returns a
 *     schema error which we swallow gracefully; the user_metadata copy
 *     is still authoritative.
 */
const COUNTRIES = [
  'México', 'Colombia', 'Argentina', 'Chile', 'Perú', 'Ecuador',
  'Venezuela', 'Costa Rica', 'Guatemala', 'Uruguay', 'Panamá', 'Bolivia',
  'Paraguay', 'Nicaragua', 'Honduras', 'El Salvador', 'República Dominicana',
  'Cuba', 'Puerto Rico', 'España', 'Estados Unidos', 'Canadá', 'Brasil',
  'Reino Unido', 'Alemania', 'Francia', 'Italia', 'Otro',
];

const INDUSTRY_KEYS = [
  'real_estate', 'healthcare', 'consulting', 'ecommerce', 'technology',
  'finance', 'education', 'manufacturing', 'retail', 'hospitality',
  'legal', 'marketing', 'construction', 'agriculture', 'automotive',
  'logistics', 'nonprofit', 'other',
];

export default function OnboardingLite() {
  const { t } = useLanguage();
  const { user, refresh } = useAuth();
  const navigate = useNavigate();

  const [country, setCountry] = useState('');
  const [industry, setIndustry] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const canSubmit = !!country && !!industry && companyName.trim().length >= 2;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!canSubmit) {
      setError(t('onboarding_lite.fill_all_fields'));
      return;
    }

    setSubmitting(true);
    try {
      const cleanCompany = companyName.trim();

      // 1. Persist to Supabase user_metadata (always works, source of truth
      //    for onboarding state).
      const { error: updErr } = await supabase.auth.updateUser({
        data: {
          full_name: user?.name,
          country,
          industry,
          company_name: cleanCompany,
          needs_onboarding: false,
          onboarded_at: new Date().toISOString(),
        },
      });
      if (updErr) throw updErr;

      // 2. Best-effort upsert into public.profiles. We only write columns
      //    the user explicitly confirmed exist (full_name) plus optional
      //    ones (country/industry/company_name). Any "column does not
      //    exist" response is swallowed — metadata is authoritative.
      try {
        await supabase
          .from('profiles')
          .upsert(
            {
              id: user.user_id,
              full_name: user?.name || null,
              country,
              industry,
              company_name: cleanCompany,
            },
            { onConflict: 'id' },
          );
      } catch (profileErr) {
        // eslint-disable-next-line no-console
        console.warn('[onboarding-lite] profiles upsert skipped:', profileErr?.message);
      }

      await refresh();
      toast.success(t('onboarding_lite.saved_title'), {
        description: t('onboarding_lite.saved_desc'),
      });
      navigate('/', { replace: true });
    } catch (err) {
      setError(err?.message || t('onboarding_lite.save_failed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      data-testid="onboarding-lite-page"
      className="min-h-screen w-full flex items-center justify-center bg-background text-foreground px-4 py-10 relative"
    >
      <div className="absolute inset-0 pointer-events-none bg-gradient-to-br from-[hsl(var(--primary)/0.06)] via-transparent to-transparent" />
      <div className="w-full max-w-xl relative">
        {/* Header */}
        <div className="space-y-2 mb-6">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] flex items-center justify-center font-bold">Q</div>
            <div className="text-sm font-semibold tracking-tight">Quantro Flow</div>
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Business OS</span>
          </div>
          <h1 className="text-2xl md:text-3xl font-semibold leading-tight">
            {(() => {
              const firstName = (user?.name || '').split(' ')[0];
              return firstName
                ? t('onboarding_lite.title_with_name', { name: firstName })
                : t('onboarding_lite.title');
            })()}
          </h1>
          <p className="text-sm text-muted-foreground leading-relaxed">
            {t('onboarding_lite.subtitle')}
          </p>
        </div>

        <form
          data-testid="onboarding-lite-form"
          onSubmit={handleSubmit}
          className="rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--surface-1))] p-6 md:p-8 space-y-6 shadow-lg"
        >
          {/* Country */}
          <div className="space-y-2">
            <Label className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Globe2 size={14} className="text-[hsl(var(--primary))]" />
              {t('onboarding_lite.country_label')}
            </Label>
            <p className="text-xs text-muted-foreground">{t('onboarding_lite.country_hint')}</p>
            <Select value={country} onValueChange={setCountry}>
              <SelectTrigger
                data-testid="onboarding-country-select"
                className="h-11 bg-[hsl(var(--surface-2))] border-[hsl(var(--border))]"
              >
                <SelectValue placeholder={t('onboarding_lite.country_placeholder')} />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {COUNTRIES.map((c) => (
                  <SelectItem key={c} value={c} data-testid={`onboarding-country-${c.replace(/\s+/g, '-').toLowerCase()}`}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Industry */}
          <div className="space-y-2">
            <Label className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Briefcase size={14} className="text-[hsl(var(--primary))]" />
              {t('onboarding_lite.industry_label')}
            </Label>
            <p className="text-xs text-muted-foreground">{t('onboarding_lite.industry_hint')}</p>
            <Select value={industry} onValueChange={setIndustry}>
              <SelectTrigger
                data-testid="onboarding-industry-select"
                className="h-11 bg-[hsl(var(--surface-2))] border-[hsl(var(--border))]"
              >
                <SelectValue placeholder={t('onboarding_lite.industry_placeholder')} />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {INDUSTRY_KEYS.map((k) => (
                  <SelectItem key={k} value={k} data-testid={`onboarding-industry-${k}`}>
                    {t(`onboarding_lite.industries.${k}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Company name */}
          <div className="space-y-2">
            <Label htmlFor="company_name" className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Building2 size={14} className="text-[hsl(var(--primary))]" />
              {t('onboarding_lite.company_label')}
            </Label>
            <p className="text-xs text-muted-foreground">{t('onboarding_lite.company_hint')}</p>
            <Input
              id="company_name"
              data-testid="onboarding-company-input"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder={t('onboarding_lite.company_placeholder')}
              disabled={submitting}
              className="h-11 bg-[hsl(var(--surface-2))] border-[hsl(var(--border))]"
            />
          </div>

          {error && (
            <div
              data-testid="onboarding-error"
              className="text-sm text-[hsl(var(--destructive))] bg-[hsl(var(--destructive)/0.08)] border border-[hsl(var(--destructive)/0.2)] rounded-md px-3 py-2"
            >
              {error}
            </div>
          )}

          <div className="pt-2 flex items-center justify-between gap-4">
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
              <ShieldCheck size={12} className="text-[hsl(var(--success))]" />
              <span>{t('auth.secured_by')}</span>
            </div>
            <Button
              data-testid="onboarding-submit-btn"
              type="submit"
              disabled={submitting || !canSubmit}
              className="h-11 px-6 bg-[hsl(var(--foreground))] text-[hsl(var(--background))] hover:bg-[hsl(var(--foreground)/0.9)]"
            >
              {submitting ? (
                <span className="flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" />
                  {t('onboarding_lite.saving')}
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  {t('onboarding_lite.continue_to_app')}
                  <ArrowRight size={14} />
                </span>
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
