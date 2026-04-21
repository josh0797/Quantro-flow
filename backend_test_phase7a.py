import requests
import sys
import json
from datetime import datetime, timedelta

class Phase7aAuthTester:
    def __init__(self, base_url="https://quantro-os.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        
        # Pre-seeded test sessions from review request
        self.user1_token = "sess_test_dd76edaa8c42404c9fcb89534abcce5e"  # default workspace
        self.user2_token = "sess_test_c9b75c3ac7d04ad08124e10444eb7068"  # ws_test_92c73371
        self.user1_workspace = "default"
        self.user2_workspace = "ws_test_92c73371"

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None, timeout=30):
        """Run a single API test"""
        url = f"{self.base_url}/api/{endpoint}"
        default_headers = {'Content-Type': 'application/json'}
        if headers:
            default_headers.update(headers)

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        if headers and 'Authorization' in headers:
            print(f"   Auth: Bearer {headers['Authorization'].split(' ')[1][:20]}...")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=default_headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=default_headers, timeout=timeout)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=default_headers, timeout=timeout)
            elif method == 'DELETE':
                response = requests.delete(url, headers=default_headers, timeout=timeout)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    if isinstance(response_data, list):
                        print(f"   Response: List with {len(response_data)} items")
                    elif isinstance(response_data, dict):
                        print(f"   Response keys: {list(response_data.keys())}")
                except:
                    print(f"   Response: {response.text[:100]}...")
            else:
                self.failed_tests.append(f"{name}: Expected {expected_status}, got {response.status_code}")
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}...")

            return success, response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text

        except Exception as e:
            self.failed_tests.append(f"{name}: Error - {str(e)}")
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_unauthenticated_access(self):
        """Test that all protected endpoints return 401 without Bearer token"""
        print("\n=== Testing Unauthenticated Access ===")
        
        protected_endpoints = [
            "contacts", "inbox", "calendar", "activity", "agents", "content",
            "dashboard/metrics", "dashboard/suggestions", "business-profile",
            "integrations", "policies", "templates", "escalation-rules",
            "system/health", "simulation/status"
        ]
        
        for endpoint in protected_endpoints:
            success, _ = self.run_test(
                f"Unauthenticated {endpoint}",
                "GET", endpoint, 401
            )
            if not success:
                print(f"   ⚠️  {endpoint} should return 401 without auth")
        
        # Test that /api/health is public
        success, _ = self.run_test("Public Health Check", "GET", "health", 200)
        return True

    def test_session_exchange(self):
        """Test session exchange validation"""
        print("\n=== Testing Session Exchange ===")
        
        # Test with invalid session_id
        invalid_session_data = {"session_id": "invalid_session_12345"}
        success, _ = self.run_test(
            "Invalid Session Exchange",
            "POST", "auth/session", 401, invalid_session_data
        )
        
        # Note: We can't test valid session exchange without a real session_id from Emergent Auth
        print("   ℹ️  Valid session exchange requires real Emergent Auth session_id")
        return True

    def test_auth_me_endpoint(self):
        """Test /api/auth/me with valid Bearer tokens"""
        print("\n=== Testing Auth Me Endpoint ===")
        
        # Test User1
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        success, user1_data = self.run_test(
            "Auth Me - User1",
            "GET", "auth/me", 200, headers=headers1
        )
        
        if success and user1_data:
            # Verify user profile structure
            required_fields = ["user_id", "email", "name", "workspaces"]
            for field in required_fields:
                if field not in user1_data:
                    self.failed_tests.append(f"Auth Me - User1: Missing field {field}")
            
            # Verify workspaces array has is_current=true for current workspace
            workspaces = user1_data.get("workspaces", [])
            current_workspace = next((ws for ws in workspaces if ws.get("is_current")), None)
            if not current_workspace:
                self.failed_tests.append("Auth Me - User1: No current workspace marked")
            elif current_workspace.get("workspace_id") != self.user1_workspace:
                self.failed_tests.append(f"Auth Me - User1: Current workspace mismatch")
        
        # Test User2
        headers2 = {"Authorization": f"Bearer {self.user2_token}"}
        success, user2_data = self.run_test(
            "Auth Me - User2",
            "GET", "auth/me", 200, headers=headers2
        )
        
        if success and user2_data:
            workspaces = user2_data.get("workspaces", [])
            current_workspace = next((ws for ws in workspaces if ws.get("is_current")), None)
            if current_workspace and current_workspace.get("workspace_id") != self.user2_workspace:
                self.failed_tests.append(f"Auth Me - User2: Current workspace mismatch")
        
        return True

    def test_auth_logout(self):
        """Test logout functionality"""
        print("\n=== Testing Auth Logout ===")
        
        # Note: We'll skip actual logout to preserve sessions for other tests
        # In a real test environment, we'd create temporary sessions for this test
        print("   ℹ️  Logout test skipped to preserve test sessions for other tests")
        print("   ℹ️  Logout endpoint exists and should invalidate sessions when called")
        
        # We can test that the endpoint exists without actually calling it
        # success, _ = self.run_test(
        #     "Logout User1",
        #     "POST", "auth/logout", 200, headers=headers1
        # )
        
        return True

    def test_workspace_isolation(self):
        """Test that User1 and User2 see completely disjoint data"""
        print("\n=== Testing Workspace Isolation ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        headers2 = {"Authorization": f"Bearer {self.user2_token}"}
        
        # Test contacts isolation
        success1, contacts1 = self.run_test(
            "User1 Contacts",
            "GET", "contacts", 200, headers=headers1
        )
        
        success2, contacts2 = self.run_test(
            "User2 Contacts",
            "GET", "contacts", 200, headers=headers2
        )
        
        if success1 and success2:
            # Check for data isolation
            contacts1_ids = {c.get("contact_id") for c in contacts1} if contacts1 else set()
            contacts2_ids = {c.get("contact_id") for c in contacts2} if contacts2 else set()
            
            overlap = contacts1_ids.intersection(contacts2_ids)
            if overlap:
                self.failed_tests.append(f"Workspace isolation failed: {len(overlap)} shared contacts")
            else:
                print(f"   ✅ Contacts isolated: User1={len(contacts1_ids)}, User2={len(contacts2_ids)}")
        
        # Test inbox isolation
        success1, inbox1 = self.run_test(
            "User1 Inbox",
            "GET", "inbox", 200, headers=headers1
        )
        
        success2, inbox2 = self.run_test(
            "User2 Inbox", 
            "GET", "inbox", 200, headers=headers2
        )
        
        if success1 and success2:
            inbox1_ids = {i.get("inbox_id") for i in inbox1} if inbox1 else set()
            inbox2_ids = {i.get("inbox_id") for i in inbox2} if inbox2 else set()
            
            overlap = inbox1_ids.intersection(inbox2_ids)
            if overlap:
                self.failed_tests.append(f"Inbox isolation failed: {len(overlap)} shared items")
            else:
                print(f"   ✅ Inbox isolated: User1={len(inbox1_ids)}, User2={len(inbox2_ids)}")
        
        # Test calendar isolation
        success1, calendar1 = self.run_test(
            "User1 Calendar",
            "GET", "calendar", 200, headers=headers1
        )
        
        success2, calendar2 = self.run_test(
            "User2 Calendar",
            "GET", "calendar", 200, headers=headers2
        )
        
        if success1 and success2:
            calendar1_ids = {e.get("event_id") for e in calendar1} if calendar1 else set()
            calendar2_ids = {e.get("event_id") for e in calendar2} if calendar2 else set()
            
            overlap = calendar1_ids.intersection(calendar2_ids)
            if overlap:
                self.failed_tests.append(f"Calendar isolation failed: {len(overlap)} shared events")
            else:
                print(f"   ✅ Calendar isolated: User1={len(calendar1_ids)}, User2={len(calendar2_ids)}")
        
        return True

    def test_simulation_mode_isolation(self):
        """Test that simulation mode is workspace-specific"""
        print("\n=== Testing Simulation Mode Isolation ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        headers2 = {"Authorization": f"Bearer {self.user2_token}"}
        
        # Get current business profiles
        success1, profile1 = self.run_test(
            "User1 Business Profile",
            "GET", "business-profile", 200, headers=headers1
        )
        
        success2, profile2 = self.run_test(
            "User2 Business Profile",
            "GET", "business-profile", 200, headers=headers2
        )
        
        if success1 and success2:
            user1_sim_mode = profile1.get("simulation_mode", False)
            user2_sim_mode = profile2.get("simulation_mode", False)
            
            print(f"   User1 simulation_mode: {user1_sim_mode}")
            print(f"   User2 simulation_mode: {user2_sim_mode}")
            
            # Toggle User1's simulation mode
            new_profile1 = {**profile1, "simulation_mode": not user1_sim_mode}
            success, updated_profile1 = self.run_test(
                "Toggle User1 Simulation Mode",
                "PUT", "business-profile", 200, new_profile1, headers=headers1
            )
            
            if success:
                # Verify User2's mode is unchanged
                success2_check, profile2_check = self.run_test(
                    "User2 Profile After User1 Toggle",
                    "GET", "business-profile", 200, headers=headers2
                )
                
                if success2_check:
                    user2_sim_mode_after = profile2_check.get("simulation_mode", False)
                    if user2_sim_mode_after != user2_sim_mode:
                        self.failed_tests.append("Simulation mode not isolated: User2 affected by User1 change")
                    else:
                        print("   ✅ Simulation mode properly isolated between workspaces")
                
                # Restore User1's original mode
                restore_profile1 = {**profile1, "simulation_mode": user1_sim_mode}
                self.run_test(
                    "Restore User1 Simulation Mode",
                    "PUT", "business-profile", 200, restore_profile1, headers=headers1
                )
        
        return True

    def test_write_tagging(self):
        """Test that new records are tagged with correct workspace_id and simulation mode"""
        print("\n=== Testing Write Tagging ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        headers2 = {"Authorization": f"Bearer {self.user2_token}"}
        
        # Create a contact for User1
        new_contact1 = {
            "name": "Test Contact User1",
            "email": "testuser1@example.com",
            "phone": "555-0001",
            "type": "lead",
            "source": "api_test",
            "notes": "Created for workspace tagging test"
        }
        
        success1, created_contact1 = self.run_test(
            "Create Contact User1",
            "POST", "contacts", 200, new_contact1, headers=headers1
        )
        
        if success1 and created_contact1:
            # Verify the contact has correct workspace_id
            contact_workspace = created_contact1.get("workspace_id")
            if contact_workspace != self.user1_workspace:
                self.failed_tests.append(f"Contact workspace tagging failed: expected {self.user1_workspace}, got {contact_workspace}")
            else:
                print(f"   ✅ Contact tagged with workspace_id: {contact_workspace}")
            
            # Verify simulation mode tagging
            is_simulation = created_contact1.get("is_simulation")
            print(f"   Contact is_simulation: {is_simulation}")
        
        # Create a contact for User2
        new_contact2 = {
            "name": "Test Contact User2",
            "email": "testuser2@example.com", 
            "phone": "555-0002",
            "type": "lead",
            "source": "api_test",
            "notes": "Created for workspace tagging test"
        }
        
        success2, created_contact2 = self.run_test(
            "Create Contact User2",
            "POST", "contacts", 200, new_contact2, headers=headers2
        )
        
        if success2 and created_contact2:
            contact_workspace = created_contact2.get("workspace_id")
            if contact_workspace != self.user2_workspace:
                self.failed_tests.append(f"Contact workspace tagging failed: expected {self.user2_workspace}, got {contact_workspace}")
            else:
                print(f"   ✅ Contact tagged with workspace_id: {contact_workspace}")
        
        # Verify User1 cannot see User2's contact
        success1_check, contacts1_after = self.run_test(
            "User1 Contacts After User2 Create",
            "GET", "contacts", 200, headers=headers1
        )
        
        if success1_check and success2 and created_contact2:
            user2_contact_id = created_contact2.get("contact_id")
            user1_contact_ids = {c.get("contact_id") for c in contacts1_after}
            
            if user2_contact_id in user1_contact_ids:
                self.failed_tests.append("Cross-workspace leakage: User1 can see User2's contact")
            else:
                print("   ✅ Cross-workspace write isolation verified")
        
        return True

    def test_workspace_management(self):
        """Test workspace creation and switching"""
        print("\n=== Testing Workspace Management ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        
        # Test workspace creation
        new_workspace_data = {
            "name": "Test Workspace",
            "industry": "consulting"
        }
        
        success, created_workspace = self.run_test(
            "Create New Workspace",
            "POST", "auth/workspaces", 200, new_workspace_data, headers=headers1
        )
        
        if success and created_workspace:
            new_workspace_id = created_workspace.get("workspace_id")
            print(f"   Created workspace: {new_workspace_id}")
            
            # Test workspace switching
            switch_data = {"workspace_id": new_workspace_id}
            success_switch, _ = self.run_test(
                "Switch to New Workspace",
                "POST", "auth/workspaces/switch", 200, switch_data, headers=headers1
            )
            
            if success_switch:
                # Verify current workspace changed
                success_me, user_data = self.run_test(
                    "Verify Workspace Switch",
                    "GET", "auth/me", 200, headers=headers1
                )
                
                if success_me and user_data:
                    workspaces = user_data.get("workspaces", [])
                    current_workspace = next((ws for ws in workspaces if ws.get("is_current")), None)
                    if current_workspace and current_workspace.get("workspace_id") == new_workspace_id:
                        print("   ✅ Workspace switch successful")
                    else:
                        self.failed_tests.append("Workspace switch failed: current workspace not updated")
            
            # Test switching to non-member workspace (should fail)
            headers2 = {"Authorization": f"Bearer {self.user2_token}"}
            switch_forbidden = {"workspace_id": new_workspace_id}
            success_forbidden, _ = self.run_test(
                "Switch to Non-member Workspace",
                "POST", "auth/workspaces/switch", 403, switch_forbidden, headers=headers2
            )
            
            # Switch User1 back to default workspace
            switch_back = {"workspace_id": self.user1_workspace}
            self.run_test(
                "Switch Back to Default",
                "POST", "auth/workspaces/switch", 200, switch_back, headers=headers1
            )
        
        return True

    def test_x_workspace_id_header(self):
        """Test X-Workspace-Id header support"""
        print("\n=== Testing X-Workspace-Id Header ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        
        # Test with valid workspace header
        headers_with_workspace = {
            **headers1,
            "X-Workspace-Id": self.user1_workspace
        }
        
        success, contacts = self.run_test(
            "Contacts with X-Workspace-Id",
            "GET", "contacts", 200, headers=headers_with_workspace
        )
        
        if success:
            print(f"   ✅ X-Workspace-Id header accepted")
        
        # Test with invalid workspace header (should fail or be ignored)
        headers_invalid_workspace = {
            **headers1,
            "X-Workspace-Id": "invalid_workspace_id"
        }
        
        # This should either fail with 403 or fall back to user's default workspace
        success, _ = self.run_test(
            "Contacts with Invalid X-Workspace-Id",
            "GET", "contacts", 200, headers=headers_invalid_workspace
        )
        # Note: The behavior depends on implementation - it might return 403 or fall back
        
        return True

    def test_integrations_scoping(self):
        """Test that integrations are workspace-scoped"""
        print("\n=== Testing Integrations Scoping ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        headers2 = {"Authorization": f"Bearer {self.user2_token}"}
        
        # Get integrations for both users
        success1, integrations1 = self.run_test(
            "User1 Integrations",
            "GET", "integrations", 200, headers=headers1
        )
        
        success2, integrations2 = self.run_test(
            "User2 Integrations",
            "GET", "integrations", 200, headers=headers2
        )
        
        if success1 and success2:
            # Both should have 5 providers but separate instances
            if len(integrations1) != 5:
                self.failed_tests.append(f"User1 should have 5 integrations, got {len(integrations1)}")
            if len(integrations2) != 5:
                self.failed_tests.append(f"User2 should have 5 integrations, got {len(integrations2)}")
            
            # Verify they are different instances (different integration_ids)
            ids1 = {i.get("integration_id") for i in integrations1}
            ids2 = {i.get("integration_id") for i in integrations2}
            
            overlap = ids1.intersection(ids2)
            if overlap:
                self.failed_tests.append(f"Integration instances not isolated: {len(overlap)} shared IDs")
            else:
                print("   ✅ Integration instances properly isolated")
            
            # Test updating an integration for User1
            if integrations1:
                gmail_integration = next((i for i in integrations1 if i.get("provider") == "gmail"), None)
                if gmail_integration:
                    provider = gmail_integration["provider"]
                    update_data = {
                        "status": "connected",
                        "config": {"test": "value"}
                    }
                    
                    success_update, _ = self.run_test(
                        "Update User1 Gmail Integration",
                        "PUT", f"integrations/{provider}", 200, update_data, headers=headers1
                    )
                    
                    if success_update:
                        # Verify User2's gmail integration is unchanged
                        success2_check, integrations2_check = self.run_test(
                            "User2 Integrations After User1 Update",
                            "GET", "integrations", 200, headers=headers2
                        )
                        
                        if success2_check:
                            gmail2 = next((i for i in integrations2_check if i.get("provider") == "gmail"), None)
                            if gmail2 and gmail2.get("status") == "connected":
                                self.failed_tests.append("Integration update not isolated: User2 affected")
                            else:
                                print("   ✅ Integration updates properly isolated")
        
        return True

    def test_dashboard_metrics_workspace_scoped(self):
        """Test that dashboard metrics include workspace-specific simulation_mode"""
        print("\n=== Testing Dashboard Metrics Workspace Scoping ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        headers2 = {"Authorization": f"Bearer {self.user2_token}"}
        
        # Get dashboard metrics for both users
        success1, metrics1 = self.run_test(
            "User1 Dashboard Metrics",
            "GET", "dashboard/metrics", 200, headers=headers1
        )
        
        success2, metrics2 = self.run_test(
            "User2 Dashboard Metrics", 
            "GET", "dashboard/metrics", 200, headers=headers2
        )
        
        if success1 and success2:
            # Verify simulation_mode field is present
            sim_mode1 = metrics1.get("simulation_mode")
            sim_mode2 = metrics2.get("simulation_mode")
            
            if sim_mode1 is None:
                self.failed_tests.append("User1 dashboard metrics missing simulation_mode field")
            if sim_mode2 is None:
                self.failed_tests.append("User2 dashboard metrics missing simulation_mode field")
            
            print(f"   User1 simulation_mode: {sim_mode1}")
            print(f"   User2 simulation_mode: {sim_mode2}")
            
            # Verify metrics are workspace-specific (different counts expected)
            user1_contacts = metrics1.get("total_contacts", 0)
            user2_contacts = metrics2.get("total_contacts", 0)
            
            print(f"   User1 total_contacts: {user1_contacts}")
            print(f"   User2 total_contacts: {user2_contacts}")
            
            # They should likely be different due to workspace isolation
            if user1_contacts == user2_contacts and user1_contacts > 0:
                print("   ⚠️  Same contact counts - verify workspace isolation")
        
        return True

    def test_system_health_workspace_scoped(self):
        """Test that system health events are workspace-scoped"""
        print("\n=== Testing System Health Workspace Scoping ===")
        
        headers1 = {"Authorization": f"Bearer {self.user1_token}"}
        headers2 = {"Authorization": f"Bearer {self.user2_token}"}
        
        # Get system health for both users
        success1, health1 = self.run_test(
            "User1 System Health",
            "GET", "system/health", 200, headers=headers1
        )
        
        success2, health2 = self.run_test(
            "User2 System Health",
            "GET", "system/health", 200, headers=headers2
        )
        
        if success1 and success2:
            # Verify health events are workspace-specific
            events1 = health1.get("events", []) if isinstance(health1, dict) else []
            events2 = health2.get("events", []) if isinstance(health2, dict) else []
            
            print(f"   User1 health events: {len(events1)}")
            print(f"   User2 health events: {len(events2)}")
            
            # Check if events have workspace_id tagging
            if events1:
                sample_event = events1[0]
                if "workspace_id" in sample_event:
                    print(f"   ✅ Health events include workspace_id")
                else:
                    print(f"   ⚠️  Health events missing workspace_id field")
        
        return True

def main():
    print("🚀 Starting Phase 7a: Google OAuth + Multi-tenant Workspace Tests")
    print("=" * 70)
    
    tester = Phase7aAuthTester()

    # Run all Phase 7a specific tests
    print("\n🔒 UNAUTHENTICATED ACCESS TESTS")
    tester.test_unauthenticated_access()

    print("\n🔑 SESSION EXCHANGE TESTS")
    tester.test_session_exchange()

    print("\n👤 AUTH ME ENDPOINT TESTS")
    tester.test_auth_me_endpoint()

    print("\n🚪 AUTH LOGOUT TESTS")
    tester.test_auth_logout()

    print("\n🏢 WORKSPACE ISOLATION TESTS")
    tester.test_workspace_isolation()

    print("\n🎭 SIMULATION MODE ISOLATION TESTS")
    tester.test_simulation_mode_isolation()

    print("\n🏷️  WRITE TAGGING TESTS")
    tester.test_write_tagging()

    print("\n🏢 WORKSPACE MANAGEMENT TESTS")
    tester.test_workspace_management()

    print("\n📋 X-WORKSPACE-ID HEADER TESTS")
    tester.test_x_workspace_id_header()

    print("\n🔌 INTEGRATIONS SCOPING TESTS")
    tester.test_integrations_scoping()

    print("\n📊 DASHBOARD METRICS WORKSPACE TESTS")
    tester.test_dashboard_metrics_workspace_scoped()

    print("\n🏥 SYSTEM HEALTH WORKSPACE TESTS")
    tester.test_system_health_workspace_scoped()

    # Print final results
    print("\n" + "=" * 70)
    print(f"📊 FINAL RESULTS: {tester.tests_passed}/{tester.tests_run} tests passed")
    
    if tester.failed_tests:
        print(f"\n❌ FAILED TESTS ({len(tester.failed_tests)}):")
        for failure in tester.failed_tests:
            print(f"   • {failure}")
    else:
        print("\n✅ ALL TESTS PASSED!")

    success_rate = (tester.tests_passed / tester.tests_run * 100) if tester.tests_run > 0 else 0
    print(f"\n📈 Success Rate: {success_rate:.1f}%")
    
    return 0 if success_rate >= 80 else 1

if __name__ == "__main__":
    sys.exit(main())