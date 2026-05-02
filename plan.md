# plan.md (Updated)

## 1. Objectives
- Deliver a modern, premium **dark-first**, OS-like SaaS web app: **Quantro Flow | Business OS**.
- Ship a connected, production-feeling workflow engine:
  **Smart Inbox → AI triage (single + batch) → automation policy evaluation → (auto-run OR review & control) → (simulated) Calendar/CRM updates → activity + execution trail**.
- Maintain **multi-industry adaptability** via configuration (Business Profile) — no industry-specific rewrites.
- Make Settings the **operational control center** where the system becomes real:
  - API keys (OpenAI/LLM)
  - Gmail / Google Calendar connections (OAuth-ready, simulated for now)
  - CRM connections (API-key based)
  - Webhooks/endpoints
  - Automation governance
- Keep integrations mocked/simulated for now, but ensure the UI/UX is **production-grade** and trust-building.
- **Expose the self-healing layer as a user-facing trust signal**:
  - “System Status: Healthy / Auto‑Repaired / Degraded”
  - Surface integrity checks + repair explanations
- **Ship a robust multilingual system (i18n) as an OS-level capability** (ES + EN):
  - UI text + dashboard labels
  - Settings and integrations control center
  - Self-healing surface copy
  - AI-generated content language enforcement via prompt injection
- **Ship Simulation Mode as a first-class product control (not demo data)**:
  - Simulation Mode ON: realistic, industry-specific sample dataset drives the full app.
  - Live Mode: uses exclusively real workspace records.
- **Guarantee strict Simulation vs Live data isolation (critical trust requirement)**:
  - Simulation Mode → sandbox dataset only
  - Live Mode → real workspace dataset only (`is_simulation != True`)
  - **Zero mixing** and **zero ambiguity** about which dataset is visible.
