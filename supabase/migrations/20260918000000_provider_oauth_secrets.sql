-- =====================================================================
-- Phase 2: Provider OAuth secrets (Google + Microsoft) → Supabase
-- =====================================================================
-- Service-role-only secret tables. Ciphertext (Fernet) only — never
-- plaintext tokens. RLS enabled with NO policies for anon/authenticated
-- (Konta vault posture). App deletes oauth_states on consume; expires_at
-- supports TTL cleanup jobs.
-- Idempotent: safe to re-run.
-- =====================================================================

set search_path = public;

-- ── 1) provider_connections ──────────────────────────────────────────
create table if not exists public.provider_connections (
    id                        uuid primary key default gen_random_uuid(),
    org_id                    uuid null,
    workspace_id              text not null,
    provider                  text not null,
    account_email             text null,
    account_name              text null,
    provider_user_id          text null,   -- google_user_id / ms_user_id
    user_id                   text null,   -- Quantro user who connected
    scopes                    jsonb not null default '[]'::jsonb,
    access_token_enc          text null,   -- Fernet ciphertext
    refresh_token_enc         text null,   -- Fernet ciphertext
    expires_at                timestamptz null,
    connected                 boolean not null default false,
    status                    text null,
    reauthorization_required  boolean not null default false,
    missing_scopes            jsonb not null default '[]'::jsonb,
    connected_at              timestamptz null,
    last_sync_at              timestamptz null,
    last_sync_attempt_at      timestamptz null,
    auto_sync_paused          boolean not null default false,
    last_sync_error           text null,
    created_at                timestamptz not null default now(),
    updated_at                timestamptz not null default now(),
    constraint provider_connections_provider_chk check (
        provider in ('google', 'microsoft')
    ),
    constraint provider_connections_workspace_provider_uq
        unique (workspace_id, provider)
);

create index if not exists ix_provider_connections_workspace
    on public.provider_connections (workspace_id);
create index if not exists ix_provider_connections_provider
    on public.provider_connections (provider);
create index if not exists ix_provider_connections_autosync
    on public.provider_connections (provider)
    where auto_sync_paused is not true;

-- Reuse Phase 7c updated_at trigger if present; else create a local one.
create or replace function public.tg_set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists trg_provider_connections_updated_at
    on public.provider_connections;
create trigger trg_provider_connections_updated_at
before update on public.provider_connections
for each row execute function public.tg_set_updated_at();

alter table public.provider_connections enable row level security;
-- Intentionally NO policies for anon / authenticated.
revoke all on table public.provider_connections from anon, authenticated;
grant all on table public.provider_connections to service_role;

-- ── 2) oauth_states (short-lived CSRF) ───────────────────────────────
create table if not exists public.oauth_states (
    state         text primary key,
    provider      text not null,
    user_id       text null,
    workspace_id  text null,
    return_to     text null,
    redirect_uri  text null,
    created_at    timestamptz not null default now(),
    expires_at    timestamptz not null,
    constraint oauth_states_provider_chk check (
        provider in ('google', 'microsoft')
    )
);

create index if not exists ix_oauth_states_expires
    on public.oauth_states (expires_at);

alter table public.oauth_states enable row level security;
revoke all on table public.oauth_states from anon, authenticated;
grant all on table public.oauth_states to service_role;

comment on table public.provider_connections is
    'Phase 2: encrypted Google/Microsoft OAuth tokens. service_role only. Ciphertext via GOOGLE_TOKENS_ENCRYPTION_KEY (Fernet).';
comment on table public.oauth_states is
    'Phase 2: short-lived OAuth CSRF state (~10m). App deletes on consume; expires_at for TTL cleanup.';
comment on column public.provider_connections.access_token_enc is
    'Fernet ciphertext — never plaintext.';
comment on column public.provider_connections.refresh_token_enc is
    'Fernet ciphertext — never plaintext.';
