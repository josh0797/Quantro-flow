import React, { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Plug, Bot, Building2, Users, CheckCircle2, XCircle, Loader2, RefreshCw, Zap } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { useBusinessProfile } from '../contexts/BusinessProfileContext';
import { INDUSTRIES } from '../config/industryConfig';
import { toast } from 'sonner';

export default function Settings() {
  const { profile, updateProfile, refetch } = useBusinessProfile();
  const [activeTab, setActiveTab] = useState('integrations');
  
  // Integrations state
  const [integrations, setIntegrations] = useState([]);
  const [loadingIntegrations, setLoadingIntegrations] = useState(true);
  const [testingConnection, setTestingConnection] = useState(null);
  const [crmApiKey, setCrmApiKey] = useState('');
  const [crmBaseUrl, setCrmBaseUrl] = useState('');
  
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
        entity_labels: profile.entity_labels || profileForm.entity_labels,
        simulation_mode: profile.simulation_mode || false
      });
    }
  }, [profile]);

  useEffect(() => {
    if (activeTab === 'integrations') {
      fetchIntegrations();
    }
  }, [activeTab]);

  const fetchIntegrations = async () => {
    try {
      setLoadingIntegrations(true);
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const response = await fetch(`${backendUrl}/api/integrations`);
      if (response.ok) {
        const data = await response.json();
        setIntegrations(data);
      }
    } catch (error) {
      console.error('Failed to fetch integrations:', error);
      toast.error('Failed to load integrations');
    } finally {
      setLoadingIntegrations(false);
    }
  };

  const testIntegration = async (provider) => {
    try {
      setTestingConnection(provider);
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const response = await fetch(`${backendUrl}/api/integrations/${provider}/test`, {
        method: 'POST'
      });
      const result = await response.json();
      
      if (result.success) {
        toast.success(result.message);
      } else {
        toast.error(result.message);
      }
    } catch (error) {
      toast.error('Connection test failed');
    } finally {
      setTestingConnection(null);
    }
  };

  const updateIntegration = async (provider, status, config = {}) => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const response = await fetch(`${backendUrl}/api/integrations/${provider}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, config })
      });
      
      if (response.ok) {
        toast.success(`${provider} integration updated`);
        fetchIntegrations();
      }
    } catch (error) {
      toast.error('Failed to update integration');
    }
  };

  const saveBusinessProfile = async () => {
    try {
      setSavingProfile(true);
      await updateProfile(profileForm);
      toast.success('Business Profile updated successfully');
      refetch();
    } catch (error) {
      toast.error('Failed to update Business Profile');
    } finally {
      setSavingProfile(false);
    }
  };

  const getIntegrationIcon = (provider) => {
    const integration = integrations.find(i => i.provider === provider);
    if (!integration) return null;
    
    const isConnected = integration.status === 'connected';
    return isConnected ? (
      <CheckCircle2 size={16} className="text-[hsl(var(--success))]" />
    ) : (
      <XCircle size={16} className="text-[hsl(var(--muted-foreground))]" />
    );
  };

  const getIntegration = (provider) => {
    return integrations.find(i => i.provider === provider);
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
            <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
            <p className="text-sm text-muted-foreground">Configure your Business OS</p>
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <TabsList className="grid w-full grid-cols-4 bg-[hsl(var(--muted)/0.3)]">
            <TabsTrigger value="integrations" className="flex items-center gap-2">
              <Plug size={14} />
              <span>Integrations</span>
            </TabsTrigger>
            <TabsTrigger value="automation" className="flex items-center gap-2">
              <Bot size={14} />
              <span>Automation</span>
            </TabsTrigger>
            <TabsTrigger value="profile" className="flex items-center gap-2">
              <Building2 size={14} />
              <span>Business Profile</span>
            </TabsTrigger>
            <TabsTrigger value="workspace" className="flex items-center gap-2">
              <Users size={14} />
              <span>Workspace</span>
            </TabsTrigger>
          </TabsList>

          {/* Integrations Tab */}
          <TabsContent value="integrations" className="space-y-4 mt-6">
            {loadingIntegrations ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="animate-spin text-muted-foreground" size={32} />
              </div>
            ) : (
              <>
                {/* Gmail Integration */}
                {(() => {
                  const gmail = getIntegration('gmail');
                  if (!gmail) return null;
                  return (
                    <Card data-testid="gmail-integration-card" className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
                      <div className="flex items-start justify-between">
                        <div className="space-y-3 flex-1">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center text-white font-semibold">
                              G
                            </div>
                            <div>
                              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                                Gmail
                                {getIntegrationIcon('gmail')}
                              </h3>
                              <p className="text-xs text-muted-foreground">Connect your Gmail account to sync inbox items</p>
                            </div>
                          </div>
                          
                          <div className="flex items-center gap-2">
                            <Badge className={gmail.status === 'connected' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]'}>
                              {gmail.status === 'connected' ? 'Connected' : 'Not Connected'}
                            </Badge>
                            {gmail.last_sync_at && (
                              <span className="text-xs text-muted-foreground">
                                Last sync: {new Date(gmail.last_sync_at).toLocaleString()}
                              </span>
                            )}
                          </div>

                          <div className="flex gap-2">
                            {gmail.status === 'connected' ? (
                              <>
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  onClick={() => testIntegration('gmail')}
                                  disabled={testingConnection === 'gmail'}
                                  data-testid="test-gmail-button"
                                >
                                  {testingConnection === 'gmail' ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                                  <span className="ml-2">Test Connection</span>
                                </Button>
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  onClick={() => updateIntegration('gmail', 'disconnected')}
                                  data-testid="disconnect-gmail-button"
                                >
                                  Disconnect
                                </Button>
                              </>
                            ) : (
                              <Button 
                                size="sm"
                                onClick={() => updateIntegration('gmail', 'connected', { email: 'user@example.com' })}
                                data-testid="connect-gmail-button"
                              >
                                <Plug size={14} className="mr-2" />
                                Connect Gmail
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    </Card>
                  );
                })()}

                {/* Google Calendar Integration */}
                {(() => {
                  const calendar = getIntegration('google_calendar');
                  if (!calendar) return null;
                  return (
                    <Card data-testid="calendar-integration-card" className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
                      <div className="flex items-start justify-between">
                        <div className="space-y-3 flex-1">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center text-white font-semibold">
                              📅
                            </div>
                            <div>
                              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                                Google Calendar
                                {getIntegrationIcon('google_calendar')}
                              </h3>
                              <p className="text-xs text-muted-foreground">Sync your calendar for automated scheduling</p>
                            </div>
                          </div>
                          
                          <div className="flex items-center gap-2">
                            <Badge className={calendar.status === 'connected' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]'}>
                              {calendar.status === 'connected' ? 'Connected' : 'Not Connected'}
                            </Badge>
                            {calendar.last_sync_at && (
                              <span className="text-xs text-muted-foreground">
                                Last sync: {new Date(calendar.last_sync_at).toLocaleString()}
                              </span>
                            )}
                          </div>

                          <div className="flex gap-2">
                            {calendar.status === 'connected' ? (
                              <>
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  onClick={() => testIntegration('google_calendar')}
                                  disabled={testingConnection === 'google_calendar'}
                                  data-testid="test-calendar-button"
                                >
                                  {testingConnection === 'google_calendar' ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                                  <span className="ml-2">Test Connection</span>
                                </Button>
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  onClick={() => updateIntegration('google_calendar', 'disconnected')}
                                  data-testid="disconnect-calendar-button"
                                >
                                  Disconnect
                                </Button>
                              </>
                            ) : (
                              <Button 
                                size="sm"
                                onClick={() => updateIntegration('google_calendar', 'connected', { calendar_id: 'primary' })}
                                data-testid="connect-calendar-button"
                              >
                                <Plug size={14} className="mr-2" />
                                Connect Calendar
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    </Card>
                  );
                })()}

                {/* CRM Integration */}
                {(() => {
                  const crm = getIntegration('crm');
                  if (!crm) return null;
                  return (
                    <Card data-testid="crm-integration-card" className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
                      <div className="flex items-start justify-between">
                        <div className="space-y-3 flex-1">
                          <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center text-white font-semibold">
                              CRM
                            </div>
                            <div>
                              <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
                                CRM System
                                {getIntegrationIcon('crm')}
                              </h3>
                              <p className="text-xs text-muted-foreground">Connect your CRM (GoHighLevel, HubSpot, etc.)</p>
                            </div>
                          </div>
                          
                          <div className="flex items-center gap-2">
                            <Badge className={crm.status === 'connected' ? 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]' : 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]'}>
                              {crm.status === 'connected' ? 'Connected' : 'Not Connected'}
                            </Badge>
                            {crm.last_sync_at && (
                              <span className="text-xs text-muted-foreground">
                                Last sync: {new Date(crm.last_sync_at).toLocaleString()}
                              </span>
                            )}
                          </div>

                          {crm.status !== 'connected' && (
                            <div className="space-y-2">
                              <div>
                                <Label className="text-xs">API Key</Label>
                                <Input 
                                  placeholder="Enter your CRM API key" 
                                  type="password"
                                  value={crmApiKey}
                                  onChange={(e) => setCrmApiKey(e.target.value)}
                                  className="bg-[hsl(var(--background))] mt-1"
                                  data-testid="crm-api-key-input"
                                />
                              </div>
                              <div>
                                <Label className="text-xs">Base URL (optional)</Label>
                                <Input 
                                  placeholder="https://api.yourcrm.com" 
                                  value={crmBaseUrl}
                                  onChange={(e) => setCrmBaseUrl(e.target.value)}
                                  className="bg-[hsl(var(--background))] mt-1"
                                  data-testid="crm-url-input"
                                />
                              </div>
                            </div>
                          )}

                          <div className="flex gap-2">
                            {crm.status === 'connected' ? (
                              <>
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  onClick={() => testIntegration('crm')}
                                  disabled={testingConnection === 'crm'}
                                  data-testid="test-crm-button"
                                >
                                  {testingConnection === 'crm' ? <Loader2 className="animate-spin" size={14} /> : <RefreshCw size={14} />}
                                  <span className="ml-2">Test Connection</span>
                                </Button>
                                <Button 
                                  variant="outline" 
                                  size="sm"
                                  onClick={() => updateIntegration('crm', 'disconnected')}
                                  data-testid="disconnect-crm-button"
                                >
                                  Disconnect
                                </Button>
                              </>
                            ) : (
                              <Button 
                                size="sm"
                                onClick={() => updateIntegration('crm', 'connected', { 
                                  api_key: crmApiKey || 'simulation_key',
                                  base_url: crmBaseUrl || ''
                                })}
                                disabled={!crmApiKey && !crmBaseUrl}
                                data-testid="connect-crm-button"
                              >
                                <Plug size={14} className="mr-2" />
                                Connect CRM
                              </Button>
                            )}
                          </div>
                        </div>
                      </div>
                    </Card>
                  );
                })()}
              </>
            )}
          </TabsContent>

          {/* Automation Tab */}
          <TabsContent value="automation" className="space-y-4 mt-6">
            <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <h3 className="text-lg font-semibold text-foreground mb-4">Automation Settings</h3>
              <p className="text-sm text-muted-foreground mb-6">
                Configure your automation policies, confidence thresholds, and escalation rules.
              </p>
              <Button 
                onClick={() => window.location.href = '/automation-policies'}
                data-testid="goto-automation-button"
              >
                <Bot size={16} className="mr-2" />
                Manage Automation Policies
              </Button>
            </Card>

            <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <h3 className="text-base font-semibold text-foreground mb-2">Quick Overview</h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-[hsl(var(--success))]"></div>
                  <span className="text-muted-foreground">Auto-run enabled for high-confidence items</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-[hsl(var(--warning))]"></div>
                  <span className="text-muted-foreground">Manual approval required for medium confidence</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-[hsl(var(--critical))]"></div>
                  <span className="text-muted-foreground">Escalation triggered for low confidence or conflicts</span>
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

                {/* Simulation Mode */}
                <div className="border-t border-[hsl(var(--border))] pt-6 mt-6">
                  <div className="flex items-start justify-between gap-4 p-4 rounded-lg bg-[hsl(var(--warning)/0.05)] border border-[hsl(var(--warning)/0.2)]">
                    <div className="flex items-start gap-3 flex-1">
                      <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-[hsl(var(--warning)/0.15)] shrink-0">
                        <Zap size={18} className="text-[hsl(var(--warning))]" />
                      </div>
                      <div className="flex-1">
                        <h4 className="text-sm font-semibold text-foreground mb-1">Simulation Mode</h4>
                        <p className="text-xs text-muted-foreground">
                          Load realistic sample operational data for your selected industry. Perfect for testing workflows, validating automations, and demoing the system before connecting live integrations.
                        </p>
                        {profileForm.simulation_mode && (
                          <p className="text-xs text-[hsl(var(--warning))] mt-2">
                            ⚡ Active: The system is populated with simulated data
                          </p>
                        )}
                      </div>
                    </div>
                    <Switch
                      checked={profileForm.simulation_mode}
                      onCheckedChange={checked => setProfileForm({...profileForm, simulation_mode: checked})}
                      data-testid="simulation-mode-toggle"
                    />
                  </div>
                </div>

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
                        Saving...
                      </>
                    ) : (
                      'Save Business Profile'
                    )}
                  </Button>
                </div>
              </div>
            </Card>
          </TabsContent>

          {/* Workspace Tab */}
          <TabsContent value="workspace" className="space-y-4 mt-6">
            <Card className="p-6 bg-[hsl(var(--card))] border-[hsl(var(--border))]">
              <h3 className="text-lg font-semibold text-foreground mb-1">Workspace</h3>
              <p className="text-sm text-muted-foreground mb-6">
                Workspace settings and team management
              </p>

              <div className="space-y-4">
                <div>
                  <Label htmlFor="workspace-name">Workspace Name</Label>
                  <Input
                    id="workspace-name"
                    data-testid="workspace-name-input"
                    placeholder="My Business"
                    defaultValue="Default Workspace"
                    className="mt-1 bg-[hsl(var(--background))]"
                  />
                </div>

                <div className="border-t border-[hsl(var(--border))] pt-4">
                  <p className="text-xs text-muted-foreground">
                    Authentication and multi-tenant workspace features will be available in Phase 6.
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