- **Ship SaaS foundation with strict tenant isolation**:
  - **Supabase Auth** (shared project with https://quantro.technology landing)
  - Multi-workspace per user (MongoDB-backed)
  - Workspace-scoped operational model (MongoDB)
  - Billing/plan truth in Supabase (`profiles`)
  - Audit logging foundation for trust and compliance
- **Enforce AI cost controls (no free AI bleeding)**:
  - Replace Emergent LLM key usage with an internal **USD-based AI Credits** system
  - Block coupon/trial users from Quantro credits and require their own OpenAI key
  - Force **`gpt-4o-mini`** when using Quantro credits
  - Debit credits after successful generations and log per-request usage

**Current status (as of this update):**
- ✅ **Phases 1–6 complete** (core app + workflow engine + policies/escalations + templates + auto-execution + Business OS transformation).
- ✅ **Phase 7a-sup complete:** Supabase Auth + workspace scoping
  - Frontend uses Supabase Auth (email/password)
  - Backend verifies Supabase JWTs (JWKS ES256 + HS256 fallback)
  - Mongo operational data stays workspace-scoped
  - Plan & Usage reads real data from Supabase (`profiles`, `ai_usage`)
- ✅ **Phase 7d-pre complete (P0): AI Credits wrapper enforcement**
  - Centralized `run_ai_request(...)` wrapper
  - Removed `EMERGENT_LLM_KEY` and all Emergent LLM client usage
  - Migrated all AI endpoints to wrapper (inbox analyze, batch analyze, content generate, template generate)
- ✅ **Phase 7b complete:** RBAC + invitations + multi-workspace UX
  - 5-tier roles (owner/admin/manager/operator/agent)
  - Member management endpoints + UI
  - Token-based invite links (email-free) + acceptance flow
  - RBAC applied to key governance/admin endpoints
  - Backend verified: **95.5% pass (63/66), 0 critical bugs** (`iteration_12.json`)
- ⏳ **Pending validation (requires live Supabase login with real accounts):**
  - Invite edge cases: revoked/expired/max-uses (410), idempotent accept
  - Ownership transfer end-to-end (updates `workspaces.owner_user_id` and demotes previous owner to admin)
  - Real multi-user role matrix verification (manager/operator/agent behavior)
- ✅ **Phase 7c (migration) complete:** MongoDB → Supabase backfill executed
  - `workspace_members` → `org_members`: 1 insertado (`0dd8aa94-…` como `leader`), 9 deduplicados contra existentes, 4 seeds de test descartados
  - `workspace_invites` → `invitations`: colección Mongo vacía, nada que migrar
  - `audit_log` → `org_audit_logs`: 17 filas fuera del vocabulario estricto (`workspace.*`, `auth.*`, `integration.*`), descartadas por diseño
  - Identity reconciliation: alias legacy `2c6c39bc-…` → Supabase `0dd8aa94-…` aplicado
  - Script idempotente + service-role seguro (sin exponer la key)
  - Validado via `SELECT` en Supabase: 2 miembros reales (`owner` + `leader`) en el default org
- ✅ **Phase 7c-resolver fix:** Supabase-aware workspace resolver
  - Nuevo helper `supabase_admin.list_orgs_for_user(user_id)` (service-role)
  - Nuevo `reconcile_supabase_memberships_to_mongo(user_doc)` ejecutado en cada login
  - Sincroniza memberships Supabase → Mongo: resuelve org→workspace, upsert rol, preserva joined_at
  - One-off patches: `workspaces["default"].org_id` seteado, workspace huérfano de Josias eliminado
  - Validado con login real de `josias.mont@hotmail.com` → ahora entra al default workspace como Leader ✅
- ✅ **Phase 7c-export:** Audit Logs exportables (CSV/JSON)
  - Endpoint `GET /api/workspaces/{id}/audit/export?format=csv|json&start_date=&end_date=&action=`
  - Lee de Supabase si es primary, con fallback automático a Mongo
  - UI: toolbar en tab Auditoría con filtros (fecha desde/hasta, acción) + botón Export con dropdown CSV/JSON
  - Cada export se registra en el propio audit log (`audit.exported`) para compliance
  - CSV incluye BOM UTF-8 para compatibilidad con Excel
  - Auth: leader+ only (mismo que list_audit)
- ✅ **Phase 7c-cleanup:** Limpieza total de Mongo legacy
  - Borrados 12 workspaces legacy (`ws_test_*`, `ws_1e70d…`, `ws_5*`, `ws_d*`, `ws_f*`, `ws_9*`, `ws_b*`, `ws_3a10…`, `ws_168c…`, etc.)
  - Borrados datos asociados: 60 integrations_config, 12 business_profile, 12 workspace_members legacy, 12 audit_logs de seed, 2 contacts de test
  - Borrados seeds de test (`user_test_20aaa7f9`, `user_test2_b`) y sus memberships huérfanos
  - Workspace default renombrado: `Test User Workspace` → **Quantro**
  - Owner real asignado al default: `c342ed89-…` (contacto@kontagroup.com)
  - Estado final Mongo: 1 workspace (`Quantro`), 2 miembros reales (owner + leader)
- ✅ **Phase 7c-rename:** Feature user-facing de renombrar workspace
  - Endpoint `PATCH /api/workspaces/{workspace_id}` (leader+, registra `workspace.renamed` en audit)
  - UI: pill con nombre del workspace + botón ✎ Pencil en el header de Members → abre Dialog de rename
  - Validación: 1-80 chars, trim de whitespace, refresh automático del AuthContext
  - i18n (ES+EN) completo
- ✅ **Phase 7c-swap:** `QUANTRO_DB_PRIMARY=supabase` activado
  - Backend verificado en runtime: `is_supabase_primary=True`, `service_role_available=True`
  - `list_orgs_for_user` funcionando contra ambos usuarios reales
  - Dual-write seguirá activo hacia Mongo para backward compatibility
- ⏭️ Next: **Phase 7d roadmap** — refactor cyclomatic complexity + split de pages grandes

## Phase 7e — Google OAuth Real (en progreso)

### ✅ Implementado
- **`/app/backend/google_oauth.py`** — módulo aislado con:
  - Encriptación Fernet (AES-128-CBC + HMAC) para access/refresh tokens en reposo
  - `build_authorization_url`, `exchange_code_for_tokens`, `credentials_from_tokens`, `maybe_refresh`
  - Auto-refresh transparente (rota access token cuando faltan <60s para expirar)
  - Helpers de fetch: `fetch_recent_gmail(limit=50)`, `fetch_upcoming_calendar(days=30)`, `revoke_token`
  - `is_oauth_configured()` + `resolve_redirect_uri()` para fallar limpio cuando falten credenciales
- **4 endpoints REST** (`/api/integrations/google/*`):
  - `GET /status` — dice si el workspace tiene una conexión activa + email + scopes + last_sync_at
  - `GET /start?return_to=` — genera state UUID, lo persiste con TTL 10min y devuelve `auth_url` para redirect
  - `GET /callback?code&state` — valida state, intercambia code por tokens, encripta y persiste, hace audit log, redirige a `<frontend>/welcome/inbox?google_connected=success&account=...`
  - `POST /sync` — pulls 50 últimos Gmail + 30 días Calendar, upsert idempotente, marca `is_real=true` en inbox/calendar, oculta los seeds simulation, flipea `simulation_mode=False`
  - `DELETE /disconnect` — revoca tokens en Google + borra DB + restaura seed simulation
- **Frontend** (`StepInbox`, `StepCalendar`, `OnboardingShell`):
  - Click en "Conectar con Google" → llamada real a `/start` → `window.location.href = auth_url` (full-page redirect, no popup)
  - `<GoogleCallbackHandler>` invisible dentro de `<OnboardingProvider>` detecta `?google_connected=success`, dispara `/sync`, marca `connection_mode='real'` y limpia query string
  - Step Calendar fast-path: si Google ya está conectado en este workspace, salta directo sin reconsentir (mismo OAuth cubre ambos scopes)
  - Toast diferenciado: `real_connected_title` (success), `real_failed_title` (error), `real_connected_no_sync_title` (link OK pero sync falló)
- **Seguridad**:
  - Tokens encriptados en reposo con Fernet (clave `GOOGLE_TOKENS_ENCRYPTION_KEY` ya generada y persistida en `/app/backend/.env`)
  - Estado OAuth con TTL 10min para prevenir replay attacks
  - `find_one_and_delete` del state: cada state se usa exactamente una vez
  - Refresh token rotation: si Google rota el refresh token al refrescar el access, persistimos el nuevo
  - Revocación bidireccional: disconnect llama a Google `/revoke` antes de borrar localmente

### ⚠️ Pendiente del lado del usuario (one-off)

Para activar la conexión real, configurar **una sola vez** en Google Cloud Console:

1. Crear/elegir proyecto en https://console.cloud.google.com
2. Habilitar **Gmail API** + **Google Calendar API** desde Library
3. Configurar **OAuth consent screen** (External): app name `Quantro Flow`, scopes `openid + email + profile + gmail.readonly + calendar.readonly`, agregar test users
4. Crear **OAuth 2.0 Client ID** (Web application):
   - Authorized JavaScript origin: `https://quantro-os.preview.emergentagent.com`
   - Authorized redirect URI: `https://quantro-os.preview.emergentagent.com/api/integrations/google/callback`
5. Copiar `Client ID` + `Client Secret` y pegarlos en `/app/backend/.env`:
   ```
   GOOGLE_CLIENT_ID=<el client_id>
   GOOGLE_CLIENT_SECRET=<el client_secret>
   ```
6. Reiniciar backend: `sudo supervisorctl restart backend`

A partir de ese momento, todo usuario que haga click en **Conectar con Google** dentro del Welcome flow va a hacer OAuth real, sus emails y eventos van a aparecer en Smart Inbox y Schedule, y la pantalla Ready va a mostrar `Datos reales` cyan.

### ⏭️ Phase 7e remaining
- Banner persistente en Smart Inbox / Schedule diferenciando "Datos reales" vs "Modo demo"
- UI en Settings → Integrations para reconectar / desconectar Google manualmente (post-onboarding)
- Sync periódico en background (cron job o scheduler) cada 15 min para mantener datos frescos
- Soporte multi-provider (Outlook, Yahoo, IMAP genérico) — sesiones siguientes

---

## 2. Implementation Steps

### Phase 1 — Core AI POC (isolation; do not proceed until stable)
**Status: ✅ Completed**

**User stories (delivered)**
1. Intent detection returns structured JSON results.
2. Confidence + extracted entities included.
3. Consistently parseable JSON across runs.
4. Safe fallback behavior for ambiguous messages (`needs_review`).
5. Content generation produces social + email drafts.

---

### Phase 2 — V1 App Development (build around proven core; no auth)
**Status: ✅ Completed**

---

### Phase 3 — Workflow Engine Upgrade (Batch Triage + Manual Control Layer)
**Status: ✅ Completed**

---

### Phase 4 — Workflow Governance + Communication Layer (Automation Policies + Templates)
**Status: ✅ Completed**

---

### Phase 5 — Automation Engine Upgrade (Auto-Execution + Advanced Escalations)
**Status: ✅ Completed**

---

### Phase 6 — Business OS Transformation (Rebrand + Configurability + Settings)
**Status: ✅ Completed (production-ready)**

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)

