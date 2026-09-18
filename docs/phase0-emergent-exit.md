# Phase 0 — Emergent exit

Scope of this PR (no Actions, no Mongo→Postgres):

1. Drop `emergentintegrations` from `backend/requirements.txt` (private/broken pin; unused at runtime).
2. Remove `tests/test_core_ai.py` POC (`LlmChat` / `EMERGENT_LLM_KEY`). App LLM path remains `backend/ai_billing.py` (OpenAI).
3. Remove `@emergentbase/visual-edits` from frontend `devDependencies` and the `craco` wrap.

Out of scope (later cleanup):

- Ad-hoc root scripts and `auth_testing.md` that still mention `*.preview.emergentagent.com` / `emergent.host` as historical preview URLs.
- Comments in `ai_billing.py` / `server.py` that mention `EMERGENT_LLM_KEY` as a forbidden/direct path (kept as negative guidance).
- Mongo → Supabase cutover (Phases 1–6).
