-- =====================================================================
-- Phase 3: Actions runtime + policies → Supabase (Postgres)
-- =====================================================================
-- Tables:
--   action_executions   — ledger + atomic idempotency (service_role only)
--   automation_policies — SoT for inbox + scope=action (service_role only;
--                         org-scoped authenticated reads deferred — see
--                         docs/phase3-actions-postgres.md)
--   action_policies     — legacy auto_approve / daily_limit (compat-read;
--                         fold into automation_policies then drop)
--
-- escalation_rules: DEFERRED (inbox-coupled; remains Mongo this phase).
-- Idempotent: safe to re-run.
-- =====================================================================

set search_path = public;

-- Reuse / ensure updated_at trigger helper
create or replace function public.tg_set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

-- ── 1) action_executions ─────────────────────────────────────────────
create table if not exists public.action_executions (
    id                         uuid primary key default gen_random_uuid(),
    execution_id               text not null,
    workspace_id               text not null,
    action_id                  text not null,
    provider                   text null,
    requested_by               text null,
    actor_role                 text null,
    source                     text null,
    input                      jsonb not null default '{}'::jsonb,
    status                     text not null,
    risk_level                 text null,
    policy_decision            text null,
    confidence                 double precision null,
    idempotency_key            text null,
    started_at                 timestamptz null,
    completed_at               timestamptz null,
    provider_request_id        text null,
    result_metadata            jsonb not null default '{}'::jsonb,
    error_code                 text null,
    error_message_sanitized    text null,
    approved_by                text null,
    approved_at                timestamptz null,
    created_at                 timestamptz not null default now(),
    updated_at                 timestamptz not null default now(),
    constraint action_executions_execution_id_uq unique (execution_id)
);

create index if not exists ix_action_executions_workspace_started
    on public.action_executions (workspace_id, started_at desc);
create index if not exists ix_action_executions_workspace_status
    on public.action_executions (workspace_id, status);
create index if not exists ix_action_executions_workspace_action
    on public.action_executions (workspace_id, action_id);

-- Match backend/actions/indexes.py: unique (workspace_id, action_id,
-- idempotency_key) only when key is present (NOT NULL). Multiple NULLs OK.
-- Application layer still treats only _CLAIMED_STATUSES as "return existing".
create unique index if not exists uniq_workspace_action_idempotency_key
    on public.action_executions (workspace_id, action_id, idempotency_key)
    where idempotency_key is not null;

drop trigger if exists trg_action_executions_updated_at on public.action_executions;
create trigger trg_action_executions_updated_at
before update on public.action_executions
for each row execute function public.tg_set_updated_at();

alter table public.action_executions enable row level security;
revoke all on table public.action_executions from anon, authenticated;
grant all on table public.action_executions to service_role;

comment on table public.action_executions is
    'Phase 3: Action execution ledger. service_role only (may contain sensitive input). Partial unique idempotency when idempotency_key IS NOT NULL.';

-- ── 2) automation_policies ───────────────────────────────────────────
-- Flexible shape: inbox intent policies + scope=action rows.
create table if not exists public.automation_policies (
    id                              uuid primary key default gen_random_uuid(),
    policy_id                       text not null,
    workspace_id                    text not null,
    org_id                          uuid null,
    enabled                         boolean not null default true,
    -- Inbox fields
    intent                          text null,
    action                          text null,
    confidence_threshold_high       double precision null,
    confidence_threshold_medium     double precision null,
    high_action                     text null,
    medium_action                   text null,
    low_action                      text null,
    -- Actions scope fields (docs/actions-policy-migration.md)
    scope                           text null,          -- 'action' when Action SoT
    action_id                       text null,
    provider                        text null,
    mode                            text null,          -- auto_run | require_approval | block | simulate | escalate
    minimum_role                    text null,
    daily_limit                     integer null,
    -- Catch-all for forward-compat keys
    extra                           jsonb not null default '{}'::jsonb,
    created_at                      timestamptz not null default now(),
    updated_at                      timestamptz not null default now(),
    constraint automation_policies_policy_id_uq unique (policy_id)
);

create index if not exists ix_automation_policies_workspace
    on public.automation_policies (workspace_id);
create index if not exists ix_automation_policies_workspace_intent
    on public.automation_policies (workspace_id, intent)
    where intent is not null;
create index if not exists ix_automation_policies_scope_action
    on public.automation_policies (workspace_id, scope, action_id)
    where scope = 'action';

drop trigger if exists trg_automation_policies_updated_at on public.automation_policies;
create trigger trg_automation_policies_updated_at
before update on public.automation_policies
for each row execute function public.tg_set_updated_at();

alter table public.automation_policies enable row level security;
-- Deny-by-default for anon/authenticated this phase (service_role only).
-- Future: org-scoped SELECT for authenticated via org_id + JWT claims.
revoke all on table public.automation_policies from anon, authenticated;
grant all on table public.automation_policies to service_role;

comment on table public.automation_policies is
    'Phase 3: Automation / Action policies SoT. service_role only for now; org-scoped authenticated reads deferred.';

-- ── 3) action_policies (legacy compat) ───────────────────────────────
create table if not exists public.action_policies (
    id              uuid primary key default gen_random_uuid(),
    policy_id       text null,
    workspace_id    text not null,
    action_id       text not null,
    auto_approve    boolean not null default false,
    daily_limit     integer null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint action_policies_workspace_action_uq unique (workspace_id, action_id)
);

create index if not exists ix_action_policies_workspace
    on public.action_policies (workspace_id);

drop trigger if exists trg_action_policies_updated_at on public.action_policies;
create trigger trg_action_policies_updated_at
before update on public.action_policies
for each row execute function public.tg_set_updated_at();

alter table public.action_policies enable row level security;
revoke all on table public.action_policies from anon, authenticated;
grant all on table public.action_policies to service_role;

comment on table public.action_policies is
    'Phase 3 legacy: Action auto_approve overrides. Compat-read then fold into automation_policies (scope=action) and drop.';
