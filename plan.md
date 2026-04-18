# plan.md

## 1. Objectives
- Ship a premium dark-mode SaaS POC→V1 for **Quantro One | Realty OS** where core workflows feel automated and connected.
- Prove the **core AI workflow** end-to-end: **Smart Inbox item → GPT-4o intent detection → suggested action → (simulated) scheduling/CRM updates → activity feed**.
- Deliver multi-page UI (Dashboard, Inbox, Schedule, CRM, Onboarding, Content) with realistic **connected mock data** and “system is running” status cues.
- Ensure backend (FastAPI + MongoDB) cleanly models entities + event log so everything is traceable and testable.

## 2. Implementation Steps

### Phase 1 — Core AI POC (isolation; do not proceed until stable)
**User stories**
1. As an operator, I can send a sample email text to an endpoint and get back a structured intent result.
2. As an operator, I can see confidence + extracted entities (name, time, request type) in the response.
3. As an operator, I can run the same input repeatedly and get consistently parseable JSON.
4. As an operator, I can handle unknown/ambiguous messages with a safe “needs_review” intent.
5. As an operator, I can generate a social post + email draft and receive cleanly formatted outputs.

**Steps**
- Websearch: best practices for **OpenAI structured outputs / JSON schema** with GPT-4o; pick the most robust approach for deterministic JSON.
- Define the **core schemas** (Pydantic): `IntentResult`, `SuggestedAction`, `ContentDraft`.
- Create a minimal **Python test script** (no web app) that calls GPT-4o via Emergent key:
  - Test 5–10 representative inbox messages (booking, onboarding, follow-up, spam, ambiguous).
  - Validate JSON schema parsing + edge cases.
- Iterate prompts until:
  - JSON is always valid;
  - intent labels match expected set;
  - fallback behavior works.
- Freeze prompt + schema as `core_ai` module contract.

**Exit criteria**
- Script passes all samples with 0 schema failures and acceptable intent quality.

---

### Phase 2 — V1 App Development (build around proven core; no auth)
**User stories**
1. As a user, I can open the Dashboard and immediately see today’s schedule, key metrics, and what the system is doing.
2. As a user, I can review the Smart Inbox, open a message, and see AI-detected intent + recommended next action.
3. As a user, I can click “Approve” on an AI suggestion to create a calendar event (simulated) and log it in the activity feed.
4. As a user, I can view a contact in CRM and see the linked inbox thread + scheduled meetings + sync status.
5. As a user, I can add a new agent and track onboarding steps automatically created by the system.

**Backend (FastAPI + MongoDB)**
- Data model (Mongo collections):
  - `inbox_items` (simulated Gmail), `calendar_events` (simulated GCal), `contacts` (simulated GHL), `agents`, `onboarding_tasks`, `content_items`, `activity_events`.
- Seed script: generate **connected mock data** (threads ↔ contacts ↔ events ↔ activity log).
- Core endpoints (MVP):
  - Inbox: list/detail, run intent detection, approve/execute suggested action.
  - Schedule: list/create events, availability stub.
  - CRM: list/detail contacts, “sync status” simulation.
  - Onboarding: create agent, generate tasks, update progress.
  - Content: generate (GPT-4o) + store + list.
  - Activity feed: list recent system events (append-only log).
- “Automation engine” (simple service): when inbox action approved → create event/contact updates → emit activity events.

**Frontend (premium dark OS UI)**
- Layout: left rail nav + top bar + main content; subtle motion; status chips (“Running”, “Sync queued”).
- Pages:
  - **Dashboard**: metrics cards, today timeline, activity feed (live-poll), AI suggestions queue.
  - **Smart Inbox**: list + detail drawer; intent badge; approve/decline; audit trail.
  - **Schedule**: agenda view + upcoming; create event modal.
  - **CRM**: contacts table + profile panel; activity timeline.
  - **Onboarding**: agent list + progress; steps checklist.
  - **Content Engine**: prompt → drafts; library with tags.
- Real-time feel (MVP): polling refresh for activity feed + subtle toasts.

**Close Phase 2 with testing**
- One full end-to-end pass: inbox → AI intent → approve action → event/contact updated → dashboard activity reflects changes.
- Fix UX/state issues (loading/empty/error states) until stable.

---

### Phase 3 — Feature expansion + hardening
**User stories**
1. As a user, I can run “Auto-triage” to classify multiple inbox items in a batch.
2. As a user, I can edit AI-extracted details (time, contact) before approving an action.
3. As a user, I can filter CRM by lifecycle stage and see last-touch timestamps.
4. As a user, I can view an onboarding “playbook” and see system-completed vs human-required steps.
5. As a user, I can reuse content templates and generate variants for different channels.

**Steps**
- Add batch operations + manual override UI.
- Add stronger relationship linking (thread→contact matching rules).
- Improve activity feed semantics (types, icons, grouping) + “system health” panel.
- Expand content engine: templates, tone controls, versioning.
- Add more robust API validation + pagination + consistent error envelopes.

**Close Phase 3 with testing**
- End-to-end regression: triage batch, overrides, CRM linkage, onboarding flow, content generation/storage.

---

### Phase 4 — Optional (ask before implementing): Authentication + multi-tenant readiness
**User stories**
1. As an admin, I can invite users and assign roles (admin/operator/agent).
2. As a user, I can sign in and only see my team’s data.
3. As an admin, I can manage integration settings (mock connectors) per workspace.
4. As a user, I can export activity logs for auditing.
5. As an admin, I can configure automation rules (what can auto-run vs needs approval).

**Steps**
- Confirm auth requirement with user (auth reduces agent testability).
- Implement JWT auth + workspace scoping (MVP) if approved.

## 3. Next Actions
- Implement Phase 1: websearch → define schemas → write Python POC script → validate GPT-4o outputs.
- Lock prompt + JSON contract and create `core_ai` module.
- Scaffold backend + seed connected mock data.
- Build V1 UI pages + wire core flows.
- Run Phase 2 end-to-end test + fix until stable.

## 4. Success Criteria
- Core workflow works reliably: **Inbox message → intent JSON → approved action → calendar/contact updates → activity feed**.
- UI feels premium, calm, system-driven (dark mode, whitespace, subtle motion, clear hierarchy).
- Connected seeded data demonstrates realistic operations across all modules.
- No broken states: loading/empty/error handled; AI failures degrade gracefully to “needs review”.
- End-to-end tests completed at each phase with regressions fixed before moving on.