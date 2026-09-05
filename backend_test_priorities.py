"""
Backend API Tests for Priorities 2-5

Tests:
  Priority 2: Gmail/Calendar OAuth-only enforcement + webhook coming soon
  Priority 3: Simulation mode generate/clear endpoints
  Priority 4: Workspace automation seeding (7 policies, 5 rules, 5 templates)
  Priority 5: GET /api/usage returns 404
"""
import os
import sys
import time
import uuid
import requests
import jwt as pyjwt
from pymongo import MongoClient

# Load env
with open('/app/backend/.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            value = value.strip('"').strip("'")
            os.environ[key] = value

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://quantro-os.preview.emergentagent.com')
SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET', '')
MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'test_database')


def mint_token(email: str) -> str:
    """Mint a synthetic Supabase-compatible JWT"""
    user_id = str(uuid.uuid4())
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": now,
        "exp": now + 3600,
        "user_metadata": {"full_name": email.split("@")[0]},
    }
    return pyjwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")


class PriorityTester:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures = []

    def log(self, msg, level="INFO"):
        print(f"[{level}] {msg}")

    def check(self, name, condition, detail=""):
        self.tests_run += 1
        if condition:
            self.tests_passed += 1
            self.log(f"PASS - {name}", "PASS")
        else:
            self.tests_failed += 1
            self.log(f"FAIL - {name} :: {detail}", "FAIL")
            self.failures.append({"test": name, "detail": detail})

    def req(self, token, method, path, **kwargs):
        url = f"{BASE_URL}/{path}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Content-Type", "application/json")
        return requests.request(method, url, headers=headers, timeout=15, **kwargs)

    def run(self):
        # Create a test user and provision workspace
        token = mint_token(f"priority_test_{uuid.uuid4().hex[:8]}@quantro-test.com")
        me_res = self.req(token, "GET", "api/auth/me")
        self.check("Test user provisioned", me_res.status_code == 200, me_res.text[:200])
        if me_res.status_code != 200:
            return self.summary()
        
        workspace_id = me_res.json().get("current_workspace_id")
        self.log(f"Test workspace: {workspace_id}")

        # ── Priority 2: OAuth-only enforcement ──
        self.log("\n=== PRIORITY 2: Gmail/Calendar OAuth-only enforcement ===")
        
        # Try to manually connect gmail (should fail with 400)
        gmail_connect = self.req(token, "PUT", "api/integrations/gmail", json={
            "status": "connected",
            "config": {"api_key": "fake_key"}
        })
        self.check(
            "Gmail manual connect blocked (expect 400)",
            gmail_connect.status_code == 400,
            f"got {gmail_connect.status_code}: {gmail_connect.text[:200]}"
        )

        # Try to manually connect google_calendar (should fail with 400)
        gcal_connect = self.req(token, "PUT", "api/integrations/google_calendar", json={
            "status": "connected",
            "config": {"api_key": "fake_key"}
        })
        self.check(
            "Google Calendar manual connect blocked (expect 400)",
            gcal_connect.status_code == 400,
            f"got {gcal_connect.status_code}: {gcal_connect.text[:200]}"
        )

        # Disconnect should work (200)
        gmail_disconnect = self.req(token, "PUT", "api/integrations/gmail", json={
            "status": "disconnected",
            "config": {}
        })
        self.check(
            "Gmail disconnect allowed (expect 200)",
            gmail_disconnect.status_code == 200,
            f"got {gmail_disconnect.status_code}: {gmail_disconnect.text[:200]}"
        )

        # CRM (non-OAuth) should still work
        crm_connect = self.req(token, "PUT", "api/integrations/crm", json={
            "status": "connected",
            "config": {"provider": "hubspot", "api_key": "test_key"}
        })
        self.check(
            "CRM manual connect allowed (expect 200)",
            crm_connect.status_code == 200,
            f"got {crm_connect.status_code}: {crm_connect.text[:200]}"
        )

        # ── Priority 3: Simulation Mode ──
        self.log("\n=== PRIORITY 3: Simulation Mode generate/clear ===")
        
        # Enable simulation mode
        enable_sim = self.req(token, "PUT", "api/business-profile", json={
            "industry": "other",
            "use_case": "",
            "entity_labels": {
                "contacts": "Contacts",
                "team_members": "Team Members",
                "meetings": "Meetings",
                "events": "Events",
                "services": "Services"
            },
            "simulation_mode": True,
            "language": "es"
        })
        self.check(
            "Enable simulation mode (expect 200)",
            enable_sim.status_code == 200,
            f"got {enable_sim.status_code}: {enable_sim.text[:200]}"
        )

        # Generate simulation data
        gen_sim = self.req(token, "POST", "api/simulation/generate")
        self.check(
            "Generate simulation data (expect 200)",
            gen_sim.status_code == 200,
            f"got {gen_sim.status_code}: {gen_sim.text[:200]}"
        )

        # Check that simulation data was created
        mongo = MongoClient(MONGO_URL)
        db = mongo[DB_NAME]
        sim_contacts = db.contacts.count_documents({"is_simulation": True, "workspace_id": workspace_id})
        self.check(
            "Simulation contacts created",
            sim_contacts > 0,
            f"found {sim_contacts} simulation contacts"
        )

        # Clear simulation data
        clear_sim = self.req(token, "POST", "api/simulation/clear")
        self.check(
            "Clear simulation data (expect 200)",
            clear_sim.status_code == 200,
            f"got {clear_sim.status_code}: {clear_sim.text[:200]}"
        )

        # Verify simulation data was cleared
        sim_contacts_after = db.contacts.count_documents({"is_simulation": True, "workspace_id": workspace_id})
        self.check(
            "Simulation contacts cleared",
            sim_contacts_after == 0,
            f"found {sim_contacts_after} simulation contacts after clear"
        )

        # ── Priority 4: Workspace automation seeding ──
        self.log("\n=== PRIORITY 4: Workspace automation seeding ===")
        
        # Count automation policies
        policies_res = self.req(token, "GET", "api/policies")
        self.check("GET /api/policies works", policies_res.status_code == 200)
        if policies_res.status_code == 200:
            policies = policies_res.json()
            self.check(
                "Workspace has 7 automation policies",
                len(policies) == 7,
                f"found {len(policies)} policies"
            )
            # Check idempotency: no duplicate intents
            intents = [p.get("intent") for p in policies]
            unique_intents = set(intents)
            self.check(
                "No duplicate policy intents (idempotent)",
                len(intents) == len(unique_intents),
                f"intents: {intents}"
            )

        # Count escalation rules
        rules_res = self.req(token, "GET", "api/escalation-rules")
        self.check("GET /api/escalation-rules works", rules_res.status_code == 200)
        if rules_res.status_code == 200:
            rules = rules_res.json()
            self.check(
                "Workspace has 5 escalation rules",
                len(rules) == 5,
                f"found {len(rules)} rules"
            )
            # Check idempotency: no duplicate names
            names = [r.get("name") for r in rules]
            unique_names = set(names)
            self.check(
                "No duplicate rule names (idempotent)",
                len(names) == len(unique_names),
                f"names: {names}"
            )

        # Count content templates
        templates_res = self.req(token, "GET", "api/templates")
        self.check("GET /api/templates works", templates_res.status_code == 200)
        if templates_res.status_code == 200:
            templates = templates_res.json()
            self.check(
                "Workspace has 5 content templates",
                len(templates) == 5,
                f"found {len(templates)} templates"
            )
            # Check idempotency: no duplicate names
            names = [t.get("name") for t in templates]
            unique_names = set(names)
            self.check(
                "No duplicate template names (idempotent)",
                len(names) == len(unique_names),
                f"names: {names}"
            )

        # ── Priority 5: GET /api/usage removed ──
        self.log("\n=== PRIORITY 5: GET /api/usage removed ===")
        
        usage_res = self.req(token, "GET", "api/usage")
        self.check(
            "GET /api/usage returns 404 (dead endpoint)",
            usage_res.status_code == 404,
            f"got {usage_res.status_code}: {usage_res.text[:200]}"
        )

        mongo.close()
        return self.summary()

    def summary(self):
        self.log("=" * 70)
        self.log(f"TOTAL: {self.tests_run}  PASSED: {self.tests_passed}  FAILED: {self.tests_failed}")
        if self.failures:
            self.log("FAILURES:")
            for f in self.failures:
                self.log(f"  - {f['test']}: {f['detail']}")
        return 0 if self.tests_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(PriorityTester().run())
