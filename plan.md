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
  - Live Mode: uses exclusively user integrations + real workspace data.
  - Mode switching is instant, safe, and **never destroys real data**.
- Prepare for future SaaS scaling (multi-tenant, auth, RBAC, audit export) **without shipping auth yet**.

**Current status (as of this update):**
- ✅ **Phases 1–5 complete** (Core app + workflow engine + policies/escalations + templates + auto-execution).
- ✅ Global rebrand + multi-industry UI adaptation implemented across all main pages.
- ✅ Simulation Layer (backend) implemented and wired to Business Profile.
- ✅ **Settings Operational Control Center** complete.
- ✅ Backend integrations config is **self-healing** (auto-seeded on startup; idempotent).
- ✅ **Session 3C — Testing & Polish completed successfully** (backend self-healing QA + frontend cross-module regression).
- ✅ **System Health surface layer shipped** (Settings banner + Dashboard card + repair toast + backend health endpoint/events).
- ✅ **Multilingual i18n system shipped (ES + EN)** with global Language Context, translation keys, persistence, and AI language enforcement.
- ✅ **Incremental i18n migration Round 2 COMPLETE** (deep-copy migration across remaining modules).
- ✅ **Brand rename shipped:** **Quantro One → Quantro Flow** (horizontal multi-industry positioning preserved).
- ✅ **Simulation Mode UX shipped:** persistent toggle in Sidebar + Settings, localized, confirmation modal on Simulation→Live, localStorage mirroring.
- 🟢 **Phase 6 complete and production-ready**.
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
- Rename product brand: **“Quantro One” → “Quantro Flow”** (no reversion to Realty OS).
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
- **Top-of-page Simulation Mode banner** (NEW; see §6.6)
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
    - Added **copy fallback** for hardened/headless contexts (execCommand + user-facing guidance)
- UX: grouped sections, status badges, timestamps, required-field validation.

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

#### 6.4 System Health / Self-Healing Surface Layer (Trust Signal)
**Status: ✅ Completed (verified healthy + auto-repaired states)**

**Goal (delivered)**
Turn “micro-feedback invisible → visible” and convert self-healing into brand trust:
- “Quantro Flow detects and fixes issues before you notice them.”

**Deliverables (delivered)**
1) **Backend health surface**
- New Mongo collection: `system_health_events`
  - Records every startup integrity check for integrations
  - Stores `status` (healthy/repaired), `repair_count`, and `repairs[]` details
  - Keeps only the latest 50 events (bounded growth)
- New endpoint: `GET /api/system/health`
  - Returns overall status: `healthy` / `repaired` / `degraded`
  - Returns check list:
    - ✓ Integrations stable
    - ✓ Data consistency verified
    - ✓ No issues detected
  - Returns latest check + recent repairs

2) **Settings → Integrations banner**
- `SystemStatusBanner` at the top of Integrations panel:
  - Healthy / Auto‑Repaired / Degraded visuals
  - 3 check cards + optional repair breakdown
  - Tagline displayed
  - **Localized via i18n**

3) **Dashboard integration**
- `SystemHealthCard` (compact view):
  - Shows 3 checks and state
  - Clickable + “Details →” to Settings
  - **Localized via i18n**

4) **Optional toast (session-gated)**
- When a startup repair occurred:
  - Toast (localized): “System repaired missing integrations automatically”
  - Fires once per browser session per `event_id` (sessionStorage-gated)

**Exit criteria**
- ✅ Healthy state visible in both Settings + Dashboard.
- ✅ Auto-repair state visible with repair detail.
- ✅ Toast fires only once per event.

#### 6.5 Multilingual System (i18n) — OS-level capability
**Status: ✅ Completed (ES + EN shipped, production-ready)**

**Goal (delivered)**
Implement a scalable, lightweight i18n system that covers:
- UI copy across core surfaces
- Dashboard labels
- Self-healing system messaging
- Decision system (keys, no stored translated strings)
- AI output language enforcement

**Deliverables (delivered)**
1) **Single source of truth**
- `/app/frontend/src/i18n/translations.js`
  - `translations = { es: {...}, en: {...} }`
  - Hierarchical keys (e.g., `settings.tabs.integrations`, `system_health.tagline`)
  - Supports `{{variable}}` interpolation
  - Includes scaffolding for `login`, `decisions`, `agents`

2) **Global language context**
- `/app/frontend/src/context/LanguageContext.js`
  - `lang`, `setLang(lang)`, `t(key, vars?)`
  - Key resolution: active lang → EN fallback → return key
  - Persistence:
    - localStorage: `quantro_lang`
    - backend Business Profile: `business_profile.language`
  - Hydration order:
    1. backend business profile
    2. localStorage
    3. default `es`

3) **Language switcher component**
- `/app/frontend/src/components/LanguageSwitcher.js`
  - Shadcn Select
  - Compact + full variants

4) **App integration**
- `App.js` wrapped with `<LanguageProvider>` (provider wraps Sidebar + all pages).

5) **UI migration — Round 1 + Round 2**
- All major modules migrated to `t()` (core + deep copy across remaining modules).

6) **Agents + Decisions (pattern)**
- `translations.js` includes:
  - `decisions.revenue.raise_prices.{title,summary,impact,action_label}`
  - `agents.{pricing,retention,triage}.{label,description}`
- Requirement met: decisions store `titleKey/summaryKey`, rendered via `t(key, variables)`.

7) **AI language enforcement**
- Backend AI prompts inject `_lang_directive()`:
  - “Respond in Spanish/English...”
