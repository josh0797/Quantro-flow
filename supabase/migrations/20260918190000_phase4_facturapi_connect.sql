-- =====================================================================
-- Phase 4: Facturapi Connect + webhook inbox + integrations_config → Supabase
-- =====================================================================
-- Extends Phase 2 provider_connections vault for Facturapi (api_key_enc
-- etc.). Adds append-only webhook_events and non-secret integrations_config
-- UI catalog. Service-role only. Idempotent: safe to re-run.
-- =====================================================================

set search_path = public;

-- ── 1) Allow provider='facturapi' on provider_connections ─────────────
alter table public.provider_connections
    drop constraint if exists provider_connections_provider_chk;

alter table public.provider_connections
    add constraint provider_connections_provider_chk check (
        provider in ('google', 'microsoft', 'facturapi')
    );

-- ── 2) Facturapi / Connect columns (nullable; Google/MS ignore) ───────
alter table public.provider_connections
    add column if not exists api_key_enc text;

alter table public.provider_connections
    add column if not exists connection_id text;

alter table public.provider_connections
    add column if not exists environment text;

alter table public.provider_connections
    add column if not exists organization_id text;

alter table public.provider_connections
    add column if not exists legal_name text;

alter table public.provider_connections
    add column if not exists is_production_ready boolean;

alter table public.provider_connections
    add column if not exists timezone text;

alter table public.provider_connections
    add column if not exists webhook_id text;

alter table public.provider_connections
    add column if not exists webhook_token_enc text;

alter table public.provider_connections
    add column if not exists webhook_secret_enc text;

alter table public.provider_connections
    add column if not exists meta jsonb not null default '{}'::jsonb;

create index if not exists ix_provider_connections_connection_id
    on public.provider_connections (connection_id)
    where connection_id is not null;

comment on column public.provider_connections.api_key_enc is
    'Phase 4: Facturapi secret_key Fernet ciphertext. Google/MS keep access/refresh.';
comment on column public.provider_connections.webhook_token_enc is
    'Phase 4: Facturapi URL-path webhook_token ciphertext.';
comment on column public.provider_connections.webhook_secret_enc is
    'Phase 4: Facturapi-issued signing secret (wh_sec_...) ciphertext.';
comment on column public.provider_connections.meta is
    'Phase 4: non-secret extras (e.g. last_error) — never plaintext keys.';

-- ── 3) webhook_events (append-only inbox; service_role only) ──────────
create table if not exists public.webhook_events (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    text not null,
    provider        text not null,
    connection_id   text null,
    event_id        text null,
    event_type      text null,
    payload         jsonb not null default '{}'::jsonb,
    headers_meta    jsonb not null default '{}'::jsonb,
    received_at     timestamptz not null default now(),
    processed_at    timestamptz null,
    status          text null,
    error           text null,
    constraint webhook_events_provider_chk check (
        provider in ('facturapi')
    )
);

create index if not exists ix_webhook_events_workspace_provider
    on public.webhook_events (workspace_id, provider);

create index if not exists ix_webhook_events_received_at
    on public.webhook_events (received_at desc);

create unique index if not exists uq_webhook_events_provider_event_id
    on public.webhook_events (provider, event_id)
    where event_id is not null;

alter table public.webhook_events enable row level security;
revoke all on table public.webhook_events from anon, authenticated;
grant all on table public.webhook_events to service_role;

comment on table public.webhook_events is
    'Phase 4: append-only provider webhook receipts. service_role only. No plaintext secrets.';

-- ── 4) integrations_config (Connect UI catalog; NO secrets) ───────────
create table if not exists public.integrations_config (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    text not null,
    provider        text not null,
    category        text null,
    display_name    text null,
    status          text null,
    last_sync_at    timestamptz null,
    config          jsonb not null default '{}'::jsonb,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    constraint integrations_config_workspace_provider_uq
        unique (workspace_id, provider)
);

create index if not exists ix_integrations_config_workspace
    on public.integrations_config (workspace_id);

create or replace function public.tg_set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists trg_integrations_config_updated_at
    on public.integrations_config;
create trigger trg_integrations_config_updated_at
before update on public.integrations_config
for each row execute function public.tg_set_updated_at();

alter table public.integrations_config enable row level security;
revoke all on table public.integrations_config from anon, authenticated;
grant all on table public.integrations_config to service_role;

comment on table public.integrations_config is
    'Phase 4: Connect UI status/config mirror. Non-secret only. service_role only for now.';
comment on column public.integrations_config.config is
    'UI config without secret fields (api_key/secret_key/…). Secrets stay in provider_connections / Mongo.';
