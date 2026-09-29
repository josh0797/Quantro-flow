# Mongo exit runbook (Quantro Flow → Supabase only)

Goal: nothing in Flow reads or writes MongoDB in production, nothing is lost,
Mongo's own data is left untouched, `MONGO_URL` stays configured until the
owner removes it.

Pieces:

| Piece | Where |
|---|---|
| Schema: new tables, missing columns | konta `supabase/migrations/20261026090500_flow_off_mongo.sql` (branch `feat/flow-supabase-tables`) |
| Schema: full unique indexes for the sync upserts (42P10 fix) | konta `supabase/migrations/20261026090600_flow_sync_unique_indexes.sql` (branch `feat/flow-sync-unique-indexes`, stacked on the one above; **apply only after step 2**) |
| Code (Supabase-only request paths, fail-safe defaults) | this repo, branch `feat/flow-off-mongo` |
| Backfill (runs on the Fly machine) | `backend/scripts/mongo_to_supabase.py` → `/app/scripts/mongo_to_supabase.py` in the image |
| Activity-leak repair (runs on the Fly machine) | `backend/scripts/fix_activity_workspace.py` (branch `fix/activity-workspace-leak`, merged after `feat/flow-off-mongo`) — see [Activity workspace repair](#activity-workspace-repair) |
| Effective routing, live | `GET /api/ready` → `checks.storage` |

## What changes

* **Defaults.** An unset `QUANTRO_<DOMAIN>_PRIMARY` now means `supabase`, an
  unset `*_MONGO_MIRROR` means "no mirror" (`backend/storage_flags.py`). The
  flags remain as the escape hatch.
* **New domain `docs`** (`QUANTRO_DOCS_PRIMARY` / `QUANTRO_DOCS_MONGO_MIRROR`):
  users, workspaces, workspace_members, workspace_invites, audit_log,
  people_onboarding_steps, business_profile, agents, onboarding_tasks,
  escalation_rules, system_health_events → `public.flow_documents`
  (`backend/doc_store.py`); autosync leases → `public.flow_sync_locks`.
* **Mongo is lazy** (`backend/mongo_legacy.py`): no connection unless a flag
  routes a domain to Mongo. Any Mongo call from a domain whose flags say
  Supabase-only logs `mongo access while disabled` (and is counted in
  `/api/ready`).
* **No silent fallback.** With Supabase primary and the mirror off, a
  Supabase failure raises (HTTP 503 `storage_unavailable`) instead of reading
  Mongo or dropping the write.
* **Two greppable WARNING tags** (Flow configures no logging, so only
  WARNING and above reach `fly logs`):
  * `MONGO_ONLY` — Mongo holds, or just received, data Supabase lacks: a
    Supabase write degraded to Mongo, a shadow copy failed, or a read was
    answered from Mongo (the line carries the row's id, never its content).
    The backfill (`--apply`) repairs these.
  * `STORE_DRIFT` — the stores disagree in a way the backfill does **not**
    repair: a Mongo mirror write/delete failed while Supabase is primary (Mongo
    is now stale), or a shadow delete failed while Mongo is primary (Supabase
    kept a row). Review each by hand.
* `fly.toml` `[env]` pins today's routing (`QUANTRO_DOCS_PRIMARY=mongo`,
  `QUANTRO_CALENDAR_PRIMARY=mongo`, `QUANTRO_INTEGRATIONS_CONFIG_PRIMARY=mongo`,
  `QUANTRO_MONGO_MIRROR=1`) so deploying the code changes nothing. The cutover
  overrides them with `fly secrets set`. **Fly: secrets take precedence over
  `[env]` variables with the same name.**

Live bugs this also fixes (all were silent in production):

1. Synced Gmail/Outlook messages and calendar events never reached Supabase:
   their upserts targeted PARTIAL unique indexes → `42P10`. Migration
   `20261026090600` makes them full indexes (NULLs stay distinct).
2. Live-mode contacts/activity/content/template lists were served from Mongo:
   the `hidden_by_real` filter had no column → PostgREST 400 → Mongo fallback.
3. `PUT /api/policies/{id}` answered 500 under Supabase primary
   (`matched_count` on an `httpx.Response`).
4. `/api/templates/{id}/generate` needed `body_template`, which only Mongo had.
5. Microsoft incremental consent lost `requested_scopes` when the OAuth state
   was read from Supabase.
6. Disconnect deleted synced calendar rows by `is_real`, which Supabase lacked.
7. Calendar sync upserts sent `external_provider` in both `$set` and
   `$setOnInsert` (inferred `internal` on the partial doc) — Mongo rejects that
   update; partial `$set` patches also rewrote `external_provider` to
   `internal`.
8. Inbox re-sync upserts would have reset `inbox_id`/`status` once 1. was fixed
   (`$setOnInsert` values were merged into every upsert). **This is why the
   index migration must wait for the Flow deploy (step 2b).**
9. `patch_connection` could create token-less `provider_connections` rows that
   later read as "not connected" (the backfill repairs any it finds).
10. Items generated from a template had no `workspace_id` → never written to
    Supabase.
11. (`fix/activity-workspace-leak`) Cross-tenant leak: `log_activity` defaulted
    `workspace_id` to `"default"` and 30 call sites did not pass one, so other
    tenants' inbox senders/subjects/AI summaries, profile changes and
    simulation runs were shown in the `"default"` workspace's activity feed.
    Fixed in code (the event is dropped with an `ACTIVITY_NO_WORKSPACE`
    WARNING if a workspace is ever missing); existing rows are repaired by
    `scripts/fix_activity_workspace.py` (step 4b).
12. (`fix/activity-workspace-leak`) Accepting a Supabase invitation of an org
    that has no Flow workspace (e.g. a Quantro OS invitation) made the
    account a member of the `"default"` workspace. Such tokens now 404.

---

## Runbook (ordered)

`APP=quantro-flow-api`. Every command below is read-only unless marked **WRITE**.
Never print secret values: the commands below only show flag names/values and
counts. The backfill prints counts and ids, never document bodies or tokens.

### 0. Record the current state (read-only)

```bash
fly secrets list -a $APP                     # names + digests only, never values
fly ssh console -a $APP -C "sh -c \"env | grep -E '^QUANTRO_[A-Z_]*_(PRIMARY|MIRROR)=' | sort\""   # storage flags only
curl -s https://<flow-api-host>/api/ready | jq .checks.storage
```

The `grep` pattern matches only the `*_PRIMARY` / `*_MIRROR` storage flags;
do **not** widen it to `^QUANTRO_` — that also prints secrets such as
`QUANTRO_OS_SERVICE_TOKEN`. `checks.storage` shows the same routing without
reading env at all.

Keep the output: it is the rollback reference. Expected today: DB, SECRETS,
ACTIONS, ACTIVITY, CONTACTS, CONTENT, INBOX primaries = `supabase`; CALENDAR =
`mongo`; INTEGRATIONS_CONFIG unset; every `*_MONGO_MIRROR` = `1`.

### 1. Apply konta migration 20261026090500 (**WRITE**, schema only, additive)

Merge konta `feat/flow-supabase-tables` and push migrations the usual way
(`supabase db push` from konta). Do **not** include
`20261026090600_flow_sync_unique_indexes.sql` yet (it lives on
`feat/flow-sync-unique-indexes`). If a union push directory picks it up by
mistake it refuses with `deploy Quantro Flow (feat/flow-off-mongo) before this
migration` and changes nothing — remove it from that push and continue.

Check (versions alone are not proof — another branch once had a migration with
the same version; the name is):

```bash
supabase migration list --linked | grep -E '20261026090500'
```
```sql
select version, name from supabase_migrations.schema_migrations
 where version in ('20261026090500', '20261026090600');
-- expect exactly: 20261026090500 | flow_off_mongo   (no 090600 row yet)
select to_regclass('public.flow_documents'), to_regclass('public.flow_sync_locks');
```

This migration does not touch the sync unique indexes, so the Flow build that is
live right now keeps behaving exactly as today.

### 2. Deploy the Flow code with the flags unchanged (**WRITE**, code)

Merge `feat/flow-off-mongo`, `fly deploy -a $APP`. Nothing is re-routed (fly.toml
pins). New behaviour right away: the `docs` collections are shadow-written to
`flow_documents` (so the backfill → flip window loses nothing).

Verify:

```bash
curl -s https://<flow-api-host>/api/ready | jq .checks.storage
#   docs/calendar/integrations: primary "mongo"; the rest "supabase"; mongo_required: true
fly logs -a $APP | grep -E "\[startup\]|MONGO_ONLY|STORE_DRIFT|mongo access while disabled|storage_unavailable"
```
```sql
select count(*) from flow_documents;   -- must be > 0 before step 2b (sign in once if it is 0)
```

Until step 2b, `MONGO_ONLY … SB update degraded` lines from inbox autosync are
expected: synced mail still lands in Mongo only, exactly as before (42P10).
`[startup] … repair skipped` lines must not appear.

### 2b. Apply konta migration 20261026090600 (**WRITE**, index swap)

Only after step 2 is live and `flow_documents` has rows. Merge konta
`feat/flow-sync-unique-indexes`, `supabase db push`.

```sql
select version, name from supabase_migrations.schema_migrations where version = '20261026090600';
-- expect: 20261026090600 | flow_sync_unique_indexes
select indexname from pg_indexes
 where indexname in ('uq_inbox_items_workspace_gmail', 'uq_inbox_items_workspace_ms',
                     'uq_calendar_events_ws_provider_ext');                -- 3 rows
```

It builds three unique indexes without `CONCURRENTLY` (each locks writes on its
table for seconds at Flow's sizes) and fails loudly, changing nothing, if a
table already holds duplicate provider ids — then stop and dedupe first. After
the next autosync tick (≤ 15 min) the `SB update degraded` lines stop and
`select count(*) from inbox_items where gmail_id is not null or ms_id is not null`
grows.

### 3. Backfill — dry run on the machine (read-only)

```bash
fly ssh console -a $APP -C "sh -c 'cd /app && python -m scripts.mongo_to_supabase'"
```

`MONGO_URL` and the service-role key are read from the machine's environment;
nothing leaves it. If the console session does not see the app's secrets the
script exits 2 with `missing env` and reads/writes nothing. Check, before going
on:

* `Schema preflight FAILED` is absent (else step 1 is not applied — stop);
* the `WARNING: Mongo is no longer mirrored` line is absent (else the mirrors
  are already off — stop, see step 4);
* `UNKNOWN Mongo collections` is absent (or each one has been reviewed);
* `error` = 0; read every `notes:` / `skipped:` / `insert:` line (ids only);
* `sb_only` / `REVIEW:` lines — see step 5.

Policies it uses: `mongo_wins` for docs, calendar_events and
integrations_config (still Mongo-primary), `fill` for everything already
Supabase-primary (Supabase values are kept; only missing rows / NULL values /
columns the migration added that still hold their default are filled).

Memory: the script streams — a Mongo cursor in batches of 500 documents and,
on the Supabase side, only the key columns of each table plus the full rows of
the current batch. It shares the 512 MB VM with the API, so it never holds a
whole collection or table.

### 4. Backfill — apply (**WRITE**, Supabase only; never deletes)

```bash
fly ssh console -a $APP -C "sh -c 'cd /app && python -m scripts.mongo_to_supabase --apply'"
```

Exit code must be 0. Re-runnable **only while every Mongo mirror is on**
(steps 3–6a). Once a domain stops mirroring (6b) its Mongo copy is stale:
copying it again would re-insert rows users deleted since (removed members,
disconnected mailboxes with their tokens, deleted contacts) and fill values
they changed. The script therefore refuses `--apply` with exit 2 for any
dataset of such a domain. Never pass `--allow-stale-mongo` during the cutover.

Before applying, compare the `insert:` ids of `google_integrations`,
`microsoft_integrations`, `facturapi_connections`, `workspace_members` and
`workspace_invites` with any `STORE_DRIFT` lines in `fly logs`: an insert that
matches a failed mirror delete is a row a user removed — do not let it back
(delete it again right after the apply, or narrow the run with `--only`).

### 4b. Repair leaked activity rows (**WRITE**, never deletes)

Requires `fix/activity-workspace-leak` deployed (a normal `fly deploy`, no
flag changes — it can go out with step 2 or any time after it). Safe at any
point of the cutover: before or after the backfill, during the 6a soak and
after 6b. The recommended slot is right here, between the backfill's
`--apply` and its `--verify`:

```bash
fly ssh console -a $APP -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace'"            # dry run
fly ssh console -a $APP -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace --apply'"    # exit 0
fly ssh console -a $APP -C "sh -c 'cd /app && python -m scripts.fix_activity_workspace --verify'"   # exit 0
```

Read the dry run first: `workspace 'default' members: N` (count only),
`decisions: keep= reattribute= quarantine=`, `re-attributed to:` (workspace
ids) and up to 20 event ids per bucket. Rows it cannot attribute go to the
workspace `__unattributed__`, which nobody can be a member of; a later run
re-resolves them. Then step 5 (`--verify` of the backfill) must still exit 0
— the remediation moves the Mongo mirror copy with each Supabase row, and the
backfill matches activity rows by `event_id` too, so it never re-inserts a
repaired row under `"default"` (details in
[Activity workspace repair](#activity-workspace-repair)).

### 5. Verify (read-only)

```bash
fly ssh console -a $APP -C "sh -c 'cd /app && python -m scripts.mongo_to_supabase --verify'"
```

Exit 0 means every dataset shows `insert=0 update=0 error=0` **and** there is no
`REVIEW:` line. A `REVIEW:` line means an access-granting row (workspace member
or invite) exists only in Supabase while Mongo is still its source of truth —
a shadow delete that failed. The backfill never deletes; after confirming the
member/invite is really gone in the app, remove it by hand (**WRITE**):

```sql
select doc_id, workspace_id, doc->>'user_id' as user_id, doc->>'role' as role
  from flow_documents where collection = 'workspace_members' and doc_id in ('<ids from the report>');
delete from flow_documents where collection = 'workspace_members' and doc_id in ('<ids>');
```

Then `--verify` again. Cross-check counts in the Supabase SQL editor against the
`mongo` column of the dry run:

```sql
select collection, count(*) from flow_documents group by 1 order by 1;
select count(*) from calendar_events;  select count(*) from integrations_config;
select count(*) from inbox_items where gmail_id is not null or ms_id is not null;
```

If users were active in between and `--verify` shows a few updates, run
`--apply` once more, then `--verify`. (Rows whose only difference was the
trigger-managed `updated_at` are not reported — that column is never compared.)

### 6. Flip the flags (**WRITE**, restarts the machines)

6a — primaries to Supabase, Mongo still mirrored (recommended soak, e.g. 24 h):

```bash
fly secrets set -a $APP \
  QUANTRO_DOCS_PRIMARY=supabase \
  QUANTRO_CALENDAR_PRIMARY=supabase \
  QUANTRO_INTEGRATIONS_CONFIG_PRIMARY=supabase
```

Smoke test (step 7). During the soak:

```bash
fly logs -a $APP | grep -E "MONGO_ONLY|STORE_DRIFT"
```

Each `MONGO_ONLY` line is a row Supabase did not have, a Supabase write that
degraded to Mongo, or a read answered from Mongo; it is repaired by the gate
below. Each `STORE_DRIFT` line names a row to review by hand.

**Gate before 6b (mandatory, mirrors still on):** immediately before 6b, run
step 4 (`--apply`; it now uses `fill` for every domain), step 4b
(`fix_activity_workspace --apply`, then `--verify`, both exit 0 — it catches
any leaked row the apply just copied from Mongo) and step 5 (`--verify`,
exit 0). Then check that no new `MONGO_ONLY` line appeared since the verify
started (`fly logs -a $APP --no-tail | grep MONGO_ONLY`); if one did, repeat the
gate. Anything written only to Mongo after this point would be lost at 6b.

6b — Mongo out of the request path:

```bash
fly secrets set -a $APP \
  QUANTRO_MONGO_MIRROR=0 QUANTRO_DOCS_MONGO_MIRROR=0 QUANTRO_CALENDAR_MONGO_MIRROR=0 \
  QUANTRO_ACTIONS_MONGO_MIRROR=0 QUANTRO_INBOX_MONGO_MIRROR=0 QUANTRO_ACTIVITY_MONGO_MIRROR=0 \
  QUANTRO_CONTACTS_MONGO_MIRROR=0 QUANTRO_CONTENT_MONGO_MIRROR=0
```

From here on, do **not** run step 4 again (the script refuses anyway).

### 7. Smoke test (after 6a and again after 6b)

```bash
curl -s https://<flow-api-host>/api/ready | jq .checks.storage
#   after 6b: mongo_required false, mongo_client_created false, mongo_disallowed_access_count 0
fly logs -a $APP | grep -E "mongo access while disabled|storage_unavailable|MONGO_ONLY|STORE_DRIFT|ACTIVITY_NO_WORKSPACE|\[startup\]"
```

`ACTIVITY_NO_WORKSPACE` must never appear (an activity event reached
`log_activity` without a workspace and was dropped — a code bug; the line
carries only the event type).

In the app (as a real user): log in → workspace switcher and members list;
Inbox (list, open, analyze, approve, decline); Calendar (list, create, delete);
Contacts; Agents / onboarding tasks; Content + template generate; Automation
policies (create, **edit**, delete) and escalation rules; Settings → business
profile, Integrations (update an API-key provider), Members / invites / audit
export; Connect → Google & Microsoft status, **Sync** (new mail/events appear
once), disconnect/reconnect on a test workspace; System health card.

### 8. Rollback

* Before 2b: revert the Flow deploy if needed; migration 20261026090500 is
  additive and can stay.
* During 6a: `fly secrets set` the three primaries back to `mongo` (or
  `fly secrets unset` them to fall back to the fly.toml pins). Mongo was
  mirrored, nothing is lost.
* After 6b: set the mirrors back to `1` first. Writes made while the mirror
  was off exist only in Supabase; rolling a primary back to Mongo after that
  needs a reverse copy — prefer fixing forward (Supabase is complete). Do not
  use the backfill for that: it copies Mongo → Supabase and would undo those
  writes.

### 9. Later (separate PRs, owner's call)

1. Remove the pins from `fly.toml` (the defaults are the end state) and
   `fly secrets unset` the flags that only restate defaults.
2. Remove `motor` and `pymongo` from `backend/requirements.txt`; delete the
   client in `mongo_legacy.py`, the Mongo branches of the stores,
   `sync_lock.acquire_sync_lock_lease`, and the startup repairs that only
   run on Mongo (`_legacy_repair_targets`).
3. `fly secrets unset MONGO_URL` and decide what to do with the Atlas cluster
   (this runbook never modifies Mongo data).

## Backfill reference

`python -m scripts.mongo_to_supabase [--apply | --verify] [--only a,b] [--json] [--allow-stale-mongo]`

| Mongo collection | Supabase target | key | policy |
|---|---|---|---|
| users, workspaces, workspace_members, workspace_invites, audit_log, people_onboarding_steps, business_profile, agents, onboarding_tasks, escalation_rules, system_health_events | `flow_documents` | (collection, Mongo `_id`) | docs domain |
| calendar_events | `calendar_events` | (ws, provider, external id) or (ws, event_id) | calendar |
| integrations_config | `integrations_config` | (ws, provider); newest duplicate wins | integrations |
| inbox_items | `inbox_items` | (ws, inbox_id), else (ws, gmail_id)/(ws, ms_id) | inbox |
| contacts, content_items, content_templates | same names | (ws, app id) | contacts/content |
| activity_events | same name | (ws, event_id), else event_id alone (a row `fix_activity_workspace` moved to another workspace is never inserted again under the Mongo copy's workspace) | activity |
| action_executions / automation_policies / action_policies | same names | execution_id / policy_id / (ws, action_id) | actions |
| google_integrations, microsoft_integrations, facturapi_connections | `provider_connections` | (ws, provider) | secrets (token-less rows repaired) |
| facturapi_webhook_events | `webhook_events` | (provider, event_id) | insert only |
| google/microsoft_oauth_state, sync_locks, user_sessions | — | not copied (short-lived / unused) | — |

Report columns: `mongo insert update same skip error sb_only`; per-dataset
lines list up to 20 ids for `insert:`, `skipped:`, `errors:` and
`supabase_only:` (rows only Supabase has; reported for workspace members /
invites and provider connections). Exit codes: 0 ok · 1 errors, pending
writes under `--verify`, or a `REVIEW:` row · 2 schema preflight failed,
stale Mongo refused, or missing env.

Legacy defaults applied while copying (the startup repairs used to apply
them in Mongo): missing `workspace_id` → `default`; missing `is_simulation`
→ `true` on the operational collections. Legacy plaintext secrets in
`integrations_config.config` are encrypted with the machine's key (or skipped
and counted if no key is configured). The trigger-managed `updated_at` column
is never compared or patched.

## Activity workspace repair

`python -m scripts.fix_activity_workspace [--apply | --verify] [--json]`
(branch `fix/activity-workspace-leak`; runbook step 4b and the gate before 6b).

Until that branch, `log_activity` stored events without an explicit workspace
under `"default"`. The script looks at every `activity_events` row under
`"default"` (and under the quarantine workspace `__unattributed__`) and
resolves its real workspace from `related_type` / `related_id`, reading the
entity through the app's own store facades — so it is found wherever it lives
at that moment of the cutover:

| related_type (who logs it) | entity looked up | where it lives |
|---|---|---|
| `inbox` (analyze / approve / decline / details / batch / overrides) | inbox item by `inbox_id` (Mongo-only synced docs: `id`) | `inbox_items` (Supabase-primary) |
| `calendar` (meeting scheduled) | calendar event by `event_id` | `calendar_events` (Mongo-primary until 6a) |
| `contact` (contact created) | contact by `contact_id` | `contacts` (Supabase-primary) |
| `agent` (onboarding started, new agent, onboarding task) | agent by `agent_id` | `flow_documents` / `agents` (docs: Mongo-primary until 6a) |
| `policy` (policy updated) | automation policy by `policy_id` | `automation_policies` (Supabase-primary) |
| `content`, `template`, `escalation` (already workspace-scoped call sites) | by `content_id` / `template_id` / `rule_id` | `content_items`, `content_templates`, `flow_documents` / `escalation_rules` |
| `profile` (business profile updated) | `related_id` **is** the workspace id | `flow_documents` / `workspaces` |

Decision per event (counts and ids are printed, never titles/descriptions):

* **keep** — the entity belongs to `"default"`, or the row has no entity and
  no leaking call site could have written it (seed "System initialized",
  the simulation generator, integration updates);
* **reattribute** — the entity belongs to another workspace: `workspace_id`
  and `is_simulation` are taken from the entity (or that workspace's current
  Simulation Mode when the entity has no flag, e.g. policies, profiles);
* **quarantine** → `__unattributed__` — the entity no longer exists, or the
  row comes from a leaking call site that logged no entity ("Batch triage
  complete", "Batch approval complete", "Content generated", "Simulation data
  generated / auto-generated / cleared"). Nobody can be a member of that
  workspace, so nobody sees these rows; they are never deleted;
* **restore** / reattribute from quarantine — a later run re-resolves
  quarantined rows (e.g. the entity was copied by the backfill since).

Cutover safety (why `--apply` then `--verify` of the backfill still exits 0):

1. The script writes through the same dual-write facade as the app
   (`product_domain_store.wrap_activity_col`). While the activity mirror is on,
   the Mongo copy moves with the Supabase row, and Mongo copies still under
   `"default"` (including rows only Mongo has, `MONGO_ONLY`) are found and
   moved too — the backfill, keyed on `(workspace_id, event_id)`, then sees the
   same row on both sides. After 6b Mongo is not touched.
2. If a mirror write fails anyway (`STORE_DRIFT`), the Mongo copy stays under
   `"default"`. Supabase's only unique key is `(workspace_id, event_id)`
   (konta `20260918210000`), so the backfill would insert it again there.
   It therefore also matches activity rows by `event_id` alone (a uuid) and
   never patches `workspace_id`: the stale copy is reported as `same` (note
   `matched_by_alt_key`). The remediation's `--apply` exits 1 in that case
   (`remaining moves after apply` > 0: the Mongo copies); re-run it once Mongo
   is reachable.
3. A Supabase duplicate (the same event already under its real workspace) is
   moved to the quarantine workspace instead of hitting the unique key.

Exit codes: 0 ok · 1 errors, anything left to move after `--apply` or under
`--verify` · 2 `missing env` (`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`,
and `MONGO_URL` while a flag still routes one of its collections to Mongo).

Check in the Supabase SQL editor (read-only):

```sql
select workspace_id, count(*) from activity_events
 where workspace_id in ('default', '__unattributed__') group by 1;
select event_id from activity_events group by 1 having count(*) > 1;   -- expect no rows
```

Reverting a quarantine by hand is never needed for correctness (a re-run
re-resolves it). If the owner wants specific quarantined rows back in
`"default"` anyway, do it after 6b (before that, the script is the only writer
that also moves the Mongo copy):

```sql
update activity_events set workspace_id = 'default'
 where workspace_id = '__unattributed__' and event_id in ('<ids from the report>');
```
