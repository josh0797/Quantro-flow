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
import { Users, UserPlus, Copy, Trash2, Shield, Crown, Loader2, Link2 } from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import {
  listMembers, updateMemberRole, removeMember,
  listInvites, createInvite, revokeInvite,
} from '../lib/api';

const ROLE_RANK = { agent: 1, operator: 2, manager: 3, admin: 4, owner: 5 };
const ROLE_OPTIONS = ['agent', 'operator', 'manager', 'admin', 'owner'];

function roleBadgeClass(role) {
  switch (role) {
    case 'owner':
      return 'bg-[hsl(var(--primary)/0.15)] text-[hsl(var(--primary))]';
    case 'admin':
      return 'bg-[hsl(var(--accent)/0.15)] text-[hsl(var(--accent))]';
    case 'manager':
      return 'bg-[hsl(var(--info)/0.15)] text-[hsl(var(--info))]';
    case 'operator':
      return 'bg-[hsl(var(--success)/0.15)] text-[hsl(var(--success))]';
    default:
      return 'bg-[hsl(var(--muted-foreground)/0.15)] text-[hsl(var(--muted-foreground))]';
  }
}

export default function Members() {
  const { t } = useLanguage();
  const { user, currentWorkspaceId } = useAuth();
  const [data, setData] = useState({ members: [], your_role: 'agent' });
  const [invites, setInvites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creatingInvite, setCreatingInvite] = useState(false);
  const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
  const [inviteForm, setInviteForm] = useState({ role: 'operator', max_uses: 1, expires_in_days: 7 });
  const [pendingRemoval, setPendingRemoval] = useState(null);
  const [pendingRevoke, setPendingRevoke] = useState(null);

  const myRoleRank = ROLE_RANK[data.your_role] || 0;
  const isAdmin = myRoleRank >= ROLE_RANK.admin;
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

  const handleRoleChange = async (member, newRole) => {
    if (newRole === member.role) return;
    if (['admin', 'owner'].includes(newRole) && !isOwner) {
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
        </div>
        <div className="flex items-center gap-3">
          <Badge className={`${roleBadgeClass(data.your_role)} capitalize`} data-testid="my-role-badge">
            {t('members.your_role')}: {t(`members.role_${data.your_role}`)}
          </Badge>
        </div>
      </div>

      <Tabs defaultValue="members">
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
                const canEdit = isAdmin && !(isMe && m.role === 'owner') && (memberRoleRank < ROLE_RANK.admin || isOwner);
                const canRemove = (isMe && m.role !== 'owner') || (isAdmin && memberRoleRank < ROLE_RANK.owner && (memberRoleRank < ROLE_RANK.admin || isOwner));

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
                              <SelectItem key={r} value={r} disabled={['admin', 'owner'].includes(r) && !isOwner}>
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
      </Tabs>

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
                    <SelectItem key={r} value={r} disabled={r === 'admin' && !isOwner}>
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
    </div>
  );
}
