# plan.md (Updated)

## 1. Objectives
- Deliver a premium **dark-first**, OS-like internal platform for real estate teams: **Quantro One | Realty OS**.
- Ship a connected, production-feeling workflow with automation **and** a critical control layer:
  **Smart Inbox item → GPT triage (single + batch) → policy evaluation → (auto-run OR manual override) → (simulated) Calendar/CRM updates → Activity feed / Audit trail**.
- Provide a multi-page, production-quality UI (Dashboard, Inbox, Schedule, CRM, Onboarding, Content Engine, Automation) with **connected seeded mock data** showing realistic operations.
- Evolve from a single-tenant MVP into a **production-ready B2B SaaS foundation** by adding:
  - **Authentication via Google OAuth (Emergent Integration)**
  - **Role-based access control (RBAC)** with 5 tiers: **Owner / Admin / Manager / Operator / Agent**
  - **Multi-workspace (multi-tenant) scoping** across all data collections
  - **Compliance-ready audit logs** with filters and export (CSV + JSON)

**Current status (as of this update):**
- ✅ **Phase 1, Phase 2, Phase 3, Phase 4 complete**.
- ✅ **Phase 5 complete** (Auto-execution pipeline + Advanced escalations + UI updates + verification).
- ✅ AI POC achieved **10/10** structured output tests.
- ✅ Full app functional with seeded workflows.
- ✅ Phase 5 testing (Iteration 4): Backend **100%**, Frontend **~95%**.
- 🟡 **Phase 6 starting** (Auth + RBAC + Multi-workspace + Audit logs).

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
  - Content generation (social post + email draft)
- POC test script created and executed:
  - `/app/tests/test_core_ai.py`
  - Result: **10/10 tests passed**

**Exit criteria met**
- Script passes samples with 0 schema failures and acceptable intent quality.

---

### Phase 2 — V1 App Development (build around proven core; no auth)
**Status: ✅ Completed**

**User stories (delivered)**
1. Dashboard shows key metrics, today’s schedule, and live system activity.
2. Smart Inbox provides message review + intent + recommended action.
3. Approving system suggestions triggers simulated automation (calendar/contact updates) and logs activity.
4. CRM contact profiles show linked inbox threads, meetings, and sync status.
5. Agent onboarding creates lifecycle steps and tracks progress.
6. Content Engine generates and stores social posts + email drafts.

**Backend (FastAPI + MongoDB) — delivered**
- MongoDB collections:
  - `inbox_items`, `calendar_events`, `contacts`, `agents`, `onboarding_tasks`, `content_items`, `activity_events`
- Seeded connected mock data demonstrating workflows across modules.
- Key endpoints delivered:
  - Dashboard: `/api/dashboard/metrics`, `/api/dashboard/suggestions`
  - Inbox: list/detail, `/analyze`, `/approve`, `/decline`
  - Calendar: list/create/delete (**create returns 201**)
  - CRM: list/detail + create contact
  - Agents + onboarding task update
  - Content: list + GPT-4o generation + delete
  - Activity feed: list recent system events
  - System status: `/api/system/status`
- Automation behavior:
  - Approving inbox action creates events/contacts/onboarding items and emits activity events.

**Frontend (React + shadcn/ui) — delivered**
- Dark-only, premium, minimal OS aesthetic.
- Left sidebar navigation with system status capsule.
- Real-time feel:
  - Polling for activity feed and dashboard updates
  - Subtle motion via **framer-motion**
- Pages delivered:
  - **Dashboard**: KPIs, Today schedule, suggestions queue, Live Activity feed
  - **Smart Inbox**: filtering, message detail, analysis, approve/decline
  - **Schedule**: grouped agenda + create event dialog
  - **CRM**: lifecycle filters, contacts table, profile panel with timeline
  - **Onboarding**: add agent, progress tracking, expandable checklist with task toggles
  - **Content Engine**: prompt → generate drafts, library filters, preview + copy

**Close Phase 2 with testing**
- Testing agent run produced **~96% overall pass rate**.

---

### Phase 3 — Workflow Engine Upgrade (Batch Triage + Manual Control Layer)
**Status: ✅ Completed**

**Primary goal (achieved)**
- Upgrade Smart Inbox from a single-item demo into a **scalable, controllable workflow engine**:
  - **Batch message processing** with real-time system activity signals
  - **Manual Override UI** enabling trust, governance, and precise execution

