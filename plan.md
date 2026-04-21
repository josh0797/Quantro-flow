# plan.md (Updated)

## 1. Objectives
- Deliver a premium **dark-first**, OS-like SaaS web app: **Quantro Flow | Business OS**.
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
- **Expose the self-healing layer as a user-facing trust signal** (Apple/Stripe-style):
  - “System Status: Healthy / Auto‑Repaired / Degraded”
  - “Quantro Flow detects and fixes issues before you notice them.”
  - Surface integrity checks + repair explanations.
- **Ship a robust multilingual system (i18n) as an OS-level capability**, not a simple UI translation layer:
  - UI text + dashboard labels
  - Settings and integrations control center
  - Self-healing surface copy
  - Decision system (Quantro Revenue / Action Center) via **keys**, not stored translated strings
  - AI-generated content language enforced via prompt injection
- **Ship Simulation Mode as a first-class product control (not demo data):**
  - Simulation Mode ON: realistic, industry-specific sample dataset drives the full app.
  - Live Mode: uses exclusively real workspace records (manual + integrated).
  - Mode switching is instant, safe, and **never destroys real data**.
- **Guarantee strict Simulation vs Live data isolation (critical trust requirement):**
  - Simulation Mode → sandbox dataset only
  - Live Mode → real workspace dataset only (`is_simulation != True`)
  - **Zero mixing** and **zero ambiguity** about which dataset is visible.
- **Ship SaaS foundation with strict tenant isolation**:
  - Google OAuth (Emergent Managed Google Auth)
  - Multi-workspace per user
  - Workspace-scoped data model across all operational and configuration collections
  - Audit logging foundation for trust and compliance

**Current status (as of this update):**
- ✅ **Phases 1–5 complete** (Core app + workflow engine + policies/escalations + templates + auto-execution).
- ✅ Global rebrand + multi-industry UI adaptation implemented across all main pages.
- ✅ Simulation Layer (backend) implemented and wired to Business Profile.
- ✅ **Settings Operational Control Center** complete.
- ✅ Backend integrations config is **self-healing** (auto-seeded on startup; idempotent).
- ✅ **System Health surface layer shipped** (Settings banner + Dashboard card + repair toast + backend health endpoint/events).
- ✅ **Multilingual i18n system shipped** (ES + EN) with global Language Context, translation keys, persistence, and AI language enforcement.
- ✅ **Brand rename shipped:** **Quantro One → Quantro Flow**.
- ✅ **Simulation Mode UX shipped:** persistent toggle in Sidebar + Settings, localized, confirmation modal on Simulation→Live, localStorage mirroring.
- ✅ **Phase 6.10 complete:** Simulation/Live Data Wiring Hardening (**strict dataset isolation + E2E verification complete**).
- ✅ **Phase 7a complete:** Auth + Workspace creation + Workspace-scoped DB (**backend 100%, frontend 100%**).
- ⏭️ Next: **Phase 7b** (multi-workspace UX + invitations + RBAC enforcement) and **Phase 7c** (audit logs UI + export).

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

**What was implemented**
- OpenAI GPT-4o integration using **Emergent LLM Key**.
- Robust prompts enforcing **JSON-only** outputs for:
  - Inbox intent detection + suggested action
  - Content generation
- POC test script:
  - `/app/tests/test_core_ai.py` (10/10 passed)

---

### Phase 2 — V1 App Development (build around proven core; no auth)
**Status: ✅ Completed**

**Delivered**
- Premium dark UI and full module set:
  - Dashboard, Smart Inbox, Schedule, CRM, Onboarding, Content Engine
- Backend seed data and endpoints for end-to-end demo workflows.

---

### Phase 3 — Workflow Engine Upgrade (Batch Triage + Manual Control Layer)
**Status: ✅ Completed**

**Delivered**
- Batch triage endpoints + UI multi-select.
- Review & Control manual override UI and endpoints.

---

### Phase 4 — Workflow Governance + Communication Layer (Automation Policies + Templates)
**Status: ✅ Completed**

**Delivered**
- Automation Policies (confidence tiers → actions).
- Escalation Rules CRUD.
- Content Templates CRUD + AI generation.

---

### Phase 5 — Automation Engine Upgrade (Auto-Execution + Advanced Escalations)
**Status: ✅ Completed**

**Delivered**
- Auto-execution pipeline:
  - `execute_action_for_item()` executes mocked actions.
  - Inbox items marked `status=auto_actioned` with `execution_results`.
- Advanced escalation evaluation:
  - `calendar_conflict`, `incomplete_entities`, `urgency`, `contact_type` (+ `intent`, `keyword`).
