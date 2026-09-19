-- Additive: iCal UID + external_updated_at for Outlook/Google calendar sync compare.
-- Keeps existing external_provider / external_event_id uniqueness.

alter table public.calendar_events
  add column if not exists ical_uid text null,
  add column if not exists external_updated_at timestamptz null;

comment on column public.calendar_events.ical_uid is
  'RFC5545 UID (iCalUId from Graph / iCalUID from Google) for strong cross-provider identity when present';
comment on column public.calendar_events.external_updated_at is
  'Provider lastModifiedDateTime / updated — used to skip unchanged sync rows';

create index if not exists calendar_events_ws_ical_uid_idx
  on public.calendar_events (workspace_id, ical_uid)
  where ical_uid is not null;
