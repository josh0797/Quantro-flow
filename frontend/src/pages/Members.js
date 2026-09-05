import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Skeleton } from '../components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
  DialogDescription,
} from '../components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader,
  AlertDialogTitle,
} from '../components/ui/alert-dialog';
import { Users, UserPlus, Copy, Trash2, Shield, Crown, Loader2, Link2, ClipboardList, History, CheckCircle2, Clock, Mail, UserCheck, Building2, KeyRound, AlertCircle, Download, FileJson, FileSpreadsheet, Pencil } from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
  DropdownMenuLabel, DropdownMenuSeparator,
} from '../components/ui/dropdown-menu';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import {
  listMembers, updateMemberRole, removeMember,
  listInvites, createInvite, revokeInvite,
  getOnboarding, markOnboardingComplete,
  getAuditLog, exportAuditLog, renameWorkspace,
} from '../lib/api';

const ROLE_RANK = { viewer: 1, member: 2, accountant: 3, leader: 4, owner: 5 };
const ROLE_OPTIONS = ['viewer', 'member', 'accountant', 'leader', 'owner'];

function roleBadgeClass(role) {
  switch (role) {
    case 'owner':
      return 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]';
    case 'leader':
      return 'bg-[hsl(var(--accent)/0.15)] text-[hsl(var(--accent))]';
    case 'accountant':
      return 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]';
    case 'member':
      return 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]';
    default:
      return 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]';
  }
}