- Applied to:
  - intent prompt
  - content prompt
  - template prompt

#### 6.6 Simulation Layer UX (First-class product control)
**Status: ✅ Completed (UX shipped + visually verified)**

**Goal (delivered)**
Expose the Simulation Layer as a first-class operating mode:
- **Simulation ON:** user experiences a fully operational OS using realistic sample data.
- **Live:** app uses real integrations + workspace data.
- Switching is safe and never deletes real data.

**Deliverables (delivered)**
1) **Simulation Mode toggle component**
- New component: `/app/frontend/src/components/SimulationModeToggle.js`
- Variants: `compact` (Sidebar), `banner` (Settings top), `inline` (utility)

2) **Persistent placement**
- Sidebar: bottom section, **above “System Running / Synced”**
- Settings: **top of page, first section before tabs**

3) **Behavior requirements**
- Badges:
  - ON: amber pill **● SIMULATION**
  - OFF: green pill **● LIVE**
- Persistence:
  - localStorage mirror: `realtyos_mode = "simulation" | "live"`
  - Backend sync: `business_profile.simulation_mode`
- Confirmation modal:
  - Only when switching **Simulation → Live**
  - Copy: “You’re switching to Live Mode. Your real integrations and workspace data will be used. Sample data will be hidden.”
  - Buttons: **Go Live** (primary/cyan) + **Stay in Simulation** (secondary)
- UX: subtle, elegant amber accent (no heavy warning border flood).
- Duplicate Simulation toggle removed from Business Profile form to avoid conflicting controls.
- Fully localized ES + EN.

**Verification**
- ✅ Toggle visible in Sidebar.
- ✅ Toggle visible in Settings.
- ✅ Badge updates correctly.
- ✅ Confirmation appears only on Simulation→Live.
- ✅ LocalStorage and backend profile sync validated.

#### 6.7 Data model: “Workspace-ready” scoping (single-tenant)
**Status: 🟡 Partially complete (deferred to Phase 7 hardening)**

**Goal**
While still single-tenant, ensure stored config is future workspace-scoped.

**What exists now**
- Integrations stored in MongoDB with provider/status/config + metadata.
- Business profile stores industry, naming, simulation, and language.
- System health events stored without workspace scoping.

**Next steps**
- Add `workspace_id` consistently to:
  - `integrations_config`
  - `business_profile`
  - `system_health_events`
  - relevant operational collections
- Default `workspace_id = "default"`.

**Exit criteria**
- No hard-coded global integration settings.
- All config stored in DB in a workspace-compatible structure.

#### 6.8 UX Guidelines (apply throughout Phase 6)
**Status: ✅ Completed (validated)**
- Dark mode, premium UI.
- Minimal layout, subtle motion.
- Clear status indicators.
- Settings communicates trust, safety, and control.

#### 6.9 Testing & verification (Phase 6)
**Status: ✅ Completed**
- Backend Self-Healing QA (7/7 PASS)
- Frontend cross-module regression QA (15/15 PASS)
- System Health surfaces verified (healthy + repaired)
- i18n verified (Round 1 + Round 2)
- Simulation Mode UX verified (EN + ES, both placements)

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

**Immediate (pre-Phase 7 hardening — P1):**
1) Ensure Simulation Mode reliably flips all pages to the correct dataset sources (no mixing):
   - ON: show simulation datasets
   - OFF: show real integration datasets
   - Keep transitions instant and non-destructive.
2) Standardize decision objects to use `titleKey/summaryKey` everywhere as the decision system ships.
3) Ensure `system_health_events`, `integrations_config`, and `business_profile` become workspace-ready once tenant model is introduced.
4) Final microcopy polish for i18n completeness (remaining deep form placeholders and select labels) — continue using the same translation-key pattern.

**Phase 7 kickoff (P1 — only after approval):**
1) Confirm tenancy model + workspace scoping strategy (`workspace_id` everywhere).
2) Implement Google OAuth login and session handling.
3) Add workspace switching + invitation flow.
4) Enforce RBAC on key endpoints and UI controls.
5) Implement audit log collection + export (CSV/JSON).

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
- ✅ Settings provides a SaaS-grade control surface:
  - Integrations control center with real inputs (LLM keys, CRM keys, OAuth-ready connectors, webhooks)
  - Automation controls
  - Business Profile config
  - Language selector (ES/EN)
- ✅ Integrations seeding is idempotent and self-healing; Integrations UI never blanks.
- ✅ Self-healing is now **user-visible** as a trust signal (Settings banner + Dashboard card + repair toast).
- ✅ i18n shipped with:
  - single source translations
  - global LanguageContext
  - persistence to backend + localStorage
  - EN fallback + key fallback
  - AI prompt language injection
  - deep-copy coverage across all modules (Round 2 complete)
- ✅ **Simulation Mode UX shipped** as a first-class product control:
  - persistent toggle in Sidebar + Settings
  - localized badges (SIMULATION/LIVE)
  - confirmation on Simulation→Live
  - localStorage mirroring (`realtyos_mode`)
  - backend sync (`business_profile.simulation_mode`)
  - visually verified
- ✅ Session 3C QA complete with **GO** results.

**Phase 7 Success Criteria (SaaS Foundation):**
- Google OAuth login working end-to-end.
- Multi-workspace support with smooth switching.
- RBAC enforced across API + UI.
- Audit logs filterable + exportable (CSV + JSON) with user/system attribution.
