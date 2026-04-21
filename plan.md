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
- Prepare for future SaaS scaling (multi-tenant, auth, RBAC, audit export) **without shipping auth yet**.

**Current status (as of this update):**
- ✅ **Phases 1–5 complete** (Core app + workflow engine + policies/escalations + templates + auto-execution).
- ✅ Global rebrand + multi-industry UI adaptation implemented across all main pages.
- ✅ Simulation Layer (backend) implemented and wired to Business Profile.
- ✅ **Settings Operational Control Center** complete.
- ✅ Backend integrations config is **self-healing** (auto-seeded on startup; idempotent).
- ✅ **System Health surface layer shipped** (Settings banner + Dashboard card + repair toast + backend health endpoint/events).
- ✅ **Multilingual i18n system shipped (ES + EN)** with global Language Context, translation keys, persistence, and AI language enforcement.
- ✅ **Brand rename shipped:** **Quantro One → Quantro Flow**.
- ✅ **Simulation Mode UX shipped:** persistent toggle in Sidebar + Settings, localized, confirmation modal on Simulation→Live, localStorage mirroring.
- 🟡 **Phase 6.10 next:** Simulation/Live Data Wiring Hardening (strict dataset isolation + E2E verification).
- ⏭️ Phase 7 is next **but OAuth/auth should not start until explicit user approval**.

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

This phase remains **single-tenant** (no auth yet) but is **designed for future multi-tenant support**.

#### 6.1 Global Rebranding (Quantro Flow | Business OS)
**Status: ✅ Completed**

**Scope (delivered)**
- Replace legacy **“Realty OS” → “Business OS”**.
- Rename product brand: **“Quantro One” → “Quantro Flow”** (no reversion).
- Updated:
  - Frontend i18n brand keys and marketing taglines
  - Sidebar brand
  - Backend health service label + FastAPI app title
  - AI prompt persona copy
  - Seeded activity event copy

**Exit criteria**
- ✅ Product is consistently branded as **Quantro Flow | Business OS**.

#### 6.2 Business Profile (Core System Layer)
**Status: ✅ Completed**

**Goal (delivered)**
Configurable **Business Profile** layer (single-tenant for now; workspace-scoped later).

**Business Profile fields (delivered)**
- Industry (dropdown): Real Estate, Healthcare, Consulting, E-commerce, Other
- Use case (free text)
- Entity naming overrides: Contacts, Team Members, Meetings, Events, Services
- `simulation_mode` toggle (Simulation Layer)
- `language` (NEW): `"es" | "en"`

**Behavior requirements (delivered)**
- UI labels adapt dynamically based on selected industry + naming overrides.
- AI prompts incorporate Business Profile context for:
  - intent classification
  - entity extraction
  - content generation
- AI outputs enforce language based on Business Profile `language`.

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

**Settings layout (delivered)**
- **Top-of-page Simulation Mode banner** (see §6.6)
- Tabs:
  1) 🔌 Integrations (production-grade, input-ready)
  2) ⚙️ Automation
  3) 🧠 Business Profile
  4) 👥 Workspace (includes Language selector)

**Integrations tab (delivered)**
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
    - Clipboard copy fallback for hardened/headless contexts
- UX: grouped sections, status badges, timestamps, required-field validation.

**Critical bug fixed (P0)**
- Root cause: `seed_database()` gated on `inbox_col` emptiness → integrations not created on some instances → Integrations UI returned null for every card → blank panel.

**Fixes applied (delivered)**
- Backend (`server.py`):
  - Added `DEFAULT_INTEGRATIONS_CATALOG` and `ensure_integrations_seeded()`.
  - Runs every startup and idempotently ensures providers exist.
  - Backfills missing `category`/`display_name` without overwriting valid config.
- Frontend:
  - Added `/app/frontend/src/components/IntegrationsPanel.js` with static manifest so UI never blanks.

**Exit criteria**
- ✅ Integrations never blank.
- ✅ Providers seed correctly on legacy instances.
- ✅ Connect/test/disconnect UX works.

#### 6.4 System Health / Self-Healing Surface Layer (Trust Signal)
**Status: ✅ Completed (verified healthy + auto-repaired states)**

**Goal (delivered)**
Turn “micro-feedback invisible → visible” and convert self-healing into brand trust.