- UI updates:
  - Smart Inbox shows auto-executed badge + execution trail.
  - Escalation reasons rendered.
  - Automation rule editor supports advanced condition types.

---

### Phase 6 — Business OS Transformation (Rebrand + Configurability + Settings)
**Status: ✅ Completed (production-ready)**

**Primary goal (Phase 6)**
Transform the product from:
- “Quantro One | Realty OS” (real-estate specific)

into:
- **“Quantro Flow | Business OS”** (horizontal, configurable, multi-industry)

#### 6.1 Global Rebranding (Quantro Flow | Business OS)
**Status: ✅ Completed**

#### 6.2 Business Profile (Core System Layer)
**Status: ✅ Completed**

**Business Profile fields (delivered)**
- Industry, Use case, Entity labels
- `simulation_mode`
- `language` (`"es" | "en"`)

**Endpoints**
- `GET /api/business-profile`
- `PUT /api/business-profile`

#### 6.3 Settings Section (Operational Control Center)
**Status: ✅ Completed (production-grade + QA-validated)**

#### 6.4 System Health / Self-Healing Surface Layer (Trust Signal)
**Status: ✅ Completed**

#### 6.5 Multilingual System (i18n) — OS-level capability
**Status: ✅ Completed (ES + EN shipped)**

#### 6.6 Simulation Layer UX (First-class product control)
**Status: ✅ Completed**

#### 6.7 Data model: “Workspace-ready” scoping (single-tenant)
**Status: ✅ Completed via Phase 7a**

#### 6.8 UX Guidelines (apply throughout Phase 6)
**Status: ✅ Completed**

#### 6.9 Testing & verification (Phase 6)
**Status: ✅ Completed**

#### 6.10 Simulation/Live Data Wiring Hardening (Strict Isolation)
**Status: ✅ Completed (P0 / critical trust requirement satisfied)**

**Key implementation (delivered)**
- `backfill_simulation_flag()` startup backfill
- `get_mode_filter()` applied to all operational reads
- Writes tagged with `is_simulation`
- Non-destructive Simulation↔Live toggling
- Auto-seed simulation dataset on first Simulation entry
- Frontend re-fetch on mode change + Live empty-state guidance (`LiveEmptyState`)

**Testing (completed)**
- Backend: **100% pass** (`/app/test_reports/iteration_6.json`).
- Frontend: passed cross-module verification.

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)

#### Phase 7a — Auth + Workspace Creation + Strict Workspace Scoping
**Status: ✅ Completed (stable; verified)**

**User-approved configuration (implemented)**
- Auth provider: **Emergent Managed Google Auth**
- Tenancy model: **multi-workspace per user**
- First-time onboarding: **auto-create/claim personal workspace**
  - First authenticated user claims legacy `workspace_id="default"` workspace (no data loss)
  - Subsequent users get a fresh personal workspace

**What was implemented (delivered)**
1) **Auth endpoints (backend)**
- `POST /api/auth/session` (session_id exchange)
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `POST /api/auth/workspaces` (create workspace)
- `POST /api/auth/workspaces/switch` (switch current workspace)

2) **Auth model (backend)**
- Collections:
  - `users`, `user_sessions`, `workspaces`, `workspace_members`

3) **Workspace scoping (backend)**
- Added `workspace_id` across **all operational + config** collections.
- Startup backfill: `backfill_workspace_scoping()` tags all legacy docs as `workspace_id="default"`.
- Read/write endpoints now scope by active workspace via `get_current_workspace_id()`.

4) **Simulation isolation preserved per workspace (backend)**
- `get_mode_filter(workspace_id)` returns `{workspace_id, is_simulation: ...}`.
- `dashboard/metrics` includes `simulation_mode` for the **current workspace**.

5) **Audit logging foundation (backend)**
- `audit_log` collection + `log_audit()` helper.
- Events captured at minimum for auth + integrations connect/disconnect.

6) **Frontend auth (delivered)**
- `AuthContext` + `AuthProvider`
- `ProtectedRoute`
- `LoginPage` + `AuthCallback`
- Sidebar user menu (name/workspace + logout)

**Important production constraint handled**
- Due to ingress forcing `Access-Control-Allow-Origin: *` (cookie credentials blocked),
  the frontend uses **Bearer session tokens** stored in `localStorage` (`quantro_session_token`).

**Testing (completed)**
- ✅ Backend Phase 7a suite: **100% pass** (`/app/test_reports/iteration_8.json`).
- ✅ Frontend Phase 7a suite: **100% pass** (`/app/test_reports/iteration_9.json`).

**Exit criteria (met)**
- ✅ User can sign in via Google (Emergent-managed flow)
- ✅ Workspace is auto-created/claimed
- ✅ Legacy default data is preserved and associated with the claimed workspace
- ✅ All reads/writes are strictly workspace-scoped
- ✅ Simulation vs Live isolation remains strict inside each workspace

