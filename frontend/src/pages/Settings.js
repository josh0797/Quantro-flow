import React, { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Plug, Bot, Building2, Users, Loader2, Zap } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { INDUSTRIES } from '../config/industryConfig';
import { toast } from 'sonner';
import IntegrationsPanel from '../components/IntegrationsPanel';
import LanguageSwitcher from '../components/LanguageSwitcher';
import SimulationModeToggle from '../components/SimulationModeToggle';
import { useLanguage } from '../context/LanguageContext';

export default function Settings() {
  const { profile, updateProfile, refetch } = useBusinessProfile();
  const { t } = useLanguage();
  const [activeTab, setActiveTab] = useState('integrations');

  // Business Profile state
  const [profileForm, setProfileForm] = useState({
    industry: 'other',
    use_case: '',
    entity_labels: {
      contacts: 'Contacts',
      team_members: 'Team Members',
      meetings: 'Meetings',
      events: 'Events',
      services: 'Services'
    },
    simulation_mode: false
  });
  const [savingProfile, setSavingProfile] = useState(false);

  useEffect(() => {
    if (profile) {
      setProfileForm({
        industry: profile.industry || 'other',
        use_case: profile.use_case || '',
        entity_labels: profile.entity_labels || {
          contacts: 'Contacts',
          team_members: 'Team Members',
          meetings: 'Meetings',
          events: 'Events',
          services: 'Services'
        },
        simulation_mode: profile.simulation_mode || false
      });
    }
  }, [profile]);

  const saveBusinessProfile = async () => {
    try {
      setSavingProfile(true);
      await updateProfile(profileForm);
      toast.success(t('settings.profile.saved_toast'));
      refetch();
    } catch (error) {
      toast.error(t('settings.profile.save_failed_toast'));
    } finally {
      setSavingProfile(false);
    }
  };

  return (
    <div data-testid="settings-page" className="min-h-screen bg-[hsl(var(--background))] p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-[hsl(var(--primary)/0.1)]">
            <SettingsIcon size={24} className="text-[hsl(var(--primary))]" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-foreground">{t('settings.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('settings.subtitle')}</p>
          </div>
        </div>

        {/* Simulation Mode — first visible section before tabs */}
        <div data-testid="settings-simulation-banner">
          <SimulationModeToggle variant="banner" />
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid w-full grid-cols-4 bg-[hsl(var(--muted)/0.3)]">
            <TabsTrigger value="integrations" className="flex items-center gap-2">
              <Plug size={14} />
              <span>{t('settings.tabs.integrations')}</span>
            </TabsTrigger>
            <TabsTrigger value="automation" className="flex items-center gap-2">
              <Bot size={14} />
              <span>{t('settings.tabs.automation')}</span>
            </TabsTrigger>
            <TabsTrigger value="profile" className="flex items-center gap-2">
              <Building2 size={14} />
              <span>{t('settings.tabs.business_profile')}</span>
            </TabsTrigger>
            <TabsTrigger value="workspace" className="flex items-center gap-2">
              <Users size={14} />
              <span>{t('settings.tabs.workspace')}</span>
            </TabsTrigger>
          </TabsList>

          {/* Integrations Tab */}
          <TabsContent value="integrations" className="space-y-4 mt-6">
            <IntegrationsPanel />
          </TabsContent>

          {/* Automation Tab */}
          <TabsContent value="automation" className="space-y-4 mt-6">
            <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <h3 className="text-lg font-semibold text-foreground mb-4">{t('settings.automation.heading')}</h3>
              <p className="text-sm text-muted-foreground mb-6">
                {t('settings.automation.description')}
              </p>
              <Button 
                onClick={() => window.location.href = '/automation-policies'}
                data-testid="goto-automation-button"
              >
                <Bot size={16} className="mr-2" />
                {t('settings.automation.manage_button')}
              </Button>
            </Card>

            <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <h3 className="text-base font-semibold text-foreground mb-2">{t('settings.automation.overview_title')}</h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-[hsl(var(--success))]"></div>
                  <span className="text-muted-foreground">{t('settings.automation.overview_auto')}</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-[hsl(var(--warning))]"></div>
                  <span className="text-muted-foreground">{t('settings.automation.overview_manual')}</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-[hsl(var(--critical))]"></div>
                  <span className="text-muted-foreground">{t('settings.automation.overview_escalation')}</span>
                </div>
              </div>
            </Card>
          </TabsContent>

          {/* Business Profile Tab */}
          <TabsContent value="profile" className="space-y-4 mt-6">
            <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <h3 className="text-lg font-semibold text-foreground mb-1">Business Profile</h3>
              <p className="text-sm text-muted-foreground mb-6">
                Configure your business type and customize system terminology
              </p>

              <div className="space-y-4">
                {/* Industry Selector */}
                <div>
                  <Label htmlFor="industry">Industry</Label>
                  <Select 
                    value={profileForm.industry} 
                    onValueChange={v => setProfileForm({...profileForm, industry: v})}
                  >
                    <SelectTrigger id="industry" data-testid="industry-selector" className="mt-1 bg-[hsl(var(--background))]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INDUSTRIES.map(ind => (
                        <SelectItem key={ind.value} value={ind.value}>{ind.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="text-xs text-muted-foreground mt-1">
                    The system will adapt its language and AI suggestions based on your industry
                  </p>
                </div>

                {/* Use Case */}
                <div>
                  <Label htmlFor="use-case">Use Case (Optional)</Label>
                  <Textarea
                    id="use-case"
                    data-testid="use-case-input"
                    placeholder="Describe how you use this Business OS..."
                    value={profileForm.use_case}
                    onChange={e => setProfileForm({...profileForm, use_case: e.target.value})}
                    className="mt-1 bg-[hsl(var(--background))] resize-none"
                    rows={3}
                  />
                </div>

                {/* Custom Entity Naming */}
                <div className="border-t border-[hsl(var(--border))] pt-4 mt-6">
                  <h4 className="text-sm font-semibold text-foreground mb-3">Custom Entity Naming</h4>
                  <p className="text-xs text-muted-foreground mb-4">
                    Customize terminology throughout the system. Leave blank to use industry defaults.
                  </p>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label htmlFor="label-contacts" className="text-xs">Contacts Label</Label>
                      <Input
                        id="label-contacts"
                        data-testid="label-contacts-input"
                        placeholder="Contacts"
                        value={profileForm.entity_labels.contacts}
                        onChange={e => setProfileForm({
                          ...profileForm,
                          entity_labels: {...profileForm.entity_labels, contacts: e.target.value}
                        })}
                        className="mt-1 bg-[hsl(var(--background))]"
                      />
                    </div>

                    <div>
                      <Label htmlFor="label-team" className="text-xs">Team Members Label</Label>
                      <Input
                        id="label-team"
                        data-testid="label-team-input"
                        placeholder="Team Members"
                        value={profileForm.entity_labels.team_members}
                        onChange={e => setProfileForm({
                          ...profileForm,
                          entity_labels: {...profileForm.entity_labels, team_members: e.target.value}
                        })}
                        className="mt-1 bg-[hsl(var(--background))]"
                      />
                    </div>

                    <div>
                      <Label htmlFor="label-meetings" className="text-xs">Meetings Label</Label>
                      <Input
                        id="label-meetings"
                        data-testid="label-meetings-input"
                        placeholder="Meetings"
                        value={profileForm.entity_labels.meetings}
                        onChange={e => setProfileForm({
                          ...profileForm,
                          entity_labels: {...profileForm.entity_labels, meetings: e.target.value}
                        })}
                        className="mt-1 bg-[hsl(var(--background))]"
                      />
                    </div>

                    <div>
                      <Label htmlFor="label-events" className="text-xs">Events Label</Label>
                      <Input
                        id="label-events"
                        data-testid="label-events-input"
                        placeholder="Events"
                        value={profileForm.entity_labels.events}
                        onChange={e => setProfileForm({
                          ...profileForm,
                          entity_labels: {...profileForm.entity_labels, events: e.target.value}
                        })}
                        className="mt-1 bg-[hsl(var(--background))]"
                      />
                    </div>

                    <div className="col-span-2">
                      <Label htmlFor="label-services" className="text-xs">Services/Products Label</Label>
                      <Input
                        id="label-services"
                        data-testid="label-services-input"
                        placeholder="Services"
                        value={profileForm.entity_labels.services}
                        onChange={e => setProfileForm({
                          ...profileForm,
                          entity_labels: {...profileForm.entity_labels, services: e.target.value}
                        })}
                        className="mt-1 bg-[hsl(var(--background))]"
                      />
                    </div>
                  </div>
                </div>

                {/* Simulation Mode is now controlled from the banner at the top of Settings
                    and the Sidebar footer toggle — no duplicate form control here. */}

                {/* Save Button */}
                <div className="flex justify-end pt-4">
                  <Button 
                    onClick={saveBusinessProfile}
                    disabled={savingProfile}
                    data-testid="save-profile-button"
                  >
                    {savingProfile ? (
                      <>
                        <Loader2 className="animate-spin mr-2" size={14} />
                        {t('settings.profile.saving')}
                      </>
                    ) : (
                      t('settings.profile.save_button')
                    )}
                  </Button>
                </div>
              </div>
            </Card>
          </TabsContent>

          {/* Workspace Tab */}
          <TabsContent value="workspace" className="space-y-4 mt-6">
            <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <h3 className="text-lg font-semibold text-foreground mb-1">{t('settings.workspace.heading')}</h3>
              <p className="text-sm text-muted-foreground mb-6">
                {t('settings.workspace.description')}
              </p>

              <div className="space-y-4">
                <div>
                  <Label htmlFor="workspace-name">{t('settings.workspace.name_label')}</Label>
                  <Input
                    id="workspace-name"
                    data-testid="workspace-name-input"
                    placeholder={t('settings.workspace.name_placeholder')}
                    defaultValue="Default Workspace"
                    className="mt-1 bg-[hsl(var(--background))]"
                  />
                </div>

                <div className="pt-2">
                  <LanguageSwitcher />
                </div>

                <div className="border-t border-[hsl(var(--border))] pt-4">
                  <p className="text-xs text-muted-foreground">
                    {t('settings.workspace.phase_note')}
                  </p>
                </div>
              </div>
            </Card>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