#### 3.1 Batch AI Triage (Inbox Intelligence at Scale)
**Status: ✅ Implemented**

**Delivered**
- `POST /api/inbox/batch-analyze` and `POST /api/inbox/batch-approve`
- Smart Inbox triage view with multi-select, batch buttons, statuses, and per-item classify.

#### 3.2 Manual Override UI (Critical Control Layer — “Review & Control”)
**Status: ✅ Implemented**

**Delivered**
- Review 6 control layout and override workflows
- Backend endpoints:
  - `PUT /api/inbox/{inbox_id}/details`
  - `POST /api/inbox/{inbox_id}/approve-with-overrides`

---

### Phase 4 — Workflow Governance + Communication Layer (Automation Policies + Templates)
**Status: ✅ Completed**

**Primary goal (achieved)**
- Governance for “when to run” + “who owns edge cases” + consistent communications.

**Delivered**
- Automation Policies (CRUD + evaluation)
- Escalation routing rules (CRUD + enable/disable)
- Content templates + AI generation from templates

---

### Phase 5 — Automation Engine Upgrade (Auto-Execution + Advanced Escalations)
**Status: ✅ Completed**

**Primary goal (achieved)**
- Unattended automation where safe (auto-run) and guarded escalation when risk/uncertainty exists.

**Delivered**
- Auto-execution pipeline:
  - `execute_action_for_item()` auto-creates mocked Calendar/CRM/Onboarding actions
  - Marks inbox items `status=auto_actioned` with `execution_results`
- Advanced escalation evaluation:
  - `calendar_conflict`, `incomplete_entities`, `urgency`, `contact_type` (+ existing `intent`, `keyword`)
- UI updates:
  - Smart Inbox shows auto-execution badge + execution trail
  - Escalation reasons shown when present
  - Automation rule editor supports advanced condition types

---

### Phase 6 — SaaS Foundation (Authentication + RBAC + Multi-Workspace + Audit Logs)
**Status: 🟡 In Progress (starting now)**

**Phase 6 Configuration (confirmed)**
- **Auth provider**: **Google OAuth via Emergent Integration**
- **Roles**: **Owner / Admin / Manager / Operator / Agent**
- **Workspace scoping**: **multiple workspaces per user** (workspace switching)
- **Onboarding flows**: create new workspace (first user becomes Owner) **and** join via invitation
- **Audit logs**: Standard (user actions + system actions)
- **Audit export**: **CSV + JSON**

#### 6.1 Data model additions (MongoDB)
**Goal**: Introduce multi-tenant primitives and stable identity.

**New collections**
- `users`
  - `{ user_id, email, name, avatar_url, google_sub, created_at, last_login_at }`
- `workspaces`
  - `{ workspace_id, name, slug, created_at, created_by_user_id, plan_tier, settings }`
- `workspace_members`
  - `{ workspace_id, user_id, role, status(active/invited), joined_at }`
- `workspace_invitations`
  - `{ invitation_id, workspace_id, email, role, token, expires_at, created_by_user_id, accepted_at }`
- `audit_events`
  - `{ audit_id, workspace_id, actor_type(user/system), actor_user_id?, action_type, module, entity_type?, entity_id?, metadata, ip?, user_agent?, created_at }`

**Schema changes (existing collections)**
- Add `workspace_id` to:
  - `inbox_items`, `calendar_events`, `contacts`, `agents`, `onboarding_tasks`, `content_items`, `activity_events`, `automation_policies`, `escalation_rules`, `content_templates`

**Exit criteria**
- All reads/writes are workspace-scoped; no cross-workspace leakage.

#### 6.2 Authentication (Google OAuth via Emergent)
**Backend**
- Implement OAuth endpoints:
  - `GET /api/auth/google/start`
  - `GET /api/auth/google/callback`
  - `POST /api/auth/logout`
  - `GET /api/auth/me`
- Session/token strategy:
  - Server issues a signed session (JWT or secure cookie) containing `user_id`.

**Frontend**
- Login screen with “Continue with Google”
- Route protection and authenticated app shell

**Exit criteria**
- User can sign in/out and session persists across refresh.

#### 6.3 Workspace selection + switching
**Backend**
- Workspace context strategy (required for most endpoints):
  - `X-Workspace-Id` header OR `?workspace_id=`
