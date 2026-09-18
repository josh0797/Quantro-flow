-- Google OAuth PKCE: persist short-lived code_verifier with CSRF state.
-- google-auth-oauthlib generates the verifier on authorization_url; the
-- callback creates a new Flow and must restore the same verifier before
-- fetch_token, or Google returns (invalid_grant) Missing code verifier.
-- Row (and verifier) are deleted on consume_oauth_state.
alter table public.oauth_states
    add column if not exists code_verifier text null;

comment on column public.oauth_states.code_verifier is
    'Short-lived Google PKCE code_verifier; deleted with the row on consume. Null for Microsoft / legacy.';
