# Mongo inventory (remaining dependencies)

> **Superseded by the Mongo exit — see [mongo-exit-runbook.md](mongo-exit-runbook.md).**
> Since `feat/flow-off-mongo` every domain below has a Supabase home and an
> unset storage flag means Supabase / no mirror (`backend/storage_flags.py`).
> Mongo is only reachable through `backend/mongo_legacy.py` (lazy; never
> connects while every flag says Supabase). `GET /api/ready → checks.storage`
> shows the live routing.

| Area | Mongo collection(s) | Supabase home | Flag (domain) |
|------|---------------------|---------------|---------------|
| Identity / workspaces | `users`, `workspaces`, `workspace_members`, `workspace_invites`, `audit_log`, `people_onboarding_steps` | `flow_documents` (+ `org_members` / `invitations` / `org_audit_logs` / `people_onboarding_steps` for mapped orgs) | `QUANTRO_DOCS_PRIMARY` |
| Business profile / simulation | `business_profile` | `flow_documents` | docs |
| Agents / onboarding / escalation | `agents`, `onboarding_tasks`, `escalation_rules` | `flow_documents` | docs |
| System health | `system_health_events` | `flow_documents` | docs |
| Sync locks | `sync_locks` | `flow_sync_locks` | docs |
| Provider OAuth secrets | `google_integrations`, `microsoft_integrations` | `provider_connections` | `QUANTRO_SECRETS_PRIMARY` |
| OAuth CSRF state | `google_oauth_state`, `microsoft_oauth_state` | `oauth_states` | secrets |
| Facturapi Connect | `facturapi_connections`, `facturapi_webhook_events` | `provider_connections`, `webhook_events` | secrets |
| Integrations catalog | `integrations_config` | `integrations_config` (+ `secrets_enc` ciphertext) | `QUANTRO_INTEGRATIONS_CONFIG_PRIMARY` |
| Actions | `action_executions`, `automation_policies`, `action_policies` | same names | `QUANTRO_ACTIONS_PRIMARY` |
| Inbox | `inbox_items` | `inbox_items` | `QUANTRO_INBOX_PRIMARY` |
| Activity | `activity_events` | `activity_events` | `QUANTRO_ACTIVITY_PRIMARY` |
| Content | `content_items`, `content_templates` | same names | `QUANTRO_CONTENT_PRIMARY` |
| Contacts | `contacts` | `contacts` | `QUANTRO_CONTACTS_PRIMARY` |
| Calendar | `calendar_events` | `calendar_events` | `QUANTRO_CALENDAR_PRIMARY` |
| Unused | `user_sessions` | — (frozen since Phase 1) | — |
