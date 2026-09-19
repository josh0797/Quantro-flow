-- Microsoft incremental consent: persist the Graph scopes used for the
-- authorization request so the callback can pass the same list to
-- acquire_token_by_authorization_code (base-only exchange dropped action scopes).
alter table public.oauth_states
    add column if not exists requested_scopes text[] null;

comment on column public.oauth_states.requested_scopes is
    'Microsoft incremental consent scope list (base + action). Null for Google / initial connect. Deleted with the row on consume.';