- Endpoints:
  - `POST /api/workspaces` (create; creator becomes Owner)
  - `GET /api/workspaces` (list workspaces for user)
  - `GET /api/workspaces/{workspace_id}`

**Frontend**
- Workspace switcher visible in top navigation (premium B2B SaaS style)
- Workspace creation modal + join-by-invite flow

**Exit criteria**
- User can switch between multiple workspaces; UI updates data accordingly.

#### 6.4 Role-based access control (RBAC)
**Role definitions (confirmed)**
- **Owner**: full workspace control, billing, policies, integrations, users
- **Admin**: full operational access, users, CRM, inbox, automations, content
- **Manager**: manage inbox, CRM, scheduling, onboarding, content, view reports
- **Operator**: inbox triage, manual override, approvals, scheduling, CRM updates
- **Agent**: view-only access to assigned records, meetings, activity

**Backend**
- Permission middleware / dependency:
  - Resolve user + workspace + role
  - Guard endpoints by module/action

**Frontend**
- UI gating:
  - Hide/disable restricted actions (e.g., policy edits, user invites)
  - Show role label in user menu

**Exit criteria**
- Unauthorized actions return 403; UI reflects permissions.

#### 6.5 Invitations + user management
**Backend**
- Endpoints:
  - `POST /api/workspaces/{workspace_id}/invites` (Owner/Admin)
  - `GET /api/workspaces/{workspace_id}/members`
  - `PUT /api/workspaces/{workspace_id}/members/{user_id}` (change role)
  - `DELETE /api/workspaces/{workspace_id}/members/{user_id}` (remove)
  - `POST /api/invites/accept` (token)

**Frontend**
- Workspace settings → Members table
- Invite user dialog (email + role)
- Accept invite screen

**Exit criteria**
- Users can be invited, accept, and join the workspace with the right role.

#### 6.6 Audit logs (filterable + exportable)
**Scope (confirmed: Standard)**
Include events for:
- login/logout
- approvals/rejections
- manual overrides
- automation executions
- policy-triggered actions
- CRM/contact updates
- scheduling actions

**Backend**
- Write audit events alongside existing `activity_events` (or unify later)
- Endpoints:
  - `GET /api/audit` with filters: `user_id`, `action_type`, `module`, `from`, `to`
  - `GET /api/audit/export?format=csv|json` (same filters)

**Frontend**
- New page: **Audit Log**
  - Filters: user, action type, module, date range
  - Table with clear “User vs System” attribution
  - Export button: CSV / JSON

**Exit criteria**
- Admin/Owner can filter and export audit events reliably.

#### 6.7 Testing & verification (Phase 6)
- Backend:
  - Auth flow happy path + failure path
  - Workspace scoping correctness
  - RBAC enforcement (matrix by role/module)
  - Audit events written for required actions
  - Export endpoints produce valid CSV + JSON
- Frontend:
  - Login/logout
  - Workspace switcher
  - Invite acceptance
  - Permission-based UI gating
  - Audit filters + export

---

## 3. Next Actions
**Immediate (Phase 6 P1):**
1. Implement Google OAuth via Emergent Integration and session handling.
2. Add workspace primitives + membership + invitation flows.
3. Add `workspace_id` to all documents and scope all API endpoints.
4. Implement RBAC enforcement across backend routes and frontend UI.
5. Add audit log storage, filtering, and export endpoints + UI.

---

## 4. Success Criteria

**Achieved (V1 + Phase 3 + Phase 4 + Phase 5):**
- Core workflow reliable:
  - **Inbox → intent (single + batch) → policy evaluation → auto-run or manual control → calendar/CRM/onboarding updates → activity feed**.
- Premium OS-like UI:
  - Dark-first, calm, minimal, system-driven.
- Connected seeded data demonstrates end-to-end workflows.
- AI failures degrade safely to `needs_review`.
- Auto-run executes with transparent execution trail.
- Advanced escalation conditions prevent unsafe automation and provide explicit reasons.

**Phase 6 Success Criteria (to be achieved):**
- Google OAuth login working end-to-end.
- Multi-workspace support with smooth switching in top navigation.
- 5-tier RBAC enforced consistently (API + UI) per permission model.
- Standard audit log covers user and system actions, filterable and exportable (CSV + JSON).
- No cross-workspace data access is possible; all queries are scoped.