**Deliverables (delivered)**
1) Backend health surface (`system_health_events` + `/api/system/health`)
2) Settings → Integrations banner (`SystemStatusBanner`)
3) Dashboard integration (`SystemHealthCard`)
4) Optional toast (session-gated)

**Exit criteria**
- ✅ Healthy state visible in both Settings + Dashboard.
- ✅ Auto-repair state visible with repair detail.
- ✅ Toast fires only once per event.

#### 6.5 Multilingual System (i18n) — OS-level capability
**Status: ✅ Completed (ES + EN shipped, production-ready)**

**Goal (delivered)**
Lightweight, scalable i18n across core OS surfaces.

**Deliverables (delivered)**
- Single translations source: `/app/frontend/src/i18n/translations.js`
- Global language context + persistence
- UI migration across all major modules
- Decision/agent key pattern
- AI prompt language enforcement

#### 6.6 Simulation Layer UX (First-class product control)
**Status: ✅ Completed (UX shipped + visually verified)**

**Goal (delivered)**
Expose Simulation Mode as a first-class operating mode with safe switching.

**Deliverables (delivered)**
- `SimulationModeToggle` component (compact/banner/inline)
- Sidebar + Settings placements
- Badges + confirmation modal (Simulation → Live)
- Persistence:
  - localStorage mirror (`realtyos_mode`)
  - backend `business_profile.simulation_mode`
- Fully localized ES + EN

**Verification**
- ✅ Toggle visible in Sidebar and Settings.
- ✅ Badge + modal behavior verified.
- ✅ Backend persistence verified.

#### 6.7 Data model: “Workspace-ready” scoping (single-tenant)
**Status: 🟡 Partially complete (deferred to Phase 7 hardening)**

**Goal**
Keep DB layout compatible with future workspace scoping.

**Next steps**
- Add `workspace_id` consistently to:
  - `integrations_config`, `business_profile`, `system_health_events`
  - relevant operational collections
- Default `workspace_id = "default"`.

**Exit criteria**
- No hard-coded global integration settings.
- All config stored in workspace-compatible structure.

#### 6.8 UX Guidelines (apply throughout Phase 6)
**Status: ✅ Completed (validated)**
- Dark mode, premium UI.
- Minimal layout, subtle motion.
- Clear status indicators.
- Settings communicates trust, safety, and control.

#### 6.9 Testing & verification (Phase 6)
**Status: ✅ Completed**
- Backend Self-Healing QA
- Frontend cross-module regression QA
- System Health surfaces verified
- i18n verified
- Simulation Mode UX verified

#### 6.10 Simulation/Live Data Wiring Hardening (Strict Isolation)
**Status: 🟡 In Progress (P0 / critical trust requirement)**

**Problem**
- Simulation datasets exist (`is_simulation: True`), but core endpoints currently return mixed datasets.
- Legacy seeded demo data was inserted without `is_simulation` and therefore leaks into Live Mode.

**Goals**
1) **Mode isolation**
   - Simulation ON → *only* `is_simulation: True`
   - Simulation OFF → *only* `is_simulation != True`
2) **No leakage** across Dashboard, Smart Inbox, CRM, Schedule, Activity, AI suggestions.
3) **Writes respect current mode** (sandbox writes in Simulation; real writes in Live).
4) **Predictable, safe, trustworthy**: users always know what they’re seeing.

**Implementation plan**
1) **Backfill legacy seed data**
   - Add a startup migration that marks all legacy seeded records as `is_simulation: True` where missing.
   - Collections in scope:
     - `contacts`, `inbox_items`, `calendar_events`, `agents`, `activity_events`, `content_templates/content` (as applicable)
   - Non-destructive: only sets `is_simulation=True` when field is absent.

2) **Centralize mode filtering in backend**
   - Add `get_mode_filter()` helper reading `business_profile.simulation_mode` and returning:
     - simulation: `{ "is_simulation": True }`
     - live: `{ "is_simulation": {"$ne": True} }`
   - Apply the filter to all relevant reads:
     - `GET /api/inbox` (+ status filter)
     - `GET /api/inbox/{id}`
     - `GET /api/contacts` / `GET /api/contacts/{id}` (and related inbox/events/activity joins)
     - `GET /api/calendar`
     - `GET /api/activity`
     - `GET /api/agents`
     - `GET /api/content`
     - `GET /api/dashboard/metrics`
     - `GET /api/dashboard/suggestions`
     - any other list/detail endpoints that render operational data

