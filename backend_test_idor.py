"""
IDOR / Cross-Workspace Isolation Tests (Priority 1 security fix)

Verifies that a user in Workspace B can NEVER read, update, or delete a
resource that belongs to Workspace A, specifically:

  - PUT  /api/onboarding/{task_id}   (bug fixed: now filters by workspace_id)
  - DELETE /api/content/{content_id} (bug fixed: now filters by workspace_id)

Plus spot-checks on endpoints that were already correctly scoped:
  - DELETE /api/calendar/{event_id}
  - GET    /api/contacts/{contact_id}

Auth strategy: mints two synthetic Supabase-compatible HS256 JWTs signed
with the project's SUPABASE_JWT_SECRET (same verification path the backend
uses in `_verify_supabase_jwt`). Each synthetic user has never logged in
before, so the backend auto-provisions a brand-new personal workspace for
each of them on first `/api/auth/me` call — giving us two fully isolated
workspaces (A and B) without needing real Supabase signup/email confirmation.
"""
import os
import sys
import time
import uuid
import json
import requests
import jwt as pyjwt

with open('/app/backend/.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            value = value.strip('"').strip("'")
            os.environ[key] = value

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://quantro-os.preview.emergentagent.com')
SUPABASE_JWT_SECRET = os.environ.get('SUPABASE_JWT_SECRET', '')


def mint_token(email: str) -> str:
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


class IDORTester:
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
        token_a = mint_token(f"idor_a_{uuid.uuid4().hex[:8]}@quantro-test.com")
        token_b = mint_token(f"idor_b_{uuid.uuid4().hex[:8]}@quantro-test.com")

        # Provision workspaces for both synthetic users
        me_a = self.req(token_a, "GET", "api/auth/me")
        me_b = self.req(token_b, "GET", "api/auth/me")
        self.check("User A provisioned", me_a.status_code == 200, me_a.text[:200])
        self.check("User B provisioned", me_b.status_code == 200, me_b.text[:200])
        if me_a.status_code != 200 or me_b.status_code != 200:
            return self.summary()

        ws_a = me_a.json().get("current_workspace_id")
        ws_b = me_b.json().get("current_workspace_id")
        self.check("Workspaces are different", ws_a != ws_b, f"A={ws_a} B={ws_b}")

        # ── Test 1: Onboarding task IDOR (the fixed bug) ──
        agent_res = self.req(token_a, "POST", "api/agents", json={
            "name": "IDOR Test Agent", "email": "idor.agent@test.com", "phone": "555-0000", "role": "agent"
        })
        self.check("Create agent as A", agent_res.status_code == 200, agent_res.text[:200])
        task_id = None
        if agent_res.status_code == 200:
            tasks = agent_res.json().get("onboarding_tasks", [])
            self.check("Agent has onboarding tasks", len(tasks) > 0)
            if tasks:
                task_id = tasks[0]["task_id"]

        if task_id:
            cross_update = self.req(token_b, "PUT", f"api/onboarding/{task_id}", json={"status": "completed"})
            self.check(
                "B cannot update A's onboarding task (expect 404)",
                cross_update.status_code == 404,
                f"got {cross_update.status_code}: {cross_update.text[:200]}"
            )

            same_update = self.req(token_a, "PUT", f"api/onboarding/{task_id}", json={"status": "completed"})
            self.check("A CAN update own onboarding task", same_update.status_code == 200, same_update.text[:200])

        # ── Test 2: Content deletion IDOR (the fixed bug) ──
        # Content items are normally created via AI generation; insert directly
        # via Mongo to avoid depending on the AI provider for this security test.
        from pymongo import MongoClient
        mongo = MongoClient(os.environ.get('MONGO_URL', 'mongodb://localhost:27017'))
        db = mongo[os.environ.get('DB_NAME', 'test_database')]
        content_id = str(uuid.uuid4())
        db.content_items.insert_one({
            "content_id": content_id, "type": "social_post", "title": "IDOR test content",
            "content": {"text": "test"}, "status": "draft", "created_at": "2025-01-01T00:00:00",
            "created_by": "test", "workspace_id": ws_a,
        })

        cross_delete = self.req(token_b, "DELETE", f"api/content/{content_id}")
        self.check(
            "B cannot delete A's content (expect 404)",
            cross_delete.status_code == 404,
            f"got {cross_delete.status_code}: {cross_delete.text[:200]}"
        )
        still_exists = db.content_items.find_one({"content_id": content_id})
        self.check("A's content still exists after B's attempt", still_exists is not None)

        same_delete = self.req(token_a, "DELETE", f"api/content/{content_id}")
        self.check("A CAN delete own content", same_delete.status_code == 200, same_delete.text[:200])
        mongo.close()

        # ── Spot-check 3: Calendar event IDOR (already scoped, must stay correct) ──
        ev_res = self.req(token_a, "POST", "api/calendar", json={
            "title": "IDOR test event", "description": "", "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T11:00:00", "location": "", "attendees": [], "contact_id": None
        })
        self.check("Create calendar event as A", ev_res.status_code == 201, ev_res.text[:200])
        if ev_res.status_code == 201:
            event_id = ev_res.json()["event_id"]
            cross_del_ev = self.req(token_b, "DELETE", f"api/calendar/{event_id}")
            self.check(
                "B cannot delete A's calendar event (expect 404)",
                cross_del_ev.status_code == 404,
                f"got {cross_del_ev.status_code}"
            )

        # ── Spot-check 4: Contact IDOR (already scoped, must stay correct) ──
        contact_res = self.req(token_a, "POST", "api/contacts", json={
            "name": "IDOR Test Contact", "email": "idor.contact@test.com", "phone": "555-1111",
            "type": "lead", "source": "test", "notes": ""
        })
        self.check("Create contact as A", contact_res.status_code == 200, contact_res.text[:200])
        if contact_res.status_code == 200:
            contact_id = contact_res.json()["contact_id"]
            cross_get_contact = self.req(token_b, "GET", f"api/contacts/{contact_id}")
            self.check(
                "B cannot read A's contact (expect 404)",
                cross_get_contact.status_code == 404,
                f"got {cross_get_contact.status_code}"
            )

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
    sys.exit(IDORTester().run())
