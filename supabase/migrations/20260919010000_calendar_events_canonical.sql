-- Additive calendar_events canonical model (Google/MS field mismatch fix).
-- Does NOT rewrite the Phase 6.3 create table; only ALTER + indexes.
-- Canonical fields: event_id, workspace_id, external_event_id,
-- external_provider (google|microsoft|internal), title, description,
-- start_time, end_time, location, attendees, status, source, contact_id,
-- external_url, is_simulation, hidden_by_real, created_at, updated_at, synced_at.
-- Legacy google_event_id / Mongo gcal_id|ms_id|start|end|html_link remain readable
-- via app-layer mapping until backfill completes.

alter table public.calendar_events
  add column if not exists external_event_id text null,
  add column if not exists external_provider text null,
  add column if not exists external_url text null,
  add column if not exists synced_at timestamptz null;

-- Backfill external_* from legacy google_event_id where present.
update public.calendar_events
set
  external_event_id = coalesce(external_event_id, google_event_id),
  external_provider = coalesce(external_provider, case when google_event_id is not null then 'google' else null end)
where google_event_id is not null
  and (external_event_id is null or external_provider is null);

-- Infer internal provider for rows that still lack one.
update public.calendar_events
set external_provider = coalesce(external_provider, 'internal')
where external_provider is null;

comment on column public.calendar_events.external_event_id is
  'Provider-native event id (Google/MS); null for internal-only events';
comment on column public.calendar_events.external_provider is
  'google | microsoft | internal';
comment on column public.calendar_events.external_url is
  'Provider deep link (htmlLink / webLink)';
comment on column public.calendar_events.synced_at is
  'Last successful provider sync timestamp';

-- Dedup key for synced events. Partial so internal rows without an
-- external id do not collide.
create unique index if not exists calendar_events_ws_provider_ext_uidx
  on public.calendar_events (workspace_id, external_provider, external_event_id)
  where external_event_id is not null;

create index if not exists calendar_events_ws_provider_idx
  on public.calendar_events (workspace_id, external_provider);

comment on table public.calendar_events is
  'Phase 6.3 calendar events — canonical external_* model (20260919)';