#### Phase 7a-sup — Supabase Auth + Workspace Creation + Strict Workspace Scoping
**Status: ✅ Completed / ⏳ pending production E2E validation**

**Exit criteria still pending**
- Existing landing accounts can sign in to Quantro Flow
- Core app operates normally under workspace scoping

---

#### Phase 7d-pre — AI Credits System + Backend Wrapper Enforcement (Cost Control)
**Status: ✅ Implemented / ⏳ pending deployed E2E verification**

**Implemented**
- `/app/backend/ai_billing.py`:
  - Supabase REST helpers (profile fetch, decrement RPC, usage insert)
  - `run_ai_request(...)` wrapper (force model, compute cost, debit/log)
- `/app/backend/server.py`:
  - All AI endpoints migrated to wrapper
  - Access token propagated via `User.access_token`

**Pending E2E (Supabase live)**
- Ensure migration `20260425_ai_credits_schema.sql` is applied
- (Recommended) set `SUPABASE_SERVICE_ROLE_KEY` so `ai_credit_usage` inserts succeed under RLS

---

#### Phase 7b — RBAC + Invitations + Multi-workspace UX
**Status: ✅ Completed (backend verified)**

**Goals (delivered)**
- Workspace switching UI (Sidebar user dropdown)
- Workspace member management UI (Members page)
- Invitation links (token-based, email-free) with acceptance page
- RBAC enforcement across backend on governance/admin endpoints