3) **Tag writes with current mode**
   - For create/update endpoints that generate new operational records:
     - Calendar event creation
     - Contact creation
     - Content generation/creation
     - Any “approve/action” pipeline steps that insert downstream artifacts
   - Ensure new records include `is_simulation = current_mode`.

4) **Auto-seed simulation dataset when entering Simulation Mode**
   - If user turns Simulation ON and no simulation data exists:
     - generate simulation data for current industry.
   - Ensure this does not affect Live data.

5) **Frontend: enforce consistent mode refresh + empty states**
   - On toggle change, ensure all pages re-fetch data and render consistent results.
   - Live mode with no data should show clean guidance:
     - connect integrations
     - or create first records manually
   - No broken UI, no “half populated” cards.

**Exit criteria**
- ✅ Simulation ON shows only simulation data everywhere.
- ✅ Live OFF shows only real workspace data everywhere.
- ✅ Records created in Simulation remain isolated.
- ✅ Records created in Live remain visible only in Live.
- ✅ No mixing in Dashboard metrics/suggestions.
- ✅ Graceful empty states in Live mode with clear guidance.

**Testing plan (full E2E)**
- Backend:
  - Validate filters per endpoint in both modes.
  - Validate joins (e.g., contact detail includes only same-mode inbox/events/activity).
  - Validate write tagging.
- Frontend:
  - Toggle Simulation ↔ Live and verify all modules update coherently:
    - Dashboard, Smart Inbox, CRM, Schedule, Activity feed, AI suggestions.
  - Validate empty states in Live with no real records.

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)
**Status: 🟡 Deferred (do NOT start OAuth yet)**

**Phase 7 configuration (planned)**
- Auth provider: Google OAuth via Emergent Integration
- Roles: Owner / Admin / Manager / Operator / Agent
- Multi-workspace per user + invitation flow
- Audit logs: standard (user + system)
- Export: CSV + JSON

**Note**
Phase 7 begins only after explicit user approval.

---

## 3. Next Actions

**Immediate (P0):**
1) **Phase 6.10 — Simulation/Live Data Wiring Hardening**
   - Implement strict `is_simulation` separation across backend reads/writes.
   - Backfill legacy seeded records as simulation.
   - Ensure toggle flips all datasets coherently.
   - Add/verify empty states in Live mode.
   - Run full E2E verification.

**Near-term (pre-Phase 7 hardening — P1):**
2) Standardize decision objects to use `titleKey/summaryKey` everywhere as the decision system ships.
3) Ensure `system_health_events`, `integrations_config`, and `business_profile` become workspace-ready once tenant model is introduced.
4) Final microcopy polish for i18n completeness (remaining deep form placeholders and select labels) — continue using translation-key pattern.

**Phase 7 kickoff (P1 — only after approval):**
1) Confirm tenancy model + workspace scoping strategy (`workspace_id` everywhere).
2) Implement Google OAuth login and session handling.
3) Add workspace switching + invitation flow.
4) Enforce RBAC on key endpoints and UI controls.
5) Implement audit log collection + export (CSV + JSON).

**Secondary (P2 hardening / refactor):**
6) Continue refactors of monolith files:
   - `server.py`, `ContentEngine.js`, `Dashboard.js`, `SmartInbox.js`
7) Add webhook inbound handler (optional) to match displayed endpoint.

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

**Phase 6.10 Success Criteria (Data Layer Isolation):**
- Simulation Mode is a **true sandbox**: only `is_simulation: True` data is visible and writable.
- Live Mode is a **true workspace view**: only `is_simulation != True` data is visible and writable.
- Switching modes never deletes real data and never causes data leakage.
- Dashboard metrics + AI suggestions respect the current mode.
- Live empty state is intentional, clean, and guides the user to connect integrations or create first records.

**Phase 7 Success Criteria (SaaS Foundation):**
- Google OAuth login working end-to-end.
- Multi-workspace support with smooth switching.
- RBAC enforced across API + UI.
- Audit logs filterable + exportable (CSV + JSON) with user/system attribution.
