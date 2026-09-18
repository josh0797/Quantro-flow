-- =====================================================================
-- Phase 6.1: inbox_items → Supabase (Postgres)
-- =====================================================================
-- Product domain cutover (cutover doc "Phase 4" → inbox_items).
-- Dual-write Mongo → this table; default read remains Mongo via
-- QUANTRO_INBOX_PRIMARY=mongo (see docs/phase6-inbox-items.md).
--
-- RLS: service_role only (same vault posture as Phase 2/3). Org-scoped
-- authenticated policies can come later.
--
-- Covers seed docs (from_email, inbox_id) + Google/Outlook sync
-- (from_address, gmail_id / ms_id, label_ids / categories, preview) + AI.
-- Idempotent: safe to re-run.
-- =====================================================================

set search_path = public;

create or replace function public.tg_set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

create table if not exists public.inbox_items (
    id                  uuid primary key default gen_random_uuid(),
    inbox_id            text not null,
    workspace_id        text not null,
    from_name           text null,
    from_email          text null,
    from_address        text null,
    subject             text null,
    body                text null,
    preview             text null,
    received_at         timestamptz null,
    read                boolean not null default false,
    status              text null,
    ai_intent           jsonb null,
    ai_suggested_action jsonb null,
    contact_id          text null,
    source              text null,
    gmail_id            text null,
    ms_id               text null,
    thread_id           text null,
    label_ids           jsonb null,
    categories          jsonb null,
    is_real             boolean null,
    is_simulation       boolean null,
    hidden_by_real      boolean null,
    priority            text null,
    synced_at           timestamptz null,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint inbox_items_workspace_inbox_uq unique (workspace_id, inbox_id)
);

-- Google sync upsert key
create unique index if not exists uniq_inbox_items_workspace_gmail
    on public.inbox_items (workspace_id, gmail_id)
    where gmail_id is not null;

-- Outlook sync upsert key
create unique index if not exists uniq_inbox_items_workspace_ms
    on public.inbox_items (workspace_id, ms_id)
    where ms_id is not null;

create index if not exists ix_inbox_items_workspace
    on public.inbox_items (workspace_id);

create index if not exists ix_inbox_items_received_at
    on public.inbox_items (received_at desc nulls last);

create index if not exists ix_inbox_items_workspace_status
    on public.inbox_items (workspace_id, status);

create index if not exists ix_inbox_items_workspace_hidden
    on public.inbox_items (workspace_id, hidden_by_real);

drop trigger if exists trg_inbox_items_updated_at on public.inbox_items;
create trigger trg_inbox_items_updated_at
before update on public.inbox_items
for each row execute function public.tg_set_updated_at();

alter table public.inbox_items enable row level security;

-- Deny-by-default for anon/authenticated this phase (service_role only).
-- Future: org-scoped SELECT for authenticated via workspace/org JWT claims.
revoke all on table public.inbox_items from anon, authenticated;
grant all on table public.inbox_items to service_role;

comment on table public.inbox_items is
    'Phase 6.1: Inbox product domain. service_role only for now; org-scoped authenticated deferred. Dual-write from Mongo; QUANTRO_INBOX_PRIMARY controls reads.';

comment on column public.inbox_items.inbox_id is
    'App-level id (Mongo inbox_id or sync $setOnInsert id). Unique with workspace_id.';

comment on column public.inbox_items.from_email is
    'Seed / demo path sender email.';

comment on column public.inbox_items.from_address is
    'Google/Outlook sync sender address.';
