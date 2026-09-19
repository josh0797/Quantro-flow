# Mongo inventory (remaining dependencies)

Classification of Mongo / Motor usage after the Supabase dual-write migration.
**Do not delete Mongo** while any production path still uses Motor.

| Area | Collection(s) / path | Class | Notes |
|------|----------------------|-------|-------|
| Identity / workspaces | `users`, `workspaces`, `workspace_members` | DUAL_WRITE / transitional | Phase 1 SoT moves to Supabase org_*; Mongo still used for membership APIs |
| Provider OAuth secrets | `google_integrations`, `microsoft_integrations` | MIGRATED_PRIMARY_SUPABASE | `QUANTRO_SECRETS_PRIMARY=supabase`, mirror ON |
| OAuth CSRF state | `google_oauth_state`, `microsoft_oauth_state` | MIGRATED_PRIMARY_SUPABASE | via `provider_secrets_store` |
| Facturapi Connect | `facturapi_connections`, webhook events | MIGRATED_PRIMARY_SUPABASE | Phase 4 connect_store |
| Actions | actions / executions / policies | DUAL_WRITE | `QUANTRO_ACTIONS_PRIMARY` (verify Fly) |
| Inbox | `inbox_items` | MIGRATED_PRIMARY_SUPABASE | Phase 6.1 |
| Activity | `activity_events` | MIGRATED_PRIMARY_SUPABASE | Phase 6.2 |
| Content | `content_items`, `content_templates` | MIGRATED_PRIMARY_SUPABASE | Phase 6.2 |
| Contacts | `contacts` | MIGRATED_PRIMARY_SUPABASE | Phase 6.3 |
| Calendar | `calendar_events` | MONGO_PRIMARY | **Must stay mongo** until canonical external_* tests green (`QUANTRO_CALENDAR_PRIMARY=mongo`) |
| Business profile / simulation | `business_profile` | MONGO_PRIMARY | Not yet migrated |
| Integrations catalog | `integrations_config` | DUAL_WRITE | Phase 4 |
| System health / audit | `system_health`, audit logs | MONGO_PRIMARY | Operational |
| Sync locks | `sync_locks` | MONGO_PRIMARY | Multi-instance autosync idempotency |
| Agents / other product | `agents`, misc | MONGO_PRIMARY / LEGACY_UNUSED | Inventory per feature before flip |

Legend:
- **MIGRATED_PRIMARY_SUPABASE** — reads prefer Supabase; Mongo mirror optional
- **DUAL_WRITE** — writing both; primary flag may still be mongo or supabase
- **MONGO_PRIMARY** — production primary is still Mongo
- **LEGACY_UNUSED** — code paths unused in prod; keep until confirmed dead
