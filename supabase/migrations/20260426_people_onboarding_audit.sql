-- =====================================================================
-- Phase 7c: People Onboarding (additive migration on existing schema)
-- =====================================================================
-- Quantro Flow uses Supabase as the system of record for organisation
-- membership. The schema already has:
--    organizations, org_members, invitations, org_audit_logs
--    helper functions: get_my_org_ids(), get_my_org_role(uuid)
--
-- This migration ADDS one new table + view to support the per-member
-- onboarding checklist surfaced in the Members → Onboarding tab.
-- It DOES NOT redefine audit logs (we reuse `org_audit_logs`) and it
-- DOES NOT touch the existing `invitations` table (we keep using it
-- as the single invite store).
--
-- Idempotent: every CREATE / DROP-IF-EXISTS pair makes re-runs safe.
-- =====================================================================

set search_path = public;

-- ── 1) people_onboarding_steps ───────────────────────────────────────
-- One row per (member, step). Tracks the 5 canonical onboarding steps
-- exposed in the UI:
--   invitation_sent · account_created · companies_assigned ·
--   role_configured · first_login
create table if not exists public.people_onboarding_steps (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null references public.organizations(id) on delete cascade,
    member_id    uuid not null,           -- corresponds to org_members.user_id (auth.uid())
    step_key     text not null,
    status       text not null default 'pending',
    completed_at timestamptz null,
    metadata     jsonb default '{}'::jsonb,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now(),
    constraint people_onboarding_steps_unique unique (org_id, member_id, step_key),
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

create index if not exists ix_pos_org      on public.people_onboarding_steps(org_id);
create index if not exists ix_pos_member   on public.people_onboarding_steps(member_id);
create index if not exists ix_pos_status   on public.people_onboarding_steps(status);

-- Auto-bump updated_at on UPDATE.
create or replace function public.tg_set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists trg_pos_set_updated_at on public.people_onboarding_steps;
create trigger trg_pos_set_updated_at
before update on public.people_onboarding_steps
for each row execute function public.tg_set_updated_at();

-- ── 2) RLS policies — reuse existing helpers ─────────────────────────
-- get_my_org_role(org_id) returns the caller's role in that org or null.
-- Quantro role hierarchy: viewer < member < accountant < leader < owner.
alter table public.people_onboarding_steps enable row level security;

drop policy if exists pos_select on public.people_onboarding_steps;
create policy pos_select on public.people_onboarding_steps
for select using (
    -- Any member of the same org can read the roster's onboarding state.
    org_id = any (public.get_my_org_ids())
);

drop policy if exists pos_insert on public.people_onboarding_steps;
create policy pos_insert on public.people_onboarding_steps
for insert with check (
    -- Leader / owner OR the member writing their own step.
    public.get_my_org_role(org_id) in ('leader', 'owner')
    or member_id = auth.uid()
);

drop policy if exists pos_update on public.people_onboarding_steps;
create policy pos_update on public.people_onboarding_steps
for update using (
    public.get_my_org_role(org_id) in ('leader', 'owner')
    or member_id = auth.uid()
);

drop policy if exists pos_delete on public.people_onboarding_steps;
create policy pos_delete on public.people_onboarding_steps
for delete using (
    public.get_my_org_role(org_id) = 'owner'
);

-- ── 3) Convenience view: rolled-up progress per member ───────────────
-- Lets the UI / dashboards render a quick "people pending onboarding"
-- count without recomputing on every query.
create or replace view public.v_member_onboarding_progress as
select
    org_id,
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
group by org_id, member_id;

grant select on public.v_member_onboarding_progress to authenticated;

-- =====================================================================
-- End of migration
--
-- After applying this in the Supabase UI, verify with:
--   select * from public.people_onboarding_steps limit 1;     -- empty OK
--   select * from public.v_member_onboarding_progress limit 1;
--
-- The backend will start writing rows here once QUANTRO_DB_PRIMARY=supabase.
-- =====================================================================
