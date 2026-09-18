# Phase 7c — Migration to Supabase (apply manually)

## Status
- **Superseded for identity SoT by Phase 1** — see `docs/phase1-identity-sot.md`.
- Backend code is **dual-write ready** (Phase 7c) and **Supabase-primary by default** (Phase 1).
- Default mode: `QUANTRO_DB_PRIMARY=supabase` (rollback: `mongo`) — Mongo remains the read source, Supabase is shadow-written best-effort.
- After applying the SQL migration below, flip `QUANTRO_DB_PRIMARY=supabase` to make Supabase the read source. Mongo keeps receiving writes for backward compatibility.

## What's in the migration

Only ONE new table + view, additive on the existing schema:

- `public.people_onboarding_steps` — per-member onboarding checklist (5 canonical steps).
- `public.v_member_onboarding_progress` — rollup view for dashboards.

Re-uses **everything else** that already exists in the project:
- `organizations` / `org_members` / `invitations` / `org_audit_logs`
- `get_my_org_ids()` / `get_my_org_role(org_id)` helpers

## How to apply

1. Open Supabase Studio → SQL Editor.
2. Paste the contents of `20260426_people_onboarding_audit.sql`.
3. Run.
4. Verify with:
   ```sql
   select count(*) from public.people_onboarding_steps;        -- 0
   select * from public.v_member_onboarding_progress limit 1;  -- empty OK
   ```
5. (Optional) Add `SUPABASE_SERVICE_ROLE_KEY` to `/app/backend/.env` if you want backend-side `org_audit_logs` inserts to bypass RLS. Not strictly required — without it, audit shadow-writes try the user JWT first.
6. Once verified, set `QUANTRO_DB_PRIMARY=supabase` in `/app/backend/.env` and restart the backend:
   ```bash
   supervisorctl restart backend
   ```

## What changes after the flip

| Endpoint                                   | Before (`mongo`)            | After (`supabase`)              |
|--------------------------------------------|-----------------------------|---------------------------------|
| `GET /api/workspaces/{id}/members`         | reads MongoDB               | reads `org_members`             |
| `GET /api/workspaces/{id}/invites`         | reads MongoDB               | reads `invitations`             |
| `GET /api/workspaces/{id}/audit`           | reads MongoDB `audit_log`   | reads `org_audit_logs`          |
| `GET /api/workspaces/{id}/onboarding`      | derives from MongoDB        | merges `people_onboarding_steps`|

Writes (create_invite, role_change, member_remove, onboarding step upsert, audit log) **always** dual-write, regardless of mode, so flipping the read flag never loses data.

## Workspace ↔ Org mapping

The legacy single-tenant Mongo workspace `default_workspace` maps to `QUANTRO_DEFAULT_ORG_ID` (currently `1250ff9b-ac04-4370-8fd3-f846f34d1159`).

For new workspaces, store an explicit `org_id` field on the `workspaces` Mongo doc:
```js
db.workspaces.updateOne(
  { workspace_id: "ws_xxxx" },
  { $set: { org_id: "uuid-from-supabase" } }
)
```

If no mapping exists, the backend silently falls back to Mongo-only behavior for that workspace (no Supabase shadow-write).
