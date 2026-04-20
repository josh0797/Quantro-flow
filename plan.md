# plan.md (Updated)

## 1. Objectives
- Deliver a premium **dark-first**, OS-like internal platform: **Quantro One | Business OS**.
- Ship a connected, production-feeling workflow engine:
  **Smart Inbox → AI triage (single + batch) → automation policy evaluation → (auto-run OR review & control) → (simulated) Calendar/CRM updates → activity + execution trail**.
- Evolve the product from a vertical-specific real estate tool into a **multi-industry Business Operating System** that can adapt to different industries through configuration (not rewrites).
- Keep integrations **mocked/simulated** (Gmail, Google Calendar, CRM) but make them feel safe, enterprise, and workspace-ready.
- Prepare for future SaaS scaling (multi-tenant, auth, RBAC, audit export) **without shipping auth yet**.

**Current status (as of this update):**
- ✅ **Phase 1–5 complete** (Core app + workflow engine + policies/escalations + templates + auto-execution).
- ✅ Phase 5 testing (Iteration 4): **Backend 100%**, **Frontend ~95%**.
- 🟡 New strategic pivot: **Business OS Transformation first** (rebrand + configurability + settings) → **then** Phase 6 (Auth + multi-tenant + audit).

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
**Status: 🟡 In Progress (starting now)**

**Primary goal (Phase 6)**
Transform the product from:
- “Quantro One | Realty OS” (real-estate specific)
into:
- **“Quantro One | Business OS”** (horizontal, configurable, multi-industry)

This phase is **single-tenant** (no auth yet) but **designed for future multi-tenant support**.

#### 6.1 Global Rebranding (Quantro One | Business OS)
**Status: ⏳ Planned**

**Scope**
- Replace all instances of **“Realty OS” → “Business OS”**.
- Keep **“Quantro One”** as product name.
- Update:
  - Sidebar/header labels
  - Dashboard headings
  - Page titles
  - Metadata/title tags
  - Any seeded copy that is real-estate specific

**Terminology normalization (industry-agnostic)**
- “Agents” → **Team Members**
- “Clients” → **Contacts**
- “Property viewing” → **Meeting / Appointment**
- “Open house” → **Event**

**Exit criteria**
- No real-estate-only language remains in UI defaults.

#### 6.2 Business Profile (Core System Layer)
**Status: ⏳ Planned**

**Goal**
Introduce a configurable **Business Profile** layer (initially global/single-tenant) that will later become **per workspace**.

**Business Profile fields**
- Industry (dropdown):
  - Real Estate
  - Healthcare
  - Consulting
  - E-commerce
  - Other
- Use case (free text or presets)
- Entity naming (customizable labels):
  - Contacts (default)
  - Team Members (default)
  - Services / Products / Assets (optional)

**Behavior requirements**
- UI labels adapt dynamically based on selected industry + naming overrides.
- AI prompts incorporate Business Profile context for:
  - intent classification
  - entity extraction
  - content generation
- CRM and Inbox terminology adjusts automatically.

**Implementation notes**
- Add a `business_profile` document in MongoDB (single-tenant now), structured as:
  - `{ profile_id, industry, use_case, entity_labels, created_at, updated_at }`
- Create backend endpoints:
  - `GET /api/business-profile`
  - `PUT /api/business-profile`

**Exit criteria**
- Changing Business Profile updates UI terminology and influences AI outputs.

#### 6.3 Settings Section (Critical for SaaS)
**Status: ⏳ Planned**

**Goal**
Add **Settings** to sidebar with a premium B2B SaaS experience.

**Settings tabs**
1) 🔌 Integrations
- Gmail
  - Connect via Google OAuth (simulated for now)
  - Status: Connected / Not connected
  - Last sync
- Google Calendar
  - Select calendar
  - Set timezone
  - Define availability rules
- CRM (GoHighLevel or custom)
  - API Key input
  - Base URL input
  - “Test Connection” button
  - Status indicator

