# Backfill MongoDB → Supabase

Scripts para Phase 7c. **Uso bajo demanda únicamente** — no corren en boot ni en CI.

## `backfill_mongo_to_supabase.py`

Migración one-shot de los datos legacy de Mongo a las tablas reales de Supabase.

### Lee

| MongoDB collection      | → | Supabase table     |
|-------------------------|---|--------------------|
| `workspace_members`     | → | `org_members`      |
| `workspace_invites`     | → | `invitations`      |
| `audit_log`             | → | `org_audit_logs`   |
| `google_integrations` / `microsoft_integrations` | → | `provider_connections` (Phase 2) |

### Pre-requisitos

1. **La migration SQL `20260426_people_onboarding_audit.sql` ya aplicada** en Supabase Studio.
   (Solo necesitamos `people_onboarding_steps` para Phase 7c — las demás tablas ya existen.)
2. `/app/backend/.env` con:
   - `MONGO_URL` (obvio)
   - `SUPABASE_URL` + `SUPABASE_ANON_KEY` (mínimo)
   - `QUANTRO_DEFAULT_ORG_ID` (uuid del organization "Quantro")
   - **Recomendado**: `SUPABASE_SERVICE_ROLE_KEY` para bypass RLS y poder escribir filas que no son del usuario que corre el script.

### Cómo correr

```bash
cd /app/scripts

# 1) DRY-RUN completo (default — no escribe nada).
python backfill_mongo_to_supabase.py

# 2) Dry-run de una sola tabla.
python backfill_mongo_to_supabase.py --table members
python backfill_mongo_to_supabase.py --table invites
python backfill_mongo_to_supabase.py --table audit
python backfill_mongo_to_supabase.py --table provider_connections

# 3) Spot-check con 50 filas.
python backfill_mongo_to_supabase.py --limit 50

# 4) RUN REAL una vez que el dry-run se ve limpio.
#    Pide confirmación interactiva escribiendo "YES".
python backfill_mongo_to_supabase.py --execute

# 5) Run real sin prompt (CI/scripted).
python backfill_mongo_to_supabase.py --execute --yes

# 6) Reporte JSON para auditoría.
python backfill_mongo_to_supabase.py --execute --yes --json-out /tmp/backfill.json
```

### Salvaguardas

- **Dry-run por default** — necesitás `--execute` para tocar Supabase.
- **Confirmación interactiva** — al usar `--execute` te pide tipear `YES`. Saltá con `--yes`.
- **Dedup por claves naturales**:
  - `org_members`: `(org_id, user_id)`
  - `invitations`: `token`
  - `org_audit_logs`: `(org_id, action, target_user_id, created_at)`
- **Validación de UUIDs** — filas con `user_id` legacy (formato `user_test_xxx`) se saltan con `skip:bad_uuid`.
- **Mapping workspace_id → org_id**:
  - `default_workspace` → `QUANTRO_DEFAULT_ORG_ID`
  - cualquier otro workspace requiere campo `org_id` en su documento Mongo (`db.workspaces.updateOne(...)`)
  - sin mapping → `skip:no_mapping`
- **Eventos de audit fuera de la enumeración** (workspace.*, policy.*, integration.*) se saltan con `skip:unmapped_action` para no contaminar el timeline.
- **Idempotente** — re-ejecutar después de un run parcial es seguro: las filas que ya están en Supabase se reportan como `skip:duplicate`.
- **Cross-link** — al insertar invites en Supabase, el script actualiza el doc Mongo con `supabase_invite_id` + `supabase_token` para que los shadow-writes futuros (revoke) encuentren el row correcto.

### Output esperado

```
[supabase] https://ukoot...supabase.co  auth=service-role
[mapping] 3 workspace(s) mapped to Supabase orgs:
   - default_workspace              → 1250ff9b-ac04-4370-8fd3-f846f34d1159
   - ws_acme_corp                   → 6cb2a3e1-...
   - ws_beta_labs                   → 91d5fb40-...

[mode] EXECUTE — rows will be written to Supabase.
Type 'YES' to proceed: YES

--- workspace_members → org_members ---
  [skip:duplicate] org=1250ff9b-... user=2a8f4e1c-...
  [ok] inserted user=7c3b9a2d-...
  [skip:bad_uuid] user_id='user_test_20aaa7f9' is not a uuid (legacy account)
  ...

======================================================================
BACKFILL SUMMARY
======================================================================

[members] total seen: 142
   - inserted                          78
   - skip:duplicate                    52
   - skip:bad_uuid                     12

[invites] total seen: 28
   - inserted                          24
   - skip:duplicate                     2
   - skip:no_token                      2

[audit] total seen: 1054
   - inserted                         320
   - skip:duplicate                    87
   - skip:unmapped_action             612  (workspace.*, policy.*, integration.*)
   - skip:no_target_uuid               35
```

### Después del backfill

1. Verifica conteos en Supabase Studio:
   ```sql
   select count(*) from public.org_members;
   select count(*) from public.invitations;
   select count(*) from public.org_audit_logs;
   ```
2. Mueve el read-source a Supabase: en `/app/backend/.env`:
   ```env
   QUANTRO_DB_PRIMARY=supabase
   ```
3. `supervisorctl restart backend`.
4. Si algo se rompe, vuelves a `mongo` y los dual-writes mantienen sincro.
5. Cuando todo esté validado por unas semanas, podemos apagar las escrituras a Mongo (Phase 7d).

## Phase 2 secrets

See `docs/phase2-oauth-secrets.md`. Requires migration `20260918000000_provider_oauth_secrets.sql`.
