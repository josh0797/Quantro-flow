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
- ✅ Global rebrand + multi-industry UI adaptation already implemented across main pages (Dashboard, Smart Inbox, CRM, Schedule, Content Engine, Onboarding).
- ✅ Simulation Layer (backend) implemented and wired to Business Profile.
- ✅ **P0 Settings bug fixed**: Integrations tab no longer blank; now a production-grade control center.
- ✅ Backend integrations config is **self-healing** (auto-seeded on startup).
- 🟡 Next: **Session 3C — Testing & Polish** (frontend + backend regression, industry switch validation, terminology consistency, empty states).

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
**Status: 🟡 In Progress (major milestones completed)**

**Primary goal (Phase 6)**
Transform the product from:
- “Quantro One | Realty OS” (real-estate specific)
into:
- **“Quantro One | Business OS”** (horizontal, configurable, multi-industry)

This phase is **single-tenant** (no auth yet) but **designed for future multi-tenant support**.

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
**Status: ✅ Completed (Bug fixed + production-ready Integrations)**

**Goal (delivered)**
Add a SaaS-grade Settings section that functions as the **operational core** of the system.

**Settings tabs (delivered)**
1) 🔌 Integrations (production-grade, input-ready)
- Implemented as a **control center** (not placeholder):
  - **AI & Intelligence**
    - OpenAI / LLM Provider: API key input (masked + eye toggle), model selector, connect/update/test/disconnect.
  - **Email & Calendar**
    - Gmail: OAuth-ready connect CTA (simulated), connected-account field.
    - Google Calendar: OAuth-ready connect CTA (simulated), calendar id field.
  - **CRM**
    - Provider selector (HubSpot / GoHighLevel / Pipedrive / Salesforce / Custom)
    - Masked API key + optional base URL
  - **Webhooks & Endpoints**
    - Copyable inbound endpoint URL + optional shared secret
- UX: grouped sections, status badges, timestamps, required-field validation.

2) ⚙️ Automation
- Shortcut to manage Automation Policies + quick overview (regression-safe).

3) 🧠 Business Profile
- Industry selector, use case, entity naming, simulation mode toggle + save.

4) 👥 Workspace
- Placeholder with workspace name; Phase 7 will add multi-tenant + team mgmt.

**Critical bug fixed (P0)**
- Root cause: `seed_database()` only ran when `inbox_col` empty → `integrations_config_col` not populated → frontend cards returned `null` → Integrations looked blank.

**Fixes applied (delivered)**
- Backend (`server.py`):
  - Added `DEFAULT_INTEGRATIONS_CATALOG` and `ensure_integrations_seeded()`.
  - Runs every startup via `lifespan` and idempotently ensures providers exist:
    - `gmail`, `google_calendar`, `crm`, `openai`, `webhook`
  - Backfills missing `category`/`display_name` on legacy rows.
- Frontend:
  - Created `/app/frontend/src/components/IntegrationsPanel.js`
    - Static manifest → never blank even if backend is empty
    - Connect/update/test/disconnect flows
    - Masked secret inputs + copy-to-clipboard endpoints
  - Slimmed `/app/frontend/src/pages/Settings.js` (678 → 349 lines)

**Exit criteria**
- ✅ Settings appears in sidebar and all tabs function.
- ✅ Integrations tab is production-feeling and supports real inputs.

#### 6.4 Data model: “Workspace-ready” scoping (single-tenant)
**Status: 🟡 Partially complete**

**Goal**
Even while single-tenant, structure stored config as future workspace-scoped.

**What exists now**
- Integrations stored in MongoDB with provider/status/config metadata.

**Next steps**
- Add `workspace_id` consistently to:
  - `integrations_config`
  - `business_profile`
  - relevant operational collections (later)
- Default `workspace_id = "default"`.

**Exit criteria**
- No hard-coded global integration settings.
- All config stored in DB in a workspace-compatible structure.

#### 6.5 UX Guidelines (apply throughout Phase 6)
**Status: ✅ Ongoing**
- Dark mode, premium UI (Apple / Stripe / Linear style)
- Minimal layout, subtle motion
- Clear status indicators (connected/syncing/degraded)
- Settings must communicate safety, trust, and control

#### 6.6 Testing & verification (Phase 6)
**Status: 🟡 In Progress → next is Session 3C**

**Completed verification**
- ✅ Settings all tabs render.
- ✅ OpenAI connect flow works end-to-end; secrets masked.
- ✅ Business Profile PUT works; simulation toggle persists.

**Remaining verification (Session 3C)**
- Regression test across:
  - Smart Inbox (single + batch triage)
  - Auto-execution + execution trail
  - Advanced escalations
  - Content Engine generation
  - Schedule + CRM pages
- Industry switching + terminology consistency across all modules.
- Simulation Mode ON/OFF end-to-end validation.
- Empty states + loading states polish.

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)
**Status: ⏭️ Deferred (next phase after Phase 6 validation)**

**Phase 7 configuration (confirmed earlier)**
- Auth provider: Google OAuth via Emergent Integration
- Roles: Owner / Admin / Manager / Operator / Agent
- Multi-workspace per user + invitation flow
- Audit logs: standard (user + system)
- Export: CSV + JSON

**Note**
Phase 7 will be implemented after Phase 6 is validated and stable.

---

## 3. Next Actions

**Immediate (Session 3C — Testing & Polish, P1):**
1. Run comprehensive regression (frontend + backend) for:
   - Smart Inbox triage flows
   - Auto-execution  escalations
   - Schedule/CRM/Content Engine
2. Validate Business Profile switching across industries:
   - UI terminology
   - AI prompt context behavior
   - Simulation data pack correctness
3. Polish Settings UX details:
   - Microcopy for OAuth simulation (“Connect with Google”)
   - Confirm required-field validation copy is clear
   - Confirm webhook endpoint copy is intuitive
4. Decide testing approach:
   - Manual screenshot/interaction pass first
   - Then testing agent for automated regression if desired

**After Session 3C:**
5. Complete workspace-ready scoping (`workspace_id`) across configs.
6. Prepare Phase 7 kickoff (Auth + Multi-tenant) only when Phase 6 is green.

---

## 4. Success Criteria

**Achieved (Phases 1–5):**
- Workflow engine: Inbox → AI triage → policies → auto-run or manual control → mocked downstream actions → transparent execution trail.
- Premium dark UI across modules.
- Advanced escalation safety net.

**Phase 6 Success Criteria (Business OS Transformation):**
- ✅ App fully rebranded to **Quantro One | Business OS**.
- ✅ Terminology industry-agnostic and configurable.
- ✅ Business Profile drives:
  - dynamic UI labels
  - AI context for classification + generation
- ✅ Settings provides a SaaS-grade control surface:
  - Integrations control center with real inputs (LLM keys, CRM keys, OAuth-ready connectors, webhooks)
  - Automation controls
  - Business Profile config
- 🟡 Single-tenant now, but data model is progressing toward workspace-ready scoping.
- 🟡 Regression testing + polish complete (Session 3C).

**Phase 7 Success Criteria (SaaS Foundation):**
- Google OAuth login working end-to-end.
- Multi-workspace support with smooth switching.
- RBAC enforced across API + UI.
- Audit logs filterable + exportable (CSV + JSON) with user/system attribution.
