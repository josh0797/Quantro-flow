-- Phase 6.2–6.3: activity_events, content_*, contacts, calendar_events
-- Dual-write ready; primary flags default mongo in app code.

create table if not exists public.activity_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null,
  event_id text not null,
  event_type text null,
  title text null,
  description text null,
  related_id text null,
  related_type text null,
  timestamp timestamptz null,
  is_simulation boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, event_id)
);
create index if not exists activity_events_ws_ts_idx
  on public.activity_events (workspace_id, timestamp desc);

create table if not exists public.content_items (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null,
  content_id text not null,
  type text null,
  title text null,
  content jsonb null,
  status text null,
  created_by text null,
  is_simulation boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, content_id)
);
create index if not exists content_items_ws_created_idx
  on public.content_items (workspace_id, created_at desc);

create table if not exists public.content_templates (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null,
  template_id text not null,
  name text null,
  category text null,
  body jsonb null,
  channel text null,
  is_default boolean not null default false,
  is_simulation boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, template_id)
);
create index if not exists content_templates_ws_name_idx
  on public.content_templates (workspace_id, name);

create table if not exists public.contacts (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null,
  contact_id text not null,
  name text null,
  email text null,
  phone text null,
  type text null,
  lifecycle_stage text null,
  source text null,
  notes text null,
  tags jsonb null,
  ghl_sync_status text null,
  ghl_last_sync timestamptz null,
  ghl_id text null,
  is_simulation boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, contact_id)
);
create index if not exists contacts_ws_updated_idx
  on public.contacts (workspace_id, updated_at desc);
create index if not exists contacts_ws_email_idx
  on public.contacts (workspace_id, email);

create table if not exists public.calendar_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id text not null,
  event_id text not null,
  title text null,
  description text null,
  start_time timestamptz null,
  end_time timestamptz null,
  location text null,
  attendees jsonb null,
  status text null,
  source text null,
  contact_id text null,
  google_event_id text null,
  is_simulation boolean not null default false,
  hidden_by_real boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workspace_id, event_id)
);
create index if not exists calendar_events_ws_start_idx
  on public.calendar_events (workspace_id, start_time);

alter table public.activity_events enable row level security;
alter table public.content_items enable row level security;
alter table public.content_templates enable row level security;
alter table public.contacts enable row level security;
alter table public.calendar_events enable row level security;

-- service_role bypasses RLS; no anon/authenticated policies (backend SoT).
revoke all on public.activity_events from anon, authenticated;
revoke all on public.content_items from anon, authenticated;
revoke all on public.content_templates from anon, authenticated;
revoke all on public.contacts from anon, authenticated;
revoke all on public.calendar_events from anon, authenticated;
grant all on public.activity_events to service_role;
grant all on public.content_items to service_role;
grant all on public.content_templates to service_role;
grant all on public.contacts to service_role;
grant all on public.calendar_events to service_role;

comment on table public.activity_events is 'Phase 6.2 activity feed; dual-write from Quantro-flow';
comment on table public.content_items is 'Phase 6.2 content studio items';
comment on table public.content_templates is 'Phase 6.2 content templates';
comment on table public.contacts is 'Phase 6.3 CRM contacts';
comment on table public.calendar_events is 'Phase 6.3 internal calendar events';