2) ⚙️ Automation
- Expose system behavior controls:
  - Auto-run vs approval per intent
  - Confidence thresholds (High / Medium / Low)
  - Escalation rules

3) 🧠 Business Profile
- Industry selector
- Use case configuration
- Custom entity naming

4) 👥 Workspace (placeholder for now)
- Workspace name
- Team members (static placeholder until Phase 7)
- Roles and permissions (read-only placeholder until Phase 7)

**Implementation notes**
- Store integration settings in MongoDB under a structure that will become workspace-scoped later, e.g.:
  - `{ integration_id, provider, status, last_sync_at, config, created_at, updated_at }`

**Exit criteria**
- Settings appears in sidebar and all tabs function (CRUD for config, simulated connection/testing states).

#### 6.4 Data model: “Workspace-ready” scoping (single-tenant)
**Status: ⏳ Planned**

**Goal**
Even though the app remains single-tenant, structure stored settings/data as if they belong to a workspace.

**Approach**
- Add `workspace_id` fields in schemas *optionally* (default to `"default"` for now) OR encapsulate under a single “default workspace” record.
- Ensure integrations/config are not global constants.

**Exit criteria**
- No hard-coded global integration settings.
- All config is stored in DB and can later be separated per workspace without breaking changes.

#### 6.5 UX Guidelines (apply throughout Phase 6)
**Status: ✅ Ongoing**
- Keep dark mode, premium UI (Apple / Stripe / Linear style)
- Minimal layout, subtle motion
- System status indicators for integrations:
  - connected, syncing, active, degraded
- Integrations must feel easy and safe to connect

#### 6.6 Testing & verification (Phase 6)
**Status: ⏳ Planned**
- Verify rebranding consistency across UI.
- Verify Business Profile updates:
  - changes labels immediately
  - updates AI prompt context
- Verify Settings:
  - Integration status changes persist
  - “Test Connection” UX works (mock)
  - Automation controls still work (regression)

---

### Phase 7 — SaaS Foundation (Auth + Multi-tenant + RBAC + Audit Logs)
**Status: ⏭️ Deferred (next phase after Business OS Transformation)**

**Phase 7 configuration (already confirmed earlier)**
- Auth provider: Google OAuth via Emergent Integration
- Roles: Owner / Admin / Manager / Operator / Agent
- Multi-workspace per user + invitation flow
- Audit logs: standard (user + system)
- Export: CSV + JSON

**Note**
Phase 7 will be implemented after Phase 6 is validated.

---

## 3. Next Actions
**Immediate (Business OS Transformation P0/P1):**
1. Global rebrand to **Quantro One | Business OS** + industry-agnostic terminology.
2. Implement **Business Profile** backend + UI and wire into AI prompts.
3. Add **Settings** section with Integrations + Automation + Business Profile tabs.
4. Make integration/config storage **workspace-ready** (single-tenant default).
5. Run testing agent and ship a demo-ready multi-industry Business OS.

---

## 4. Success Criteria

**Achieved (Phases 1–5):**
- Workflow engine: Inbox → AI triage → policies → auto-run or manual control → mocked downstream actions → transparent execution trail.
- Premium dark UI across modules.
- Advanced escalation safety net.

**Phase 6 Success Criteria (Business OS Transformation):**
- App is fully rebranded to **Quantro One | Business OS**.
- All core terminology is industry-agnostic and configurable.
- **Business Profile** drives:
  - dynamic UI labels
  - AI context for classification + generation
- **Settings** provides a SaaS-grade control surface:
  - Integrations (mock connect/status/test)
  - Automation controls
  - Business Profile config
- Single-tenant now, but no hard-coded global settings; data is stored in a future workspace-compatible structure.

**Phase 7 Success Criteria (SaaS Foundation):**
- Google OAuth login working end-to-end.
- Multi-workspace support with smooth switching.
- RBAC enforced across API + UI.
- Audit logs filterable + exportable (CSV + JSON) with user/system attribution.
