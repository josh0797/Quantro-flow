-- =====================================================================
-- Phase 7b-ext: People Onboarding & Audit Trail
-- =====================================================================
-- Adds two operational tables that mirror what the Quantro Flow backend
-- already persists in MongoDB. Apply this migration when you're ready
-- to consolidate the audit + onboarding state in Supabase as the system
-- of record. The backend is forward-compatible with both layouts.
--
-- Idempotency: every CREATE/POLICY uses IF NOT EXISTS / DROP-IF-EXISTS
-- so re-running this file is safe.
-- =====================================================================

set search_path = public;

-- ── 1) people_onboarding_steps ───────────────────────────────────────
create table if not exists public.people_onboarding_steps (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    member_id    uuid not null,
    step_key     text not null,
    status       text not null default 'pending',
    completed_at timestamptz null,
    metadata     jsonb default '{}'::jsonb,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now(),
    constraint people_onboarding_steps_unique unique (member_id, step_key),
    constraint people_onboarding_steps_step_key_chk check (
        step_key in (
            'invitation_sent',
            'account_created',
            'companies_assigned',
            'role_configured',
            'first_login'
        )
    ),
    constraint people_onboarding_steps_status_chk check (
        status in ('pending', 'completed', 'blocked')
    )
);

create index if not exists ix_onb_member       on public.people_onboarding_steps(member_id);
create index if not exists ix_onb_workspace    on public.people_onboarding_steps(workspace_id);
create index if not exists ix_onb_status       on public.people_onboarding_steps(status);

-- Auto-bump updated_at on every UPDATE.
create or replace function public.tg_set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists trg_onb_set_updated_at on public.people_onboarding_steps;
create trigger trg_onb_set_updated_at
before update on public.people_onboarding_steps
for each row execute function public.tg_set_updated_at();

-- ── 2) people_audit_logs ─────────────────────────────────────────────
create table if not exists public.people_audit_logs (
    id                uuid primary key default gen_random_uuid(),
    workspace_id      uuid null,
    actor_user_id     uuid null,
    target_member_id  uuid null,
    company_id        uuid null,
    action            text not null,
    description       text null,
    metadata          jsonb default '{}'::jsonb,
    created_at        timestamptz default now(),
    constraint people_audit_logs_action_chk check (
        action in (
            'invitation_created',
            'invitation_accepted',
            'access_revoked',
            'user_deleted',
            'role_changed',
            'companies_assigned',
            'companies_removed',
            'permissions_modified',
            'onboarding_completed'
        )
    )
);

create index if not exists ix_audit_member      on public.people_audit_logs(target_member_id);
create index if not exists ix_audit_actor       on public.people_audit_logs(actor_user_id);
create index if not exists ix_audit_company     on public.people_audit_logs(company_id);
create index if not exists ix_audit_workspace   on public.people_audit_logs(workspace_id);
create index if not exists ix_audit_action      on public.people_audit_logs(action);
create index if not exists ix_audit_created_at  on public.people_audit_logs(created_at desc);

-- ── 3) RLS — only members of the same workspace can read; only
--      leader/owner can mutate; audit rows are append-only from the
--      UI (no DELETE policy) ─────────────────────────────────────────
alter table public.people_onboarding_steps enable row level security;
alter table public.people_audit_logs       enable row level security;

-- Helper: is the caller a member of the given workspace?
create or replace function public.is_workspace_member(p_workspace uuid)
returns boolean language sql stable as $$
    select exists (
        select 1
        from public.org_members
        where org_id = p_workspace
          and user_id = auth.uid()
    );
$$;

-- Helper: does the caller have at least the given role in the given
-- workspace? Roles are ranked owner > leader > accountant > member > viewer.
create or replace function public.has_role_at_least(p_workspace uuid, p_min_role text)
returns boolean language sql stable as $$
    with my_role as (
        select role from public.org_members
        where org_id = p_workspace and user_id = auth.uid()
        limit 1
    ),
    rank_map as (
        select 'viewer' as role, 1 as rank union all
        select 'member',     2 union all
        select 'accountant', 3 union all
        select 'leader',     4 union all
        select 'owner',      5
    )
    select coalesce(
        (select rm.rank from rank_map rm join my_role m on m.role = rm.role) >=
        (select rm.rank from rank_map rm where rm.role = p_min_role),
        false
    );
$$;

-- ─── people_onboarding_steps policies ───────────────────────────────
drop policy if exists onb_select on public.people_onboarding_steps;
create policy onb_select on public.people_onboarding_steps
for select using (public.is_workspace_member(workspace_id));

drop policy if exists onb_insert on public.people_onboarding_steps;
create policy onb_insert on public.people_onboarding_steps
for insert with check (public.has_role_at_least(workspace_id, 'leader'));

drop policy if exists onb_update on public.people_onboarding_steps;
create policy onb_update on public.people_onboarding_steps
for update using (
    public.has_role_at_least(workspace_id, 'leader')
    or member_id = auth.uid()  -- members can self-update their own steps
);

drop policy if exists onb_delete on public.people_onboarding_steps;
create policy onb_delete on public.people_onboarding_steps
for delete using (public.has_role_at_least(workspace_id, 'owner'));

-- ─── people_audit_logs policies (append-only from clients) ──────────
drop policy if exists audit_select on public.people_audit_logs;
create policy audit_select on public.people_audit_logs
for select using (
    workspace_id is null  -- system-level events, gated app-side
    or public.has_role_at_least(workspace_id, 'leader')
);

drop policy if exists audit_insert on public.people_audit_logs;
create policy audit_insert on public.people_audit_logs
for insert with check (public.has_role_at_least(workspace_id, 'leader'));

-- INTENTIONALLY: no UPDATE / no DELETE policy → audit rows are
-- immutable from the UI. Only the service-role key (or a future db
-- admin migration) can modify them.

-- ── 4) Backfill helper view (optional) ───────────────────────────────
-- Surfaces a count of pending steps per member so dashboards can light
-- up "people pending onboarding" without recomputing on the fly.
create or replace view public.v_member_onboarding_progress as
select
    workspace_id,
    member_id,
    sum(case when status = 'completed' then 1 else 0 end) as completed,
    count(*)                                              as total,
    case
        when sum(case when status = 'completed' then 1 else 0 end) = count(*) then 'completed'
        when sum(case when status = 'blocked'   then 1 else 0 end) > 0       then 'blocked'
        when sum(case when status = 'completed' then 1 else 0 end) > 0       then 'in_progress'
        else 'pending'
    end as overall_status
from public.people_onboarding_steps
group by workspace_id, member_id;

-- =====================================================================
-- End of migration
-- =====================================================================