---

#### Phase 7b — Multi-workspace UX + Invitations + RBAC Enforcement
**Status: ⏭️ Ready (requires explicit user approval to start)**

**Goals**
- Workspace switching UI (workspace selector in sidebar/settings)
- Workspace member management UI
- Invitation links (token-based, email-free)
- RBAC enforcement (Owner/Admin/Manager/Operator/Agent) across backend + UI

**Deliverables (planned)**
- Backend:
  - Invite token endpoints
  - Membership CRUD + role assignments
  - RBAC dependency (`require_role`) and permission matrix for endpoints
- Frontend:
  - Workspace switcher
  - Members screen + role editor
  - Invite link generation + revoke

**Testing**
- Verify strict workspace isolation under multi-workspace switching.
- Verify permissions matrix for each role.

---

#### Phase 7c — Audit Logs UI + Export (CSV/JSON) + Deep Trust Events
**Status: ⏭️ Ready (requires explicit user approval to start)**

**Goals**
- Make audit logs user-visible and exportable.
- Capture critical trust events:
  - Simulation↔Live toggles
  - integrations connect/disconnect
  - automation actions executed
  - self-healing repair events

**Deliverables (planned)**
- Backend:
  - `/api/audit` list endpoint (filter by date/event_type/user)
  - `/api/audit/export` (CSV + JSON)
  - Expand audit coverage for automation + simulation toggles + system health repairs
- Frontend:
  - Audit Logs screen (filters, search, pagination)
  - Export actions

---

## 3. Next Actions

**Immediate (P0/P1):**
1) **Hold for user approval** on whether to start:
   - **Phase 7b** (multi-workspace UX + invitations + RBAC enforcement)
   - OR **Phase 7c** (audit logs UI + export)
2) Phase 7a polish (optional):
   - Workspace switcher UI (if you want this in 7a scope, otherwise defer to 7b)
   - Remove any remaining legacy references to `profile_id="default"` (keep backward compatibility but prefer workspace_id)

**Secondary (P2 hardening):**
3) Refactor oversized modules:
   - Backend: `server.py`
   - Frontend: `SmartInbox.js`, `ContentEngine.js`, `Dashboard.js`
4) Optional: add webhook inbound handler to match displayed endpoint.

---

## 4. Success Criteria

**Achieved (Phases 1–5):**
- Workflow engine: Inbox → AI triage → policies → auto-run or manual control → mocked downstream actions → transparent execution trail.
- Premium dark UI across modules.
- Advanced escalation safety net.

**Phase 6 Success Criteria (Business OS Transformation): ✅ ACHIEVED**
- ✅ App fully rebranded to **Quantro Flow | Business OS**.
- ✅ Terminology industry-agnostic and configurable.
- ✅ Business Profile drives:
  - dynamic UI labels
  - AI context for classification + generation
  - i18n language enforcement
- ✅ Settings provides a SaaS-grade control surface.
- ✅ Integrations seeding is idempotent and self-healing; Integrations UI never blanks.
- ✅ Self-healing is user-visible as a trust signal.
- ✅ i18n shipped with full EN/ES coverage + persistence.
- ✅ Simulation Mode UX shipped as a first-class control.

**Phase 6.10 Success Criteria (Data Layer Isolation): ✅ ACHIEVED**
- ✅ Simulation Mode is a **true sandbox**: only `is_simulation: True` data is visible and writable.
- ✅ Live Mode is a **true workspace view**: only `is_simulation != True` data is visible and writable.
- ✅ Switching modes never deletes real data and never causes data leakage.
- ✅ Dashboard metrics + AI suggestions respect the current mode.
- ✅ Live empty state is intentional, clean, and guides the user to connect integrations or create first records.

**Phase 7a Success Criteria (Auth + Workspace + Migration + Scoping): ✅ ACHIEVED**
- ✅ User can log in via Google (Emergent Managed Auth).
- ✅ A workspace is automatically created/claimed.
- ✅ Existing default data migrated/associated to that workspace.
- ✅ All queries/writes scoped by `workspace_id`.
- ✅ App works as before but under authenticated context.
- ✅ No cross-workspace data leakage.
- ✅ Simulation vs Live remains strict within each workspace.

**Phase 7 Success Criteria (SaaS Foundation):**
- Phase 7b:
  - Multi-workspace UX + invitation links
  - RBAC enforced across API + UI
- Phase 7c:
  - Audit logs user-visible, filterable, and exportable (CSV + JSON)
  - Audit coverage includes Simulation toggles, integrations connect/disconnect, automation executions, and self-healing events
