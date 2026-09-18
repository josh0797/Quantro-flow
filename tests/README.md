# Ad-hoc / legacy scripts

`test_core_ai.py` (Emergent LLM POC) was removed in Phase 0 Emergent exit.
Intent detection and content generation in the app go through
`backend/ai_billing.py` (OpenAI), not `emergentintegrations`.

Historical scripts in the repo root that still point at
`*.preview.emergentagent.com` are optional manual runners against old
preview hosts — they are not the pytest suite under `backend/tests/`.
