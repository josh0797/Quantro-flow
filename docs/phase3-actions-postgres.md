# Phase 3 — Actions runtime + policies (Supabase / Postgres)

Migrates **Action executions** and **policies** toward Supabase as source of
truth, without breaking deploys that have not applied the migration or
backfill. Connect adapters are untouched.

| Concern | Mongo (default read) | Supabase |
|---------|----------------------|----------|
| Execution ledger + idempotency | `action_executions` | `action_executions` |
| Automation / Action SoT | `automation_policies` | `automation_policies` |
| Legacy Action overrides | `action_policies` | `action_policies` (compat) |
| Escalation (inbox) | `escalation_rules` | **Deferred** — stays Mongo |

## Design

Pattern: **dual-write → backfill → flip read → stop Mongo write**.

Persistence for PolicyEngine + ActionExecutor goes through
`backend/actions/store.py` (Motor-like facades). Action API contracts and
Connect adapters are unchanged. Unit tests may still inject
`FakeAsyncCollection` directly (no live Mongo / Supabase required).

### Idempotency (Postgres)

Partial unique index (matches `backend/actions/indexes.py`):

```sql
UNIQUE (workspace_id, action_id, idempotency_key)
WHERE idempotency_key IS NOT NULL
```

Multiple NULL keys remain allowed. Application layer still only *returns*
an existing row when `status` is in the claimed set (`running`,
`pending_approval`, `approved`, `succeeded`, `simulated`, `failed`,
`suggested`).

### RLS

| Table | Posture |
|-------|---------|
| `action_executions` | **service_role only** (inputs may be secrets-like) |
| `automation_policies` | **service_role only** this phase; org-scoped `authenticated` reads deferred |
| `action_policies` | **service_role only** (legacy; fold then drop) |

Backend uses `SUPABASE_SERVICE_ROLE_KEY` via the store. Missing tables /
transport errors → warning log + Mongo (graceful degrade).

### escalation_rules — deferred

Inbox evaluation (`evaluate_policy_for_item`, seed defaults) still reads
Mongo `escalation_rules`. Not tightly required for ActionExecutor /
PolicyEngine Action path. Migrate with inbox (Phase 4) or a follow-up.

## Migration

Apply:

```text
supabase/migrations/20260918120000_actions_postgres.sql
```

## Env flags

```bash
# Default for this Phase 3 PR — safe without backfill
QUANTRO_ACTIONS_PRIMARY=mongo

# Dual-write to Supabase whenever URL + service role are set (automatic)
# SUPABASE_URL=...
# SUPABASE_SERVICE_ROLE_KEY=...

# After migration + backfill, flip reads to Supabase (Mongo fallback)
QUANTRO_ACTIONS_PRIMARY=supabase

# Mongo writes when primary=supabase (prefer dedicated flag; else shared)
QUANTRO_ACTIONS_MONGO_MIRROR=1
# or QUANTRO_MONGO_MIRROR=1

# Later: freeze Mongo action/policy writes
QUANTRO_ACTIONS_MONGO_MIRROR=0
```

`QUANTRO_ACTIONS_PRIMARY` is **independent** of Phase 1
`QUANTRO_DB_PRIMARY` and Phase 2 `QUANTRO_SECRETS_PRIMARY`.

### Behaviour matrix

| `QUANTRO_ACTIONS_PRIMARY` | Reads | Mongo writes | Supabase writes |
|---------------------------|-------|--------------|-----------------|
| `mongo` (default) | Mongo | always | when SB configured (dual-write) |
| `supabase` | Supabase → Mongo fallback | if mirror on | when SB configured |

## Backfill

```bash
# Dry-run (default)
python scripts/backfill_mongo_to_supabase.py --table action_executions
python scripts/backfill_mongo_to_supabase.py --table automation_policies
python scripts/backfill_mongo_to_supabase.py --table action_policies

# Execute
python scripts/backfill_mongo_to_supabase.py --table action_executions --execute --yes
python scripts/backfill_mongo_to_supabase.py --table automation_policies --execute --yes
python scripts/backfill_mongo_to_supabase.py --table action_policies --execute --yes
```

Idempotent upserts: executions on `execution_id`; automation policies on
`policy_id`; legacy action_policies on `(workspace_id, action_id)`.

**Dedupe before flip:** if historical duplicate idempotency keys exist in
Mongo, resolve manually (keep earliest) before relying on the Postgres
unique index — never auto-delete.

## Rollout

1. Apply SQL migration in Supabase.
2. Deploy backend with defaults (`QUANTRO_ACTIONS_PRIMARY=mongo`) → dual-write.
3. Backfill dry-run, then `--execute`.
4. Spot-check row counts vs Mongo.
5. Set `QUANTRO_ACTIONS_PRIMARY=supabase`, restart, exercise execute /
   approve / list executions + policy evaluation.
6. Optionally `QUANTRO_ACTIONS_MONGO_MIRROR=0` after soak.

## Rollback

```bash
QUANTRO_ACTIONS_PRIMARY=mongo
QUANTRO_ACTIONS_MONGO_MIRROR=1
```

Restart backend. Reads return to Mongo; Supabase dual-write continues when
configured.

## Residual Mongo reads (known)

Even with `QUANTRO_ACTIONS_PRIMARY=supabase`:

- Fallback when Supabase miss / error / missing table
- **`escalation_rules`** — Mongo only (deferred)
- Product domain still Mongo: inbox items, contacts, calendar, agents, …
- Connect secrets use Phase 2 flags (`QUANTRO_SECRETS_PRIMARY`), not this flag
- Identity uses Phase 1 (`QUANTRO_DB_PRIMARY`)

## Tests

```bash
cd backend && PYTHONPATH=. pytest tests/test_actions_hardening.py tests/test_executor.py tests/test_policy_gate.py -q
PYTHONPATH=backend pytest test_phase3_actions_postgres.py -q
```

## Code map

- Store: `backend/actions/store.py`
- Wiring: `backend/server.py` (`wrap_*_col`)
- Executor / PolicyEngine: unchanged contracts; receive wrapped cols
- SQL: `supabase/migrations/20260918120000_actions_postgres.sql`
- Backfill: `scripts/backfill_mongo_to_supabase.py`
