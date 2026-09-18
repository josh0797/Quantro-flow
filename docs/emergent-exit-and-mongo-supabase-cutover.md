# Audit: emergentintegrations + Mongo → Supabase cutover

_Date: 2026-09-17 · Repo: josh0797/Quantro-flow · Branch context: feat/quantro-connect-actions_

## Part A — `emergentintegrations` audit

### Where it appears

| Location | What | Runtime impact |
|----------|------|----------------|
| `backend/requirements.txt` | `emergentintegrations==0.1.0` | **Blocks clean `pip install -r requirements.txt`** (package not on public PyPI) |
| `tests/test_core_ai.py` | `from emergentintegrations.llm.chat import LlmChat, UserMessage` + `EMERGENT_LLM_KEY` | Standalone POC script only; **not** used by pytest suite under `backend/tests/` |
| `backend/server.py` ~L50 | Comment: `EMERGENT_LLM_KEY` intentionally **not** loaded | Production path already avoided Emergent LLM |
| `backend/ai_billing.py` | Documents that callers must use OpenAI via this module, not `EMERGENT_LLM_KEY` | Live AI = **OpenAI** (`AsyncOpenAI`) |
| `frontend/package.json` | `@emergentbase/visual-edits` from `assets.emergent.sh` | Dev-time visual editing helper |
| `frontend/craco.config.js` | Optional `withVisualEdits`; soft-fails if package missing | Build continues without it |

### What it is *not* used for (anymore)

- Auth → Supabase JWT (`get_current_user`, JWKS / JWT secret)
- LLM in app → `ai_billing.run_ai_request` + OpenAI SDK
- Connect/Actions → local `actions/` + `integrations/` modules

### Recommended Emergent exit (small PR, do first)

1. **Backend**
   - Remove `emergentintegrations==0.1.0` from `requirements.txt`.
   - Move or rewrite `tests/test_core_ai.py` to call `ai_billing` / OpenAI (or delete if obsolete POC).
   - Grep CI/docs for `EMERGENT_LLM_KEY` and retire env var.
2. **Frontend**
   - Remove `@emergentbase/visual-edits` dependency and the `craco` visual-edits branch (or keep behind an optional local-only path not in `package.json`).
3. **Verify**
   - `pip install -r requirements.txt` succeeds on a clean venv.
   - `backend/tests` still 49+ green.
   - Frontend production build without Emergent CDN.

**Do not** combine this PR with Mongo→Postgres migration.

---

## Part B — Mongo collections inventory

Declared in `backend/server.py` (plus Connect/Actions):

### Identity & tenancy (already dual-writing toward Supabase)

| Collection | Role | Supabase analog (today / target) |
|------------|------|----------------------------------|
| `users` | App user profile mirrored from Supabase `sub` | `auth.users` + `profiles` |
| `user_sessions` | Legacy; Bearer-only now | Drop after confirm unused |
| `workspaces` | Tenant; may store `org_id` | `organizations` / orgs |
| `workspace_members` | Roles; **mirrored from** `org_members` (Phase 7c) | `org_members` (**SoT direction**) |
| `workspace_invites` | Invites | Supabase invitations API / table |
| `audit_log` | App audit; **shadow-write** to `org_audit_logs` | `org_audit_logs` |

### Governance / automation

| Collection | Role | Notes |
|------------|------|-------|
| `automation_policies` | Inbox + future Actions SoT (`scope: action`) | Migrate carefully; keep shape in `docs/actions-policy-migration.md` |
| `action_policies` | **Legacy** Action auto_approve overrides | Compat-read only → fold into `automation_policies` then drop |
| `escalation_rules` | Inbox escalation | After policies |
| `content_templates` | Templates | Medium priority |

### Product domain (Mongo-heavy today)

| Collection | Role | Coupling |
|------------|------|----------|
| `inbox_items` | Inbox + AI intent | High — policies, Actions shim |
| `activity_events` | Activity feed | Medium |
| `contacts` | CRM | High write volume |
| `calendar_events` | Internal calendar | Actions internal handlers |
| `agents` | People/agents | Onboarding Actions |
| `onboarding_tasks` | Agent checklist | Actions |
| `people_onboarding_steps` | People onboarding | Phase 7 |
| `content_items` | Content studio | Medium |
| `business_profile` | Workspace profile | Low volume |
| `integrations_config` | Generic integrations UI | Overlap with Connect |
| `system_health_events` | Health | Low |

### Connect / secrets (sensitive)