export default function Members() {
  const { t } = useLanguage();
  const { user, currentWorkspaceId, workspaces, refresh } = useAuth();
  const [data, setData] = useState({ members: [], your_role: 'viewer' });
  const [invites, setInvites] = useState([]);
  const [onboarding, setOnboarding] = useState(null);
  const [auditEvents, setAuditEvents] = useState(null);
  const [activeTab, setActiveTab] = useState('members');
  const [loading, setLoading] = useState(true);
  const [creatingInvite, setCreatingInvite] = useState(false);
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [inviteForm, setInviteForm] = useState({ role: 'member', max_uses: 1, expires_in_days: 7, email: '', full_name: '' });
  const [pendingRemoval, setPendingRemoval] = useState(null);
  const [pendingRevoke, setPendingRevoke] = useState(null);
  const [pendingComplete, setPendingComplete] = useState(null);
  const [auditFilters, setAuditFilters] = useState({ start_date: '', end_date: '', action: '' });
  const [exporting, setExporting] = useState(false);
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [renaming, setRenaming] = useState(false);

  const myRoleRank = ROLE_RANK[data.your_role] || 0;
  const isAdmin = myRoleRank >= ROLE_RANK.leader;
  const isOwner = data.your_role === 'owner';

  const fetchData = useCallback(async () => {
    if (!currentWorkspaceId) return;
    try {
      const [membersRes, invitesRes] = await Promise.all([
        listMembers(currentWorkspaceId),
        // Invites endpoint requires admin — gracefully degrade if forbidden.
        listInvites(currentWorkspaceId).catch((err) => {
          if (err?.response?.status === 403) return { invites: [] };
          throw err;
        }),
      ]);
      setData(membersRes);
      setInvites(invitesRes?.invites || []);
    } catch (err) {
      toast.error('Could not load members', { description: err?.response?.data?.detail || err.message });
    } finally {
      setLoading(false);
    }
  }, [currentWorkspaceId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Lazy-load Onboarding the first time the user opens that tab.
  useEffect(() => {
    if (activeTab !== 'onboarding' || onboarding) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getOnboarding(currentWorkspaceId);
        if (!cancelled) setOnboarding(res);
      } catch (err) {
        toast.error('Could not load onboarding', { description: err?.response?.data?.detail || err.message });
      }
    })();
    return () => { cancelled = true; };
  }, [activeTab, onboarding, currentWorkspaceId]);

  // Lazy-load the Audit timeline (leader+ only — silently skipped for
  // lower roles since the tab itself isn't rendered).
  useEffect(() => {
    if (activeTab !== 'audit' || auditEvents) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getAuditLog(currentWorkspaceId, { limit: 200 });
        if (!cancelled) setAuditEvents(res?.events || []);
      } catch (err) {
        const detail = err?.response?.data?.detail;
        const msg = typeof detail === 'string' ? detail : detail?.message || err.message;
        toast.error('Could not load audit log', { description: msg });
      }
    })();
    return () => { cancelled = true; };
  }, [activeTab, auditEvents, currentWorkspaceId]);

  // Audit export (CSV/JSON) — triggers a browser download and records the
  // action in the audit trail itself (via the backend). Applies the same
  // filters the user has in the UI.
  const handleExportAudit = useCallback(async (format) => {
    if (!currentWorkspaceId) return;
    setExporting(true);
    try {
      const params = { format };
      if (auditFilters.start_date) params.start_date = auditFilters.start_date;
      if (auditFilters.end_date) params.end_date = auditFilters.end_date;
      if (auditFilters.action) params.action = auditFilters.action;
      const { blob, filename } = await exportAuditLog(currentWorkspaceId, params);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success(t('audit.export_success', { format: format.toUpperCase() }));
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || err.message;
      toast.error(t('audit.export_error'), { description: msg });
    } finally {
      setExporting(false);
    }
  }, [currentWorkspaceId, auditFilters, t]);

  // Rename the active workspace. Leader+ only on the backend, but we also
  // gate the UI entry point so regular members never see the edit affordance.
  const currentWs = useMemo(
    () => (workspaces || []).find((w) => w.workspace_id === currentWorkspaceId) || null,
    [workspaces, currentWorkspaceId],
  );
  const openRenameDialog = useCallback(() => {
    setRenameValue(currentWs?.name || '');
    setRenameDialogOpen(true);
  }, [currentWs]);
  const handleRenameWorkspace = useCallback(async () => {
    const name = (renameValue || '').trim();
    if (!name) {
      toast.error(t('workspace.rename_empty'));
      return;
    }
    if (name === (currentWs?.name || '')) {
      setRenameDialogOpen(false);
      return;
    }
    setRenaming(true);
    try {
      await renameWorkspace(currentWorkspaceId, name);
      toast.success(t('workspace.rename_success', { name }));
      setRenameDialogOpen(false);
      // Pull fresh workspace metadata into the AuthContext so the sidebar
      // switcher reflects the new name without a full reload.
      await refresh?.();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || err.message;
      toast.error(t('workspace.rename_error'), { description: msg });
    } finally {
      setRenaming(false);
    }
  }, [renameValue, currentWs, currentWorkspaceId, refresh, t]);

  const handleMarkOnboardingComplete = async () => {
    if (!pendingComplete) return;
    try {
      await markOnboardingComplete(currentWorkspaceId, pendingComplete.user_id);
      toast.success(t('onboarding.action_mark_complete'));
      setOnboarding(null); // force re-fetch
      setPendingComplete(null);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Action failed';
      toast.error(msg);
      setPendingComplete(null);
    }
  };

  const handleCopyMostRecentInvite = async (memberCard) => {
    // Best-effort: find the most recent active invite that this member
    // accepted (or any active one if none match) and copy its URL.
    const invite = invites.find((inv) => !inv.revoked && inv.url);
    if (!invite?.url) {
      toast.error(t('onboarding.action_copy_invite'));
      return;
    }
    try {
      await navigator.clipboard.writeText(invite.url);
      toast.success(t('members.invite_link_copied'));
    } catch {
      toast.error('Copy failed');
    }
  };

  const handleRoleChange = async (member, newRole) => {
    if (newRole === member.role) return;
    if (['leader', 'owner'].includes(newRole) && !isOwner) {
      toast.error(t('members.not_owner_promotion'));
      return;
    }
    try {
      await updateMemberRole(currentWorkspaceId, member.user_id, newRole);
      toast.success(t('members.change_role'));
      fetchData();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Action failed';
      toast.error(msg);
    }
  };

  const handleRemove = async () => {
    if (!pendingRemoval) return;
    try {
      await removeMember(currentWorkspaceId, pendingRemoval.user_id);
      toast.success(t('members.remove_member'));
      setPendingRemoval(null);
      fetchData();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Action failed';
      toast.error(msg);
      setPendingRemoval(null);
    }
  };

  const handleCreateInvite = async () => {
    setCreatingInvite(true);
    try {
      const result = await createInvite(currentWorkspaceId, inviteForm);
      toast.success(t('members.invite_link_created'));
      // Best-effort copy
      if (result?.url) {
        try { await navigator.clipboard.writeText(result.url); } catch { /* noop */ }
        toast.message(t('members.invite_link_copied'), { description: result.url });
      }
      setInviteDialogOpen(false);
      fetchData();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Action failed';
      toast.error(msg);
    } finally {
      setCreatingInvite(false);
    }
  };

  const handleRevokeInvite = async () => {
    if (!pendingRevoke) return;
    try {
      await revokeInvite(currentWorkspaceId, pendingRevoke.invite_id);
      toast.success(t('members.revoked'));
      setPendingRevoke(null);
      fetchData();
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Action failed';
      toast.error(msg);
      setPendingRevoke(null);
    }
  };

  const handleCopyInvite = async (invite) => {
    if (!invite?.url) return;
    try {
      await navigator.clipboard.writeText(invite.url);
      toast.success(t('members.invite_link_copied'));
    } catch {
      toast.error('Copy failed');
    }
  };

  const activeInvites = useMemo(
    () => invites.filter((i) => !i.revoked && (i.used_count || 0) < (i.max_uses || 1)),
    [invites],
  );

  if (loading) {
    return (
      <div className="page-container relative z-[1]">
        <Skeleton className="h-8 w-48 mb-6" />
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }

  return (
    <div className="page-container relative z-[1]" data-testid="members-page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">{t('members.title')}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t('members.subtitle')}</p>
          {/* Current workspace pill — with inline rename for leader+. Gives
              every tenant an obvious path to customize the default name. */}
          {currentWs && (
            <div className="mt-3 inline-flex items-center gap-2 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted)/0.3)] px-3 py-1.5 text-sm">
              <Building2 size={14} className="text-[hsl(var(--primary))]" />
              <span className="font-medium" data-testid="workspace-name">{currentWs.name}</span>
              {isAdmin && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 hover:bg-[hsl(var(--muted))]"
                  onClick={openRenameDialog}
                  data-testid="workspace-rename-btn"
                  aria-label={t('workspace.rename_button')}
                >
                  <Pencil size={12} />
                </Button>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          <Badge className={`${roleBadgeClass(data.your_role)} capitalize`} data-testid="my-role-badge">
            {t('members.your_role')}: {t(`members.role_${data.your_role}`)}
          </Badge>
        </div>
      </div>

      <Tabs defaultValue="members" onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="members" data-testid="tab-members">
            <Users size={14} className="mr-1.5" />
            {t('members.tab_members')} · {data.members.length}
          </TabsTrigger>
          {isAdmin && (
            <TabsTrigger value="invites" data-testid="tab-invites">
              <Link2 size={14} className="mr-1.5" />
              {t('members.tab_invites')} · {activeInvites.length}
            </TabsTrigger>
          )}
          <TabsTrigger value="onboarding" data-testid="tab-onboarding">
            <ClipboardList size={14} className="mr-1.5" />
            {t('onboarding.tab_label')}
          </TabsTrigger>
          {isAdmin && (
            <TabsTrigger value="audit" data-testid="tab-audit">
              <History size={14} className="mr-1.5" />
              {t('audit.tab_label')}
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="members" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">{t('members.member_count', { count: data.members.length })}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {data.members.map((m) => {
                const isMe = m.user_id === user?.user_id;
                const memberRoleRank = ROLE_RANK[m.role] || 0;
                // Allow editing only if I'm admin+, target isn't me-as-owner,
                // and (target is below admin OR I am owner).
                const canEdit = isAdmin && !(isMe && m.role === 'owner') && (memberRoleRank < ROLE_RANK.leader || isOwner);
                const canRemove = (isMe && m.role !== 'owner') || (isAdmin && memberRoleRank < ROLE_RANK.owner && (memberRoleRank < ROLE_RANK.leader || isOwner));

                return (
                  <div
                    key={m.user_id}
                    data-testid={`member-row-${m.user_id}`}
                    className="flex items-center gap-3 p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]"
                  >
                    <div className="w-9 h-9 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] flex items-center justify-center text-sm font-semibold shrink-0 overflow-hidden">
                      {m.picture ? (
                        <img src={m.picture} alt={m.name} className="w-full h-full object-cover" />
                      ) : (
                        (m.name || m.email || '?').slice(0, 1).toUpperCase()
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium truncate">
                          {m.name || m.email || m.user_id}
                          {isMe && <span className="text-xs text-muted-foreground ml-1.5">(you)</span>}
                        </p>
                        {m.role === 'owner' && <Crown size={12} className="text-[hsl(var(--primary))]" />}
                      </div>
                      <p className="text-xs text-muted-foreground truncate">{m.email}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {canEdit ? (
                        <Select value={m.role} onValueChange={(v) => handleRoleChange(m, v)}>
                          <SelectTrigger className="h-8 w-[130px]" data-testid={`role-select-${m.user_id}`}>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {ROLE_OPTIONS.map((r) => (
                              <SelectItem key={r} value={r} disabled={['leader', 'owner'].includes(r) && !isOwner}>
                                {t(`members.role_${r}`)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <Badge className={`${roleBadgeClass(m.role)} capitalize`}>{t(`members.role_${m.role}`)}</Badge>
                      )}
                      {canRemove && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.1)]"
                          onClick={() => setPendingRemoval(m)}
                          data-testid={`remove-member-${m.user_id}`}
                        >
                          <Trash2 size={14} />
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        </TabsContent>

        {isAdmin && (
          <TabsContent value="invites" className="mt-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle className="text-sm">
                  {t('members.pending_count', { count: activeInvites.length })}
                </CardTitle>
                <Button size="sm" onClick={() => setInviteDialogOpen(true)} data-testid="new-invite-btn">
                  <UserPlus size={14} className="mr-1.5" />
                  {t('members.generate_invite')}
                </Button>
              </CardHeader>
              <CardContent className="space-y-2">
                {invites.length === 0 ? (
                  <div className="py-10 text-center">
                    <Shield size={28} className="mx-auto text-muted-foreground/50 mb-3" />
                    <p className="text-sm text-muted-foreground">{t('members.empty_invites')}</p>
                  </div>
                ) : (
                  invites.map((inv) => (
                    <div
                      key={inv.invite_id}
                      data-testid={`invite-row-${inv.invite_id}`}
                      className="flex items-center gap-3 p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <Badge className={`${roleBadgeClass(inv.role)} capitalize`}>
                            {t(`members.role_${inv.role}`)}
                          </Badge>
                          {inv.revoked && (
                            <Badge className="bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]">
                              {t('members.revoked')}
                            </Badge>
                          )}
                          <span className="text-xs text-muted-foreground">
                            {(inv.used_count || 0)}/{inv.max_uses} used
                          </span>
                        </div>
                        {inv.url && (
                          <p className="text-[11px] font-mono text-muted-foreground truncate mt-1">
                            {inv.url}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleCopyInvite(inv)}
                          disabled={inv.revoked || !inv.url}
                          data-testid={`copy-invite-${inv.invite_id}`}
                        >
                          <Copy size={14} className="mr-1" /> {t('members.copy_link')}
                        </Button>
                        {!inv.revoked && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-[hsl(var(--destructive))]"
                            onClick={() => setPendingRevoke(inv)}
                            data-testid={`revoke-invite-${inv.invite_id}`}
                          >
                            <Trash2 size={14} />
                          </Button>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* Onboarding tab — checklist + progress per member */}
        <TabsContent value="onboarding" className="mt-4">
          {!onboarding ? (
            <Card>
              <CardContent className="py-8">
                <Skeleton className="h-32 w-full" />
              </CardContent>
            </Card>
          ) : onboarding.members.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <ClipboardList size={28} className="mx-auto text-muted-foreground/50 mb-3" />
                <p className="text-sm text-muted-foreground">{t('onboarding.empty')}</p>
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="mb-4 text-xs text-muted-foreground" data-testid="onboarding-summary">
                {t('onboarding.summary', {
                  completed: onboarding.summary.completed_onboarding,
                  total: onboarding.summary.total_members,
                })}
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {onboarding.members.map((card) => (
                  <OnboardingCard
                    key={card.user_id}
                    card={card}
                    isAdmin={isAdmin}
                    t={t}
                    onMarkComplete={() => setPendingComplete(card)}
                    onCopyInvite={() => handleCopyMostRecentInvite(card)}
                    onRevokeAccess={() => setPendingRemoval({ user_id: card.user_id, role: card.role })}
                  />
                ))}
              </div>
            </>
          )}
        </TabsContent>

        {/* Audit tab — append-only timeline (leader+ only) */}
        {isAdmin && (
          <TabsContent value="audit" className="mt-4">
            {/* Toolbar: filters + export. Always visible (even when empty) so
                compliance users can still export an empty range snapshot. */}
            <div
              className="mb-4 flex flex-col gap-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-3 md:flex-row md:items-end md:justify-between"
              data-testid="audit-toolbar"
            >
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 md:flex-1">
                <div className="space-y-1">
                  <Label htmlFor="audit-start" className="text-xs text-muted-foreground">
                    {t('audit.filter_start_date')}
                  </Label>
                  <Input
                    id="audit-start"
                    type="date"
                    value={auditFilters.start_date}
                    onChange={(e) => setAuditFilters((f) => ({ ...f, start_date: e.target.value }))}
                    data-testid="audit-filter-start"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="audit-end" className="text-xs text-muted-foreground">
                    {t('audit.filter_end_date')}
                  </Label>
                  <Input
                    id="audit-end"
                    type="date"
                    value={auditFilters.end_date}
                    onChange={(e) => setAuditFilters((f) => ({ ...f, end_date: e.target.value }))}
                    data-testid="audit-filter-end"
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="audit-action" className="text-xs text-muted-foreground">
                    {t('audit.filter_action')}
                  </Label>
                  <Select
                    value={auditFilters.action || 'all'}
                    onValueChange={(v) => setAuditFilters((f) => ({ ...f, action: v === 'all' ? '' : v }))}
                  >
                    <SelectTrigger id="audit-action" data-testid="audit-filter-action">
                      <SelectValue placeholder={t('audit.filter_action_all')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">{t('audit.filter_action_all')}</SelectItem>
                      <SelectItem value="role_changed">{t('audit.action_role_changed')}</SelectItem>
                      <SelectItem value="invitation_created">{t('audit.action_invitation_created')}</SelectItem>
                      <SelectItem value="invitation_accepted">{t('audit.action_invitation_accepted')}</SelectItem>
                      <SelectItem value="access_revoked">{t('audit.action_access_revoked')}</SelectItem>
                      <SelectItem value="onboarding_completed">{t('audit.action_onboarding_completed')}</SelectItem>
                      <SelectItem value="added">{t('audit.action_added')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="default"
                    disabled={exporting}
                    className="gap-2 self-start md:self-auto"
                    data-testid="audit-export-btn"
                  >
                    {exporting ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Download size={16} />
                    )}
                    {t('audit.export_button')}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuLabel>{t('audit.export_menu_label')}</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => handleExportAudit('csv')}
                    data-testid="audit-export-csv"
                    className="cursor-pointer"
                  >
                    <FileSpreadsheet size={16} className="mr-2" />
                    {t('audit.export_csv')}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => handleExportAudit('json')}
                    data-testid="audit-export-json"
                    className="cursor-pointer"
                  >
                    <FileJson size={16} className="mr-2" />
                    {t('audit.export_json')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            {!auditEvents ? (
              <Card>
                <CardContent className="py-8">
                  <Skeleton className="h-48 w-full" />
                </CardContent>
              </Card>
            ) : auditEvents.length === 0 ? (
              <Card>
                <CardContent className="py-12 text-center">
                  <History size={28} className="mx-auto text-muted-foreground/50 mb-3" />
                  <p className="text-sm text-muted-foreground">{t('audit.empty')}</p>
                </CardContent>
              </Card>
            ) : (
              <AuditTimeline events={auditEvents} t={t} />
            )}
          </TabsContent>
        )}


      </Tabs>

      {/* Rename workspace dialog — leader+ only */}
      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))] max-w-md">
          <DialogHeader>
            <DialogTitle>{t('workspace.rename_title')}</DialogTitle>
            <DialogDescription>{t('workspace.rename_description')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="workspace-rename-input">{t('workspace.rename_label')}</Label>
            <Input
              id="workspace-rename-input"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              maxLength={80}
              placeholder={t('workspace.rename_placeholder')}
              data-testid="workspace-rename-input"
              onKeyDown={(e) => { if (e.key === 'Enter' && !renaming) handleRenameWorkspace(); }}
            />
            <p className="text-xs text-muted-foreground">
              {t('workspace.rename_hint')}
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setRenameDialogOpen(false)}
              disabled={renaming}
              data-testid="workspace-rename-cancel"
            >
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleRenameWorkspace}
              disabled={renaming || !(renameValue || '').trim()}
              data-testid="workspace-rename-save"
              className="gap-2"
            >
              {renaming && <Loader2 size={14} className="animate-spin" />}
              {t('workspace.rename_save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Invite create dialog */}
      <Dialog open={inviteDialogOpen} onOpenChange={setInviteDialogOpen}>
        <DialogContent className="bg-[hsl(var(--card))] border-[hsl(var(--border))] max-w-md">
          <DialogHeader>
            <DialogTitle>{t('members.invite_create_title')}</DialogTitle>
            <DialogDescription>{t('members.subtitle')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label>{t('members.invite_role_label')}</Label>
              <Select
                value={inviteForm.role}
                onValueChange={(v) => setInviteForm({ ...inviteForm, role: v })}
              >
                <SelectTrigger data-testid="invite-role-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ROLE_OPTIONS.filter((r) => r !== 'owner').map((r) => (
                    <SelectItem key={r} value={r} disabled={r === 'leader' && !isOwner}>
                      {t(`members.role_${r}`)} — <span className="text-muted-foreground">{t(`members.role_${r}_desc`)}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('members.invite_max_uses')}</Label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={inviteForm.max_uses}
                  onChange={(e) => setInviteForm({ ...inviteForm, max_uses: parseInt(e.target.value, 10) || 1 })}
                  data-testid="invite-max-uses"
                />
              </div>
              <div>
                <Label>{t('members.invite_expires')}</Label>
                <Input
                  type="number"
                  min={1}
                  max={90}
                  value={inviteForm.expires_in_days}
                  onChange={(e) => setInviteForm({ ...inviteForm, expires_in_days: parseInt(e.target.value, 10) || 7 })}
                  data-testid="invite-expires"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground">{t('members.invite_email_optional')}</Label>
                <Input
                  type="email"
                  placeholder="alice@empresa.com"
                  value={inviteForm.email}
                  onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                  data-testid="invite-email"
                />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">{t('members.invite_full_name_optional')}</Label>
                <Input
                  placeholder="Alice Silva"
                  value={inviteForm.full_name}
                  onChange={(e) => setInviteForm({ ...inviteForm, full_name: e.target.value })}
                  data-testid="invite-full-name"
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setInviteDialogOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleCreateInvite} disabled={creatingInvite} data-testid="invite-submit-btn">
              {creatingInvite ? (
                <><Loader2 size={14} className="animate-spin mr-1.5" />{t('members.generating')}</>
              ) : (
                t('members.generate_invite')
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirm remove member */}
      <AlertDialog open={!!pendingRemoval} onOpenChange={(open) => { if (!open) setPendingRemoval(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {pendingRemoval?.user_id === user?.user_id ? t('members.leave_workspace') : t('members.remove_member')}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {pendingRemoval?.user_id === user?.user_id ? t('members.leave_confirm') : t('members.remove_confirm')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleRemove} className="bg-[hsl(var(--destructive))]">
              {t('common.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm revoke invite */}
      <AlertDialog open={!!pendingRevoke} onOpenChange={(open) => { if (!open) setPendingRevoke(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('members.revoke')}</AlertDialogTitle>
            <AlertDialogDescription>{t('members.revoke_confirm')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleRevokeInvite} className="bg-[hsl(var(--destructive))]">
              {t('members.revoke')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm mark onboarding complete */}
      <AlertDialog open={!!pendingComplete} onOpenChange={(open) => { if (!open) setPendingComplete(null); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('onboarding.action_mark_complete')}</AlertDialogTitle>
            <AlertDialogDescription>{t('onboarding.mark_complete_confirm')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common.cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleMarkOnboardingComplete} data-testid="confirm-mark-complete-btn">
              {t('common.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// ── Helpers / sub-components ────────────────────────────────────────────

const STEP_ICONS = {
  invitation_sent: Mail,
  account_created: UserCheck,
  companies_assigned: Building2,
  role_configured: KeyRound,
  first_login: CheckCircle2,
};

const ONBOARDING_STATUS_BADGE = {
  pending: 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]',
  in_progress: 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]',
  completed: 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]',
  blocked: 'bg-[hsl(var(--destructive)/0.15)] text-[hsl(var(--destructive))]',
};

function formatStepDate(iso, lang) {
  if (!iso) return null;
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(lang === 'es' ? 'es-ES' : 'en-US', { day: '2-digit', month: 'short' });
  } catch {
    return null;
  }
}

function OnboardingCard({ card, isAdmin, t, onMarkComplete, onCopyInvite, onRevokeAccess }) {
  const { lang } = useLanguage();
  const pct = card.progress.total
    ? Math.round((card.progress.completed / card.progress.total) * 100)
    : 0;
  const statusKey = card.status || 'pending';
  return (
    <div
      data-testid={`onboarding-card-${card.user_id}`}
      className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--surface-1))] p-4 hover:border-[hsl(var(--primary)/0.3)] transition-colors"
    >
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-full bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))] flex items-center justify-center text-sm font-semibold shrink-0 overflow-hidden">
          {card.picture ? (
            <img src={card.picture} alt={card.name} className="w-full h-full object-cover" />
          ) : (
            (card.name || card.email || '?').slice(0, 1).toUpperCase()
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium truncate">{card.name || card.email}</p>
            {card.role === 'owner' && <Crown size={12} className="text-[hsl(var(--primary))]" />}
          </div>
          <p className="text-xs text-muted-foreground truncate">{card.email}</p>
        </div>
        <Badge className={`${ONBOARDING_STATUS_BADGE[statusKey]} shrink-0 text-[10px]`}>
          {t(`onboarding.status_${statusKey}`)}
        </Badge>
      </div>

      <div className="mt-3 mb-2">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground mb-1.5">
          <span>{t('onboarding.member_progress', { completed: card.progress.completed, total: card.progress.total })}</span>
          <span className="font-mono">{pct}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-[hsl(var(--surface-2))] overflow-hidden">
          <div
            className="h-full bg-[hsl(var(--primary))] transition-[width] duration-300"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <ul className="mt-3 space-y-1.5">
        {card.steps.map((step) => {
          const Icon = STEP_ICONS[step.step_key] || AlertCircle;
          const done = step.status === 'completed';
          const blocked = step.status === 'blocked';
          const stepDate = formatStepDate(step.completed_at, lang);
          const microcopy = done
            ? t(`onboarding.step_${step.step_key}_done`)
            : t(`onboarding.step_${step.step_key}_pending`);
          return (
            <li
              key={step.step_key}
              data-testid={`onboarding-step-${card.user_id}-${step.step_key}`}
              className="flex items-start gap-2 text-xs"
            >
              <Icon
                size={14}
                className={`mt-0.5 shrink-0 ${
                  done ? 'text-[hsl(var(--success))]'
                    : blocked ? 'text-[hsl(var(--destructive))]'
                    : 'text-muted-foreground/60'
                }`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className={done ? 'text-foreground' : 'text-muted-foreground'}>
                    {t(`onboarding.step_${step.step_key}`)}
                  </span>
                  {stepDate && <span className="text-[10px] font-mono text-muted-foreground">{stepDate}</span>}
                </div>
                <p className="text-[10px] text-muted-foreground/80 mt-0.5">{microcopy}</p>
              </div>
            </li>
          );
        })}
      </ul>

      {isAdmin && card.status !== 'completed' && (
        <div className="mt-3 pt-3 border-t border-[hsl(var(--border))] flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={onCopyInvite}
            data-testid={`onb-copy-invite-${card.user_id}`}
            className="text-xs h-7"
          >
            <Copy size={12} className="mr-1" />
            {t('onboarding.action_copy_invite')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={onMarkComplete}
            data-testid={`onb-mark-complete-${card.user_id}`}
            className="text-xs h-7"
          >
            <CheckCircle2 size={12} className="mr-1" />
            {t('onboarding.action_mark_complete')}
          </Button>
          {card.role !== 'owner' && (
            <Button
              size="sm"
              variant="outline"
              onClick={onRevokeAccess}
              data-testid={`onb-revoke-${card.user_id}`}
              className="text-xs h-7 text-[hsl(var(--destructive))] hover:bg-[hsl(var(--destructive)/0.1)]"
            >
              <Trash2 size={12} className="mr-1" />
              {t('onboarding.action_revoke_access')}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

const AUDIT_ICON_MAP = {
  'invites.created': Mail,
  'invites.accepted': UserCheck,
  'invites.revoked': Trash2,
  'members.role_changed': KeyRound,
  'members.removed': Trash2,
  'workspace.claimed': Crown,
  'workspace.created': Building2,
  'workspace.switched': Building2,
  'onboarding.completed': CheckCircle2,
  'onboarding.step_updated': ClipboardList,
  'policy.created': Shield,
  'policy.deleted': Shield,
};

const AUDIT_LABEL_MAP = {
  'invites.created': 'audit.action_invitation_created',
  'invites.accepted': 'audit.action_invitation_accepted',
  'invites.revoked': 'audit.action_access_revoked',
  'members.role_changed': 'audit.action_role_changed',
  'members.removed': 'audit.action_user_deleted',
  'onboarding.completed': 'audit.action_onboarding_completed',
};

function relativeTime(iso, t) {
  if (!iso) return '';
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return t('audit.time_just_now');
  if (minutes < 60) return t('audit.time_minutes_ago', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('audit.time_hours_ago', { count: hours });
  const days = Math.floor(hours / 24);
  if (days < 30) return t('audit.time_days_ago', { count: days });
  return d.toLocaleDateString();
}

function AuditTimeline({ events, t }) {
  return (
    <Card>
      <CardContent className="py-4">
        <ul className="relative pl-6 space-y-4 before:content-[''] before:absolute before:left-3 before:top-2 before:bottom-2 before:w-px before:bg-[hsl(var(--border))]">
          {events.map((ev) => {
            const Icon = AUDIT_ICON_MAP[ev.action] || AlertCircle;
            const labelKey = AUDIT_LABEL_MAP[ev.action];
            const label = labelKey ? t(labelKey) : (ev.description || t('audit.action_unknown'));
            const actorName = ev.actor?.name || ev.actor?.email || '—';
            const targetName = ev.target?.name || ev.target?.email;
            return (
              <li
                key={ev.event_id}
                data-testid={`audit-event-${ev.event_id}`}
                className="relative"
              >
                <span className="absolute -left-[18px] top-0 w-6 h-6 rounded-full bg-[hsl(var(--surface-2))] border border-[hsl(var(--border))] flex items-center justify-center">
                  <Icon size={11} className="text-[hsl(var(--primary))]" />
                </span>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium">{label}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      <span className="font-medium text-foreground/90">{actorName}</span>
                      {targetName && (
                        <>
                          {' → '}
                          <span className="font-medium text-foreground/90">{targetName}</span>
                        </>
                      )}
                      {ev.metadata?.new_role && (
                        <>
                          {' · '}
                          <span className="capitalize">{ev.metadata.new_role}</span>
                        </>
                      )}
                    </p>
                    {ev.description && (
                      <p className="text-[10px] text-muted-foreground/70 mt-0.5 truncate">{ev.description}</p>
                    )}
                  </div>
                  <span className="text-[10px] font-mono text-muted-foreground shrink-0 mt-0.5">
                    {relativeTime(ev.timestamp, t)}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
