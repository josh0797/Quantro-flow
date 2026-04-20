# plan.md (Updated)

## 1. Objectives
- Deliver a premium **dark-first**, OS-like SaaS web app: **Quantro One | Business OS**.
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
- Prepare for future SaaS scaling (multi-tenant, auth, RBAC, audit export) **without shipping auth yet**.

**Current status (as of this update):**
- ✅ **Phases 1–5 complete** (Core app + workflow engine + policies/escalations + templates + auto-execution).
- ✅ Global rebrand + multi-industry UI adaptation implemented across all main pages.
- ✅ Simulation Layer (backend) implemented and wired to Business Profile.
- ✅ **Settings Operational Control Center** complete.
- ✅ Backend integrations config is **self-healing** (auto-seeded on startup; idempotent).
- ✅ **Session 3C — Testing & Polish completed successfully** (backend self-healing QA + frontend cross-module regression).
- 🟢 **Phase 6 complete and production-ready**.
- ⏭️ Ready for **Phase 7: SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)** on user approval.

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
- **“Quantro One | Business OS”** (horizontal, configurable, multi-industry)

This phase remains **single-tenant** (no auth yet) but is **designed for future multi-tenant support**.

#### 6.1 Global Rebranding (Quantro One | Business OS)
**Status: ✅ Completed**

**Scope (delivered)**
- Replace all instances of **“Realty OS” → “Business OS”**.
- Keep **“Quantro One”** as product name.
- Updated:
  - Sidebar/header labels
  - Dashboard headings
  - Page titles
  - Seeded copy made more industry-agnostic

**Terminology normalization (delivered)**
- “Agents” → **Team Members**
- “Clients” → **Contacts**
- “Property viewing” → **Meeting / Appointment**
- “Open house” → **Event**

**Exit criteria**
- ✅ No real-estate-only language remains in UI defaults.

#### 6.2 Business Profile (Core System Layer)
**Status: ✅ Completed**

**Goal (delivered)**
Configurable **Business Profile** layer (single-tenant for now; workspace-scoped later).

**Business Profile fields (delivered)**
- Industry (dropdown):
  - Real Estate, Healthcare, Consulting, E-commerce, Other
- Use case (free text)
- Entity naming overrides:
  - Contacts, Team Members, Meetings, Events, Services
- `simulation_mode` toggle (Simulation Layer)

**Behavior requirements (delivered)**
- UI labels adapt dynamically based on selected industry + naming overrides.
- AI prompts incorporate Business Profile context for:
  - intent classification
  - entity extraction
  - content generation

**Implementation notes (delivered)**
- MongoDB `business_profile` document.
- Backend endpoints:
  - `GET /api/business-profile`
  - `PUT /api/business-profile`

**Exit criteria**
- ✅ Changing Business Profile updates UI terminology and influences AI outputs.

#### 6.3 Settings Section (Operational Control Center)
**Status: ✅ Completed (production-grade + QA-validated)**

**Goal (delivered)**
Provide a SaaS-grade Settings section that functions as the **operational core** of the system.

**Settings tabs (delivered)**
1) 🔌 Integrations (production-grade, input-ready)
- Implemented as a true **control center** (not placeholder):
  - **AI & Intelligence**
    - OpenAI / LLM Provider: API key input (**masked + eye toggle**), model selector, connect/update/test/disconnect.
  - **Email & Calendar**
    - Gmail: OAuth-ready connect CTA (simulated), connected-account field.
    - Google Calendar: OAuth-ready connect CTA (simulated), calendar id field.
  - **CRM**
    - Provider selector (HubSpot / GoHighLevel / Pipedrive / Salesforce / Custom)
    - Masked API key + optional base URL
  - **Webhooks & Endpoints**
    - Copyable inbound endpoint URL + optional shared secret
    - Added **copy fallback** for hardened/headless contexts (execCommand + user-facing guidance)
- UX: grouped sections, status badges, timestamps, required-field validation.

2) ⚙️ Automation
- Shortcut to manage Automation Policies + quick overview.

3) 🧠 Business Profile
- Industry selector, use case, entity naming, simulation mode toggle + save.

4) 👥 Workspace
- Placeholder with workspace name; Phase 7 will add multi-tenant + team management.

**Critical bug fixed (P0)**
- Root cause: `seed_database()` gated on `inbox_col` emptiness → integrations not created on some instances → Integrations UI returned null for every card → blank panel.