| Collection | Role | Cutover caution |
|------------|------|-----------------|
| `google_integrations` | Tokens/scopes | Encrypt at rest in Vault / `connector_secrets`-style table; never plaintext in logs |
| `google_oauth_state` | OAuth CSRF state | Short-lived; easy |
| `microsoft_integrations` | Tokens/scopes | Same as Google |
| `microsoft_oauth_state` | OAuth state | Short-lived |
| `facturapi_connections` | Encrypted API keys | Same secret pattern as konta |
| `facturapi_webhook_events` | Webhook inbox | Append-only |

### Actions runtime

| Collection | Role | Cutover caution |
|------------|------|-----------------|
| `action_executions` | Execution ledger + idempotency | Needs **partial unique** `(workspace_id, action_id, idempotency_key)`; just hardened |

`supabase_admin.DB_PRIMARY` already supports `"supabase"` vs Mongo-first modes for members/audit — reuse that pattern per domain.

---

## Part C — Cutover plan by collection (phased)

### Principles

- One domain per PR (or tight PR train). No Emergent + Postgres mega-PR.
- Prefer: **dual-write → backfill → read flip (`DB_PRIMARY`) → stop Mongo writes → drop**.
- Preserve: workspace isolation, Simulation (`is_simulation`), Action idempotency, RLS on Supabase.
- Secrets: service_role only; mirror konta vault patterns where possible.

### Phase 0 — Emergent exit (1–3 days)
As in Part A. Unblocks CI/dev installs.

### Phase 1 — Finish identity SoT on Supabase (1–2 weeks)
**Collections:** `workspace_members`, `workspace_invites`, `audit_log`, then `workspaces`/`users` as projections.

- Complete Phase 7c: Supabase `org_members` = SoT; Mongo mirror optional then removed.
- Flip `DB_PRIMARY=supabase` for members/invites/audit in staging → prod.
- Drop or freeze `user_sessions` if unused.

**Exit criteria:** login, switch workspace, invite, role change, audit trail work with Mongo members optionally empty.

### Phase 2 — Secrets & Connect (2–3 weeks)
**Collections:** `google_*`, `microsoft_*`, `facturapi_*`, then `integrations_config`.

- Tables: `provider_connections`, `oauth_states`, `webhook_events` (+ encrypted secret column or vault table).
- Migrate tokens with keyed encryption; rotate if plaintext ever existed.
- OAuth callbacks write Supabase first.

**Exit criteria:** Google/Microsoft reconnect + Facturapi Test send on Supabase-backed storage; Mongo integration cols read-only then dropped.

### Phase 3 — Actions + policies (2–3 weeks) — **after** Connect/Actions PR #1 is stable in prod
**Collections:** `action_executions`, `automation_policies`, `action_policies` (delete after merge), `escalation_rules`.

- Recreate partial unique idempotency index in Postgres (`UNIQUE NULLS NOT DISTINCT` or partial unique index).
- Port PolicyEngine reads to Postgres; keep API contracts.
- Backfill executions (or start fresh if retention allows — decide explicitly).

**Exit criteria:** concurrent idempotency + approve same-id tests against Postgres; Simulation tagging intact.

### Phase 4 — Inbox & activity (2–4 weeks)
**Collections:** `inbox_items`, `activity_events`, `content_templates`, `content_items`.

- Highest product risk; do after Actions path is solid.
- Batch AI analyze / approve flows regression suite.

### Phase 5 — CRM / calendar / people (2–4 weeks)
**Collections:** `contacts`, `calendar_events`, `agents`, `onboarding_tasks`, `people_onboarding_steps`, `business_profile`, `system_health_events`.

- Internal Actions handlers point at Supabase repos.
- Then remove Motor/Mongo client from `server.py`.

### Phase 6 — Decommission Mongo
- Remove `MONGO_URL`, Motor, seed/backfill helpers that only serve Mongo.
- Document backup retention of final dump.

---

## Suggested sequencing vs current work

```
[now] Stabilize PR #1 Connect/Actions on Mongo
   ↓
[next] Phase 0 Emergent exit (small)
   ↓
Phase 1 identity SoT
   ↓
Phase 2 Connect secrets
   ↓
Phase 3 Actions/policies → Postgres
   ↓
Phases 4–5 product data
   ↓
Phase 6 kill Mongo
```

## Risks

| Risk | Mitigation |
|------|------------|
| Duplicate `action_executions` keys block unique index | Inventory before flip; manual dedupe; never auto-delete |
| Token leakage during migration | Encrypt in transit to new table; scrub logs |
| Dual-write drift | Single writer module per domain; metrics on mismatch |
| RLS gaps | Copy konta patterns; deny-by-default per `org_id` |
| Long dual-run cost | Timebox each phase; delete Mongo writes aggressively after flip |

## Non-goals for the next 2 weeks

- Rewriting Actions architecture again
- New providers
- Big-bang Mongo dump → Supabase import of all collections
