-- Reconcile people_onboarding_steps: live table exists without org_id
-- (has user_id instead). Additive + idempotent. Safe to re-run.

set search_path = public;

-- 1) Add org_id if missing
alter table public.people_onboarding_steps
  add column if not exists org_id uuid references public.organizations(id) on delete cascade;

-- 2) Backfill org_id from org_members using member_id (preferred) or user_id
update public.people_onboarding_steps pos
set org_id = om.org_id
from public.org_members om
where pos.org_id is null
  and om.user_id = coalesce(pos.member_id, pos.user_id);

-- If still null and only one org exists for that user, take it
update public.people_onboarding_steps pos
set org_id = sub.org_id
from (
  select user_id, min(org_id::text)::uuid as org_id
  from public.org_members
  group by user_id
  having count(distinct org_id) = 1
) sub
where pos.org_id is null
  and sub.user_id = coalesce(pos.member_id, pos.user_id);

-- 3) Ensure member_id populated from user_id when needed
update public.people_onboarding_steps
set member_id = user_id
where member_id is null and user_id is not null;

-- 4) Unique constraint on (org_id, member_id, step_key) when possible
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'people_onboarding_steps_unique'
  ) then
    -- Drop legacy unique on (user_id, ...) if any, then add canonical
    begin
      alter table public.people_onboarding_steps
        add constraint people_onboarding_steps_unique unique (org_id, member_id, step_key);
    exception when others then
      raise notice 'unique constraint deferred: %', sqlerrm;
    end;
  end if;
end $$;

-- 5) Indexes
create index if not exists ix_pos_org    on public.people_onboarding_steps(org_id);
create index if not exists ix_pos_member on public.people_onboarding_steps(member_id);
create index if not exists ix_pos_status on public.people_onboarding_steps(status);

-- 6) updated_at trigger helper
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

-- 7) RLS — org-scoped policies (drop/recreate)
alter table public.people_onboarding_steps enable row level security;

drop policy if exists pos_select on public.people_onboarding_steps;
create policy pos_select on public.people_onboarding_steps
for select using (
  org_id is not null and org_id = any (public.get_my_org_ids())
);

drop policy if exists pos_insert on public.people_onboarding_steps;
create policy pos_insert on public.people_onboarding_steps
for insert with check (
  org_id is not null
  and (
    public.get_my_org_role(org_id) in ('leader', 'owner')
    or member_id = auth.uid()
  )
);

drop policy if exists pos_update on public.people_onboarding_steps;
create policy pos_update on public.people_onboarding_steps
for update using (
  org_id is not null
  and (
    public.get_my_org_role(org_id) in ('leader', 'owner')
    or member_id = auth.uid()
  )
);

drop policy if exists pos_delete on public.people_onboarding_steps;
create policy pos_delete on public.people_onboarding_steps
for delete using (
  org_id is not null and public.get_my_org_role(org_id) = 'owner'
);

-- 8) Progress view
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
where org_id is not null
group by org_id, member_id;

grant select on public.v_member_onboarding_progress to authenticated;

-- Verify helpers (run separately if desired):
-- select column_name from information_schema.columns
--   where table_schema='public' and table_name='people_onboarding_steps' order by 1;