**Backend implementation (delivered)**
- 5-tier role mapping:
  - `ROLE_RANK = { agent:1, operator:2, manager:3, admin:4, owner:5 }`
- RBAC dependency:
  - `require_role(min_role)` → returns 403 with `{error: 'rbac_forbidden', required_role, your_role}`
- New Mongo collection: `workspace_invites` (token: `secrets.token_urlsafe(24)`)
- New endpoints (8 total):
  - Members:
    - `GET /api/workspaces/{workspace_id}/members`
    - `PATCH /api/workspaces/{workspace_id}/members/{target_user_id}`
    - `DELETE /api/workspaces/{workspace_id}/members/{target_user_id}`
  - Invites:
    - `POST /api/workspaces/{workspace_id}/invites`
    - `GET /api/workspaces/{workspace_id}/invites`
    - `DELETE /api/workspaces/{workspace_id}/invites/{invite_id}`
    - `GET /api/invites/{token}` (peek)
    - `POST /api/invites/{token}/accept` (accept)
- Owner-only carveouts:
  - Only owner can manage admin/owner roles
  - Ownership transfer demotes previous owner to admin and updates `workspaces.owner_user_id`
- Member lifecycle rules:
  - Self-leave allowed for non-owners
  - Owner cannot be removed
  - Admin removal requires owner
- RBAC applied to existing endpoints:
  - **Manager+**: templates, policies, escalation rules CRUD
  - **Admin+**: business-profile update, integrations update/test, simulation generate/clear
  - Note: Inbox/CRM/content writes intentionally NOT gated in this phase (deferred; needs product decision around agent vs operator).

**Frontend implementation (delivered)**
- Sidebar:
  - Workspace switcher inside user dropdown (roles + current check)
  - Create workspace CTA
  - Shortcut to Members page
- New pages:
  - `/members` — tabbed Members + Invites management
  - `/join/:token` — invite acceptance UX (auth-gated; redirects to `/login?next=...`)
- API helpers added to `/app/frontend/src/lib/api.js`:
  - `listMembers`, `updateMemberRole`, `removeMember`
  - `listInvites`, `createInvite`, `revokeInvite`, `peekInvite`, `acceptInvite`
- i18n:
  - Added `members.*`, `invite.*`, `sidebar.members` in ES + EN