**Fixes applied (delivered)**
- Backend (`server.py`):
  - Added `DEFAULT_INTEGRATIONS_CATALOG` and `ensure_integrations_seeded()`.
  - Runs every startup via `lifespan` and idempotently ensures providers exist:
    - `gmail`, `google_calendar`, `crm`, `openai`, `webhook`
  - Backfills missing `category`/`display_name` without overwriting valid config.
- Frontend:
  - Added `/app/frontend/src/components/IntegrationsPanel.js` with a **static manifest** so UI never blanks even if API returns empty.
  - `Settings.js` slimmed (678 → 349 lines).

**Exit criteria**
- ✅ Integrations never blank.
- ✅ Providers seed correctly on legacy instances.
- ✅ Connect/test/disconnect UX works.

#### 6.4 Data model: “Workspace-ready” scoping (single-tenant)
**Status: 🟡 Partially complete (deferred to Phase 7 hardening)**

**Goal**
While still single-tenant, ensure stored config is future workspace-scoped.

**What exists now**
- Integrations stored in MongoDB with provider/status/config + metadata.

**Next steps**
- Add `workspace_id` consistently to:
  - `integrations_config`
  - `business_profile`
  - relevant operational collections
- Default `workspace_id = "default"`.

**Exit criteria**
- No hard-coded global integration settings.
- All config stored in DB in a workspace-compatible structure.

#### 6.5 UX Guidelines (apply throughout Phase 6)
**Status: ✅ Completed (validated)**
- Dark mode, premium UI.
- Minimal layout, subtle motion.
- Clear status indicators.
- Settings communicates trust, safety, and control.

#### 6.6 Testing & verification (Phase 6)
**Status: ✅ Completed (Session 3C)**

**Backend Self-Healing QA (7/7 PASS)**
- Idempotency across 3 restarts (no duplicates; stable IDs)
- Legacy repopulation (missing providers restored)
- Partial corruption recovery (backfills metadata **without losing user status/config**)
- Collection-missing recovery (auto-creates all providers)
- Empty integrations + seeded inbox scenario covered
- Unknown-provider survival (extra provider does not break system)
- Final API returns all 5 providers

**Frontend + Cross-Module Regression QA (15/15 PASS)**
- Integrations renders 5 cards; no blank states
- OpenAI connect/test/disconnect + eye-toggle
- CRM provider selector options + required-field validation
- Webhook endpoint URL shown and copy button present
- Industry switch + terminology updates
- Dashboard/Smart Inbox/CRM/Schedule/Content Engine load; **zero JS console errors**

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)
**Status: 🟢 Ready to start (pending user approval)**

**Phase 7 configuration (confirmed earlier)**
- Auth provider: Google OAuth via Emergent Integration
- Roles: Owner / Admin / Manager / Operator / Agent
- Multi-workspace per user + invitation flow
- Audit logs: standard (user + system)
- Export: CSV + JSON

**Note**
Phase 7 begins only after Phase 6 stability — now achieved.

---

## 3. Next Actions

**Immediate (Phase 7 kickoff — P1):**
1. Confirm tenancy model + workspace scoping strategy (`workspace_id` everywhere).
2. Implement Google OAuth login and session handling.
3. Add workspace switching + invitation flow.
4. Enforce RBAC on key endpoints and UI controls.
5. Implement audit log collection + export (CSV/JSON).

**Secondary (P2 hardening / refactor):**
6. Continue refactors of monolith files:
   - `server.py`, `ContentEngine.js`, `Dashboard.js`, `SmartInbox.js`
7. Add webhook inbound handler (optional) to match displayed endpoint.

---

## 4. Success Criteria

**Achieved (Phases 1–5):**
- Workflow engine: Inbox → AI triage → policies → auto-run or manual control → mocked downstream actions → transparent execution trail.
- Premium dark UI across modules.
- Advanced escalation safety net.

**Phase 6 Success Criteria (Business OS Transformation): ✅ ACHIEVED**
- ✅ App fully rebranded to **Quantro One | Business OS**.
- ✅ Terminology industry-agnostic and configurable.
- ✅ Business Profile drives:
  - dynamic UI labels
  - AI context for classification + generation
- ✅ Settings provides a SaaS-grade control surface:
  - Integrations control center with real inputs (LLM keys, CRM keys, OAuth-ready connectors, webhooks)
  - Automation controls
  - Business Profile config
- ✅ Integrations seeding is idempotent and self-healing; Integrations UI never blanks.
- ✅ Session 3C QA complete with **GO** results.

**Phase 7 Success Criteria (SaaS Foundation):**
- Google OAuth login working end-to-end.
- Multi-workspace support with smooth switching.
- RBAC enforced across API + UI.
- Audit logs filterable + exportable (CSV + JSON) with user/system attribution.
