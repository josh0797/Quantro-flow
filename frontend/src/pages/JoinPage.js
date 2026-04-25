import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Skeleton } from '../components/ui/skeleton';
import { CheckCircle2, AlertTriangle, Loader2, Users, Clock } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { peekInvite, acceptInvite } from '../lib/api';
import { toast } from 'sonner';

export default function JoinPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { user, loading: authLoading, refresh } = useAuth();
  const { t } = useLanguage();

  const [invite, setInvite] = useState(null);
  const [loading, setLoading] = useState(true);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      // Send the user to /login but remember where to come back to.
      const redirect = encodeURIComponent(`/join/${token}`);
      navigate(`/login?next=${redirect}`, { replace: true });
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await peekInvite(token);
        if (!cancelled) setInvite(data);
      } catch (err) {
        const detail = err?.response?.data?.detail;
        const msg = typeof detail === 'string' ? detail : detail?.message || t('invite.error_invalid');
        if (!cancelled) setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [token, user, authLoading, navigate, t]);

  const handleAccept = async () => {
    setAccepting(true);
    try {
      const result = await acceptInvite(token);
      if (result?.already_member) {
        toast.info(t('invite.already_member'));
      } else {
        toast.success(t('invite.success_title'));
      }
      // Re-hydrate auth so the new workspace shows up in the sidebar.
      await refresh();
      // Hard nav to dashboard so all contexts re-fetch under the new workspace.
      window.location.href = '/dashboard';
    } catch (err) {
      const detail = err?.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Failed to accept invite';
      toast.error(msg);
    } finally {
      setAccepting(false);
    }
  };

  if (authLoading || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[hsl(var(--background))] p-6">
        <Card className="max-w-md w-full">
          <CardHeader><CardTitle>{t('invite.page_title')}</CardTitle></CardHeader>
          <CardContent><Skeleton className="h-32 w-full rounded-lg" /></CardContent>
        </Card>
      </div>
    );
  }

  if (error || !invite) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[hsl(var(--background))] p-6">
        <Card data-testid="join-invalid-card" className="max-w-md w-full">
          <CardHeader>
            <div className="flex items-center gap-2">
              <AlertTriangle size={20} className="text-[hsl(var(--destructive))]" />
              <CardTitle className="text-base">{t('invite.error_invalid')}</CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{error || t('invite.error_invalid')}</p>
            <Button className="mt-4" onClick={() => navigate('/dashboard')}>
              {t('common.back')}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[hsl(var(--background))] p-6">
      <Card data-testid="join-invite-card" className="max-w-md w-full">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Users size={18} className="text-[hsl(var(--primary))]" />
            <CardTitle className="text-base">{t('invite.page_title')}</CardTitle>
          </div>
          <p className="text-sm text-muted-foreground mt-1">{t('invite.page_subtitle')}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
              <span className="text-xs text-muted-foreground uppercase tracking-wide">{t('invite.workspace_label')}</span>
              <span className="text-sm font-medium" data-testid="invite-workspace-name">{invite.workspace_name}</span>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
              <span className="text-xs text-muted-foreground uppercase tracking-wide">{t('invite.role_label')}</span>
              <Badge className="capitalize" data-testid="invite-role-badge">
                {t(`members.role_${invite.role}`)}
              </Badge>
            </div>
            {invite.expires_at && (
              <div className="flex items-center justify-between p-3 rounded-lg bg-[hsl(var(--surface-1))] border border-[hsl(var(--border))]">
                <span className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  <Clock size={12} />
                  {t('invite.expires_label')}
                </span>
                <span className="text-xs font-mono">
                  {new Date(invite.expires_at).toLocaleDateString()}
                </span>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 pt-2">
            <Button
              variant="secondary"
              className="flex-1"
              onClick={() => navigate('/dashboard')}
              disabled={accepting}
              data-testid="invite-cancel-btn"
            >
              {t('invite.decline_cta')}
            </Button>
            <Button
              className="flex-1"
              onClick={handleAccept}
              disabled={accepting}
              data-testid="invite-accept-btn"
            >
              {accepting ? (
                <><Loader2 size={14} className="animate-spin mr-1.5" />{t('invite.accepting')}</>
              ) : (
                <><CheckCircle2 size={14} className="mr-1.5" />{t('invite.accept_cta')}</>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