**Testing**
- Backend testing agent: **iteration_12.json** → 63/66 passed, 0 critical bugs
- Lint: backend + frontend clean

**Pending validation (live)**
- Multi-user role matrix verification
- Invite 410 cases (revoked/expired/max-uses)
- Idempotent accept behavior confirmation
- Ownership transfer in real environment

---

#### Phase 7c — Audit Logs UI + Export (CSV/JSON) + Deep Trust Events
**Status: ⏭️ Ready (next)**

**Why now**
- Phase 7b created many high-value governance events (members/invites/workspace switches)
- Backend already writes `audit_log_col` events; making them visible/exportable completes the compliance/trust loop.

**Goals**
- Make audit logs user-visible and exportable
- Provide compliance-friendly evidence of:
  - workspace lifecycle (claimed/created/switched)
  - member role changes and removals
  - invite creation/revocation/acceptance
  - policy and integration governance
  - (optional) AI credit blocks / billing events

**Deliverables (planned)**
- Backend:
  - `GET /api/audit` list endpoint with filters (workspace_id, event_type, date range)
  - `GET /api/audit/export` (CSV + JSON)
  - RBAC: viewer = operator+, export = admin+ (proposed)
- Frontend:
  - Audit Logs screen with search + filters + pagination
  - Export buttons (CSV/JSON)

---

## 3. Next Actions

**Immediate (P0): Validate Phase 7b end-to-end with real Supabase users**
1) Sign in as an owner/admin account.
2) Go to **Members** (`/members`).
3) Create an invite (operator role). Copy the link.
4) Sign in as a second user, open `/join/:token`, accept.
5) Verify:
   - second user appears in `/members`
   - switch workspace works and data is isolated
6) Revoke an invite and verify peek/accept returns **410**.
7) Test ownership transfer from Owner → Admin and verify:
   - `workspaces.owner_user_id` updates
   - previous owner becomes admin

**Immediate (P0): Validate AI Credits wrapper end-to-end on Supabase (still pending)**
8) Ensure migration is applied: `20260425_ai_credits_schema.sql`.
9) Set `SUPABASE_SERVICE_ROLE_KEY` for `ai_credit_usage` inserts (optional but recommended).
10) Trigger `/api/content/generate` and confirm:
   - `profiles.ai_credits_used` increments
   - `profiles.ai_credits_remaining` decrements
   - `ai_credit_usage` row appears

**Next (P1): Start Phase 7c — Audit Logs UI + Export**
11) Implement backend audit list/export endpoints + RBAC.
12) Implement frontend Audit Logs page + export UX.

**Secondary (P2 hardening)**
13) Refactor oversized modules:
  - Backend: `server.py`
  - Frontend: `SmartInbox.js`, `ContentEngine.js`, `Dashboard.js`, `PlanAndUsage.js`

---

## 4. Success Criteria

**Achieved (Phases 1–6):**
- Workflow engine: Inbox → AI triage → policies → auto-run or manual control → mocked downstream actions → transparent execution trail.
- Premium dark UI across modules.

**Phase 7a-sup (Auth + workspace scoping):**
- ✅ Shared Supabase project (no new DB)
- ✅ Frontend auth via Supabase
- ✅ Backend verifies Supabase JWTs
- ✅ Mongo operational data remains workspace-scoped
- ⏳ Production E2E validation with real landing accounts

**Phase 7d-pre (AI Credits enforcement):**
- ✅ All backend AI endpoints are routed through `run_ai_request`
- ✅ Quantro-credit usage forces `gpt-4o-mini`
- ✅ Coupon/trial users cannot consume Quantro credits
- ⏳ Credits are decremented and usage is logged in live Supabase (requires schema + optional service-role key)

**Phase 7b (RBAC + invitations + multi-workspace UX):**
- ✅ Role hierarchy implemented
- ✅ Member CRUD + invite token flow implemented
- ✅ RBAC enforced on governance/admin endpoints
- ✅ Frontend workspace switcher + Members page + join page shipped
- ⏳ Live multi-user verification completed

**Phase 7c (Audit logs):**
- Audit logs are visible, filterable, and exportable (CSV/JSON)
- RBAC enforced on audit visibility/export
- Audit coverage includes workspace lifecycle, member/invite events, policy/integration governance, and (optional) AI billing/credit events
