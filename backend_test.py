import requests
import sys
import json
from datetime import datetime, timedelta

class QuantroOSAPITester:
    def __init__(self, base_url="https://quantro-os.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.access_token = None
        self.user_info = None

    def run_test(self, name, method, endpoint, expected_status, data=None, timeout=30, require_auth=False):
        """Run a single API test"""
        url = f"{self.base_url}/api/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        # Add authentication header if available and required
        if require_auth and self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'
        elif require_auth and not self.access_token:
            self.failed_tests.append(f"{name}: Authentication required but no access token available")
            print(f"❌ Failed - {name}: Authentication required but no access token available")
            return False, {}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        if require_auth:
            print(f"   Auth: {'✓ Bearer token' if self.access_token else '✗ No token'}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=timeout)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers, timeout=timeout)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=timeout)

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

    def test_supabase_auth(self):
        """Test Supabase authentication with test credentials"""
        print("🔐 Testing Supabase Authentication...")
        
        # Test credentials from the review request
        test_credentials = [
            {"email": "josias.martin@hotmail.com", "password": "testpass123"},
            {"email": "josias.martin90@hotmail.com", "password": "testpass123"}
        ]
        
        # Try to authenticate with Supabase directly
        supabase_url = "https://ukootpnechabpmwsmxsi.supabase.co"
        auth_url = f"{supabase_url}/auth/v1/token?grant_type=password"
        
        for creds in test_credentials:
            print(f"\n   Trying to authenticate: {creds['email']}")
            try:
                auth_response = requests.post(auth_url, json={
                    "email": creds["email"],
                    "password": creds["password"]
                }, headers={
                    "apikey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVrb290cG5lY2hhYnBtd3NteHNpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMwOTk2NDcsImV4cCI6MjA4ODY3NTY0N30.xAB8F7stKKJC5dIY6-dPkuwbE-IhhtYkmti7TB0NLfI",
                    "Content-Type": "application/json"
                }, timeout=10)
                
                if auth_response.status_code == 200:
                    auth_data = auth_response.json()
                    if "access_token" in auth_data:
                        self.access_token = auth_data["access_token"]
                        self.user_info = auth_data.get("user", {})
                        print(f"   ✅ Authentication successful for {creds['email']}")
                        print(f"   User ID: {self.user_info.get('id', 'N/A')}")
                        return True
                    else:
                        print(f"   ❌ No access token in response: {auth_data}")
                else:
                    print(f"   ❌ Auth failed with status {auth_response.status_code}: {auth_response.text[:200]}")
                    
            except Exception as e:
                print(f"   ❌ Auth error: {str(e)}")
                continue
        
        print("   ❌ Could not authenticate with any test credentials")
        return False

    def test_auth_me_endpoint(self):
        """Test /api/auth/me endpoint with authentication"""
        if not self.access_token:
            print("   ⚠️ Skipping auth/me test - no access token available")
            return False
            
        return self.run_test("Auth Me Endpoint", "GET", "auth/me", 200, require_auth=True)

    def test_ai_billing_endpoints(self):
        """Test AI billing system endpoints"""
        print("🤖 Testing AI Billing System...")
        
        if not self.access_token:
            print("   ⚠️ Skipping AI billing tests - authentication required")
            return False
        
        # First get inbox items to test with
        success, inbox_data = self.run_test("Get Inbox for AI Testing", "GET", "inbox", 200, require_auth=True)
        if not success or not inbox_data:
            print("   ❌ Cannot test AI endpoints - no inbox data available")
            return False
        
        # Test 1: Single inbox analyze (should use gpt-4o-mini via run_ai_request)
        if len(inbox_data) > 0:
            inbox_id = inbox_data[0].get('inbox_id')
            if inbox_id:
                print(f"   Testing AI analysis on inbox item: {inbox_id}")
                success, analyze_result = self.run_test(
                    "AI Inbox Analyze (via run_ai_request)", 
                    "POST", 
                    f"inbox/{inbox_id}/analyze", 
                    200,  # Expecting success with valid auth
                    timeout=25,
                    require_auth=True
                )
                
                if success and analyze_result:
                    # Check if AI intent was populated (indicates AI processing worked)
                    ai_intent = analyze_result.get('ai_intent')
                    if ai_intent:
                        print(f"   ✅ AI analysis successful - intent: {ai_intent.get('intent', 'N/A')}")
                        print(f"   Model used should be gpt-4o-mini (forced by Quantro credits)")
                    else:
                        print(f"   ⚠️ AI analysis completed but no ai_intent populated")
        
        # Test 2: Batch analyze (should handle 402 errors properly)
        if len(inbox_data) >= 2:
            batch_ids = [item['inbox_id'] for item in inbox_data[:2]]
            print(f"   Testing batch AI analysis on {len(batch_ids)} items")
            success, batch_result = self.run_test(
                "AI Batch Analyze (via run_ai_request)",
                "POST",
                "inbox/batch-analyze",
                200,  # Expecting success with valid auth
                data={"inbox_ids": batch_ids},
                timeout=35,
                require_auth=True
            )
            
            if success and batch_result:
                results = batch_result.get('results', [])
                print(f"   ✅ Batch analysis successful - processed {len(results)} items")
        
        # Test 3: Content generation (should use run_ai_request)
        print("   Testing AI content generation")
        content_prompt = {
            "prompt": "New luxury listing: 4-bedroom modern home with pool and smart features",
            "type": "both"
        }
        success, content_result = self.run_test(
            "AI Content Generate (via run_ai_request)",
            "POST",
            "content/generate",
            200,
            data=content_prompt,
            timeout=25,
            require_auth=True
        )
        
        if success and content_result:
            items = content_result.get('items', [])
            print(f"   ✅ Content generation successful - created {len(items)} items")
        
        # Test 4: Template generation (if templates exist)
        success, templates_data = self.run_test("Get Templates for AI Testing", "GET", "templates", 200, require_auth=True)
        if success and templates_data and len(templates_data) > 0:
            template_id = templates_data[0].get('template_id')
            if template_id:
                print(f"   Testing AI template generation with template: {template_id}")
                generation_data = {
                    "context": {
                        "contact_name": "John Doe",
                        "subject": "Property Inquiry",
                        "situation": "your interest in downtown properties"
                    }
                }
                success, template_result = self.run_test(
                    "AI Template Generate (via run_ai_request)",
                    "POST",
                    f"templates/{template_id}/generate",
                    200,
                    data=generation_data,
                    timeout=25,
                    require_auth=True
                )
                
                if success and template_result:
                    print(f"   ✅ Template generation successful")
        
        return True

    def test_ai_endpoints_without_auth(self):
        """Test that AI endpoints require authentication (should return 401)"""
        print("🔒 Testing AI endpoints without authentication...")
        
        # Temporarily clear access token
        original_token = self.access_token
        self.access_token = None
        
        # Test endpoints that should require auth
        test_cases = [
            ("inbox/123/analyze", "POST", {}),
            ("inbox/batch-analyze", "POST", {"inbox_ids": ["123"]}),
            ("content/generate", "POST", {"prompt": "test", "type": "both"}),
        ]
        
        for endpoint, method, data in test_cases:
            success, response = self.run_test(
                f"Unauthorized {method} {endpoint}",
                method,
                endpoint,
                401,  # Expecting 401 Unauthorized
                data=data if data else None,
                timeout=10
            )
        
        # Restore access token
        self.access_token = original_token
        return True

    def test_health_check(self):
        """Test health endpoint"""
        return self.run_test("Health Check", "GET", "health", 200)

    def test_dashboard_metrics(self):
        """Test dashboard metrics"""
        return self.run_test("Dashboard Metrics", "GET", "dashboard/metrics", 200)

    def test_dashboard_suggestions(self):
        """Test AI suggestions"""
        return self.run_test("AI Suggestions", "GET", "dashboard/suggestions", 200)

    def test_inbox_operations(self):
        """Test inbox operations"""
        # Get all inbox items
        success, inbox_data = self.run_test("Get Inbox", "GET", "inbox", 200)
        if not success or not inbox_data:
            return False

        # Test filtering
        self.run_test("Get New Inbox", "GET", "inbox?status=new", 200)
        self.run_test("Get Processed Inbox", "GET", "inbox?status=processed", 200)

        # Get specific inbox item
        if inbox_data and len(inbox_data) > 0:
            inbox_id = inbox_data[0].get('inbox_id')
            if inbox_id:
                self.run_test("Get Inbox Item", "GET", f"inbox/{inbox_id}", 200)
                
                # Test AI analysis (may take longer)
                print("   Testing AI analysis (may take 10-15 seconds)...")
                self.run_test("AI Analysis", "POST", f"inbox/{inbox_id}/analyze", 200, timeout=20)
                
                # Test approve/decline actions
                self.run_test("Approve Action", "POST", f"inbox/{inbox_id}/approve", 200)
                # Note: We won't test decline as it would conflict with approve

        return True

    def test_calendar_operations(self):
        """Test calendar operations"""
        # Get events
        success, events_data = self.run_test("Get Calendar Events", "GET", "calendar", 200)
        
        # Create new event
        new_event = {
            "title": "Test Meeting",
            "description": "API Test Event",
            "start_time": (datetime.utcnow() + timedelta(days=1)).isoformat(),
            "end_time": (datetime.utcnow() + timedelta(days=1, hours=1)).isoformat(),
            "location": "Test Location",
            "attendees": ["Test User"]
        }
        success, created_event = self.run_test("Create Calendar Event", "POST", "calendar", 201, new_event)
        
        # Delete the created event
        if success and created_event and 'event_id' in created_event:
            event_id = created_event['event_id']
            self.run_test("Delete Calendar Event", "DELETE", f"calendar/{event_id}", 200)

        return True

    def test_contacts_operations(self):
        """Test contacts/CRM operations"""
        # Get all contacts
        success, contacts_data = self.run_test("Get Contacts", "GET", "contacts", 200)
        
        # Test filtering
        self.run_test("Get Active Contacts", "GET", "contacts?lifecycle_stage=active", 200)
        self.run_test("Get New Contacts", "GET", "contacts?lifecycle_stage=new", 200)

        # Get specific contact
        if contacts_data and len(contacts_data) > 0:
            contact_id = contacts_data[0].get('contact_id')
            if contact_id:
                self.run_test("Get Contact Detail", "GET", f"contacts/{contact_id}", 200)

        # Create new contact
        new_contact = {
            "name": "Test Contact",
            "email": "test@example.com",
            "phone": "555-0123",
            "type": "lead",
            "source": "api_test",
            "notes": "Created via API test"
        }
        self.run_test("Create Contact", "POST", "contacts", 200, new_contact)

        return True

    def test_agents_operations(self):
        """Test agents operations"""
        # Get all agents
        success, agents_data = self.run_test("Get Agents", "GET", "agents", 200)
        
        # Create new agent
        new_agent = {
            "name": "Test Agent",
            "email": "testagent@example.com",
            "phone": "555-0456",
            "role": "agent"
        }
        success, created_agent = self.run_test("Create Agent", "POST", "agents", 200, new_agent)
        
        # Test onboarding task update if we have tasks
        if success and created_agent and 'onboarding_tasks' in created_agent:
            tasks = created_agent['onboarding_tasks']
            if tasks and len(tasks) > 0:
                task_id = tasks[0]['task_id']
                self.run_test("Update Onboarding Task", "PUT", f"onboarding/{task_id}", 200, {"status": "completed"})

        return True

    def test_content_operations(self):
        """Test content engine operations"""
        # Get all content
        success, content_data = self.run_test("Get Content", "GET", "content", 200)
        
        # Test filtering
        self.run_test("Get Social Posts", "GET", "content?content_type=social_post", 200)
        self.run_test("Get Email Drafts", "GET", "content?content_type=email_draft", 200)

        # Generate new content (AI operation - may take longer)
        print("   Testing AI content generation (may take 10-15 seconds)...")
        content_prompt = {
            "prompt": "New luxury listing: 4-bedroom modern home with pool and smart features",
            "type": "both"
        }
        success, generated_content = self.run_test("Generate Content", "POST", "content/generate", 200, content_prompt, timeout=20)
        
        # Delete generated content if successful
        if success and generated_content and 'items' in generated_content:
            for item in generated_content['items']:
                if 'content_id' in item:
                    content_id = item['content_id']
                    self.run_test("Delete Content", "DELETE", f"content/{content_id}", 200)

        return True

    def test_activity_operations(self):
        """Test activity feed operations"""
        # Get activity feed
        self.run_test("Get Activity Feed", "GET", "activity", 200)
        self.run_test("Get Limited Activity", "GET", "activity?limit=10", 200)
        self.run_test("Get System Activity", "GET", "activity?event_type=system", 200)
        return True

    def test_system_status(self):
        """Test system status"""
        return self.run_test("System Status", "GET", "system/status", 200)

    def test_automation_policies(self):
        """Test automation policies operations"""
        # Get all policies
        success, policies_data = self.run_test("Get Automation Policies", "GET", "policies", 200)
        
        if success and policies_data and len(policies_data) > 0:
            # Test updating a policy
            policy_id = policies_data[0].get('policy_id')
            if policy_id:
                update_data = {
                    "intent": policies_data[0].get('intent'),
                    "action": "require_approval",
                    "high_action": "auto_run",
                    "medium_action": "require_approval", 
                    "low_action": "escalate",
                    "enabled": True
                }
                self.run_test("Update Automation Policy", "PUT", f"policies/{policy_id}", 200, update_data)
        
        return True

    def test_escalation_rules(self):
        """Test escalation rules operations"""
        # Get all escalation rules
        success, rules_data = self.run_test("Get Escalation Rules", "GET", "escalation-rules", 200)
        
        # Create new escalation rule
        new_rule = {
            "name": "Test Escalation Rule",
            "condition_type": "keyword",
            "condition_value": "urgent,emergency",
            "route_to": "Test Manager",
            "priority": "high",
            "enabled": True
        }
        success, created_rule = self.run_test("Create Escalation Rule", "POST", "escalation-rules", 200, new_rule)
        
        # Update and delete the created rule
        if success and created_rule and 'rule_id' in created_rule:
            rule_id = created_rule['rule_id']
            update_data = {**new_rule, "priority": "critical"}
            self.run_test("Update Escalation Rule", "PUT", f"escalation-rules/{rule_id}", 200, update_data)
            self.run_test("Delete Escalation Rule", "DELETE", f"escalation-rules/{rule_id}", 200)
        
        return True

    def test_content_templates(self):
        """Test content templates operations"""
        # Get all templates
        success, templates_data = self.run_test("Get Content Templates", "GET", "templates", 200)
        
        # Test filtering by category
        self.run_test("Get Welcome Templates", "GET", "templates?category=welcome", 200)
        
        # Create new template
        new_template = {
            "name": "Test Template",
            "category": "follow_up",
            "template_type": "email",
            "subject_template": "Following up: {{subject}}",
            "body_template": "Hi {{contact_name}},\n\nJust following up on {{situation}}.\n\nBest regards,\nThe Team",
            "variables": ["contact_name", "subject", "situation"],
            "tags": ["test", "follow-up"]
        }
        success, created_template = self.run_test("Create Content Template", "POST", "templates", 200, new_template)
        
        # Test template generation and cleanup
        if success and created_template and 'template_id' in created_template:
            template_id = created_template['template_id']
            
            # Get specific template
            self.run_test("Get Template Detail", "GET", f"templates/{template_id}", 200)
            
            # Generate from template (AI operation - may take longer)
            print("   Testing template generation (may take 10-15 seconds)...")
            generation_data = {
                "template_id": template_id,
                "context": {
                    "contact_name": "John Doe",
                    "subject": "Property Inquiry",
                    "situation": "your interest in downtown properties"
                }
            }
            self.run_test("Generate from Template", "POST", f"templates/{template_id}/generate", 200, generation_data, timeout=20)
            
            # Delete the created template
            self.run_test("Delete Content Template", "DELETE", f"templates/{template_id}", 200)
        
        return True

    def test_batch_operations(self):
        """Test batch inbox operations"""
        # Get inbox items for batch testing
        success, inbox_data = self.run_test("Get Inbox for Batch", "GET", "inbox?status=new", 200)
        
        if success and inbox_data and len(inbox_data) > 0:
            # Get up to 2 inbox IDs for batch testing
            inbox_ids = [item['inbox_id'] for item in inbox_data[:2]]
            
            # Test batch analyze (AI operation - may take longer)
            print("   Testing batch AI analysis (may take 15-20 seconds)...")
            batch_analyze_data = {"inbox_ids": inbox_ids}
            success, batch_result = self.run_test("Batch Analyze Inbox", "POST", "inbox/batch-analyze", 200, batch_analyze_data, timeout=30)
            
            # Test batch approve if analysis was successful
            if success and batch_result:
                print("   Testing batch approval...")
                self.run_test("Batch Approve Inbox", "POST", "inbox/batch-approve", 200, batch_analyze_data, timeout=15)
        
        return True

    def test_phase5_auto_execution(self):
        """Test Phase 5 auto-execution pipeline and advanced escalation"""
        print("   Testing Phase 5 auto-execution features...")
        
        # First, get current policies to understand auto_run settings
        success, policies_data = self.run_test("Get Policies for Auto-execution Test", "GET", "policies", 200)
        if not success:
            return False
            
        # Find a policy with auto_run action for testing
        auto_run_policy = None
        for policy in policies_data:
            if policy.get('high_action') == 'auto_run' or policy.get('action') == 'auto_run':
                auto_run_policy = policy
                break
        
        if not auto_run_policy:
            print("   No auto_run policy found, setting booking policy to auto_run for testing...")
            # Update booking policy to have auto_run for high confidence
            booking_policy = next((p for p in policies_data if p.get('intent') == 'booking'), None)
            if booking_policy:
                update_data = {
                    "intent": "booking",
                    "action": "auto_run",
                    "high_action": "auto_run",
                    "medium_action": "require_approval",
                    "low_action": "escalate",
                    "enabled": True
                }
                self.run_test("Set Booking Policy to Auto-run", "PUT", f"policies/{booking_policy['policy_id']}", 200, update_data)
        
        # Test advanced escalation rule creation with new condition types
        advanced_escalation_rules = [
            {
                "name": "Calendar Conflict Detection",
                "condition_type": "calendar_conflict",
                "condition_value": "any",
                "route_to": "Calendar Manager",
                "priority": "high",
                "enabled": True
            },
            {
                "name": "Incomplete Entity Detection",
                "condition_type": "incomplete_entities", 
                "condition_value": "person_name,email",
                "route_to": "Data Quality Team",
                "priority": "normal",
                "enabled": True
            },
            {
                "name": "Urgency Detection",
                "condition_type": "urgency",
                "condition_value": "any",
                "route_to": "Priority Queue",
                "priority": "critical",
                "enabled": True
            },
            {
                "name": "Contact Type Routing",
                "condition_type": "contact_type",
                "condition_value": "investor",
                "route_to": "Investment Team",
                "priority": "high", 
                "enabled": True
            }
        ]
        
        created_rule_ids = []
        for rule_data in advanced_escalation_rules:
            success, created_rule = self.run_test(f"Create Advanced Escalation Rule: {rule_data['name']}", "POST", "escalation-rules", 200, rule_data)
            if success and created_rule and 'rule_id' in created_rule:
                created_rule_ids.append(created_rule['rule_id'])
        
        # Get inbox items to test auto-execution
        success, inbox_data = self.run_test("Get All Inbox Items", "GET", "inbox", 200)
        if success and inbox_data:
            # Look for items that can be analyzed
            unprocessed_items = [item for item in inbox_data if item.get('status') == 'new']
            processed_items = [item for item in inbox_data if item.get('status') == 'processed']
            
            # Test single item analysis with auto-execution
            if unprocessed_items:
                test_item = unprocessed_items[0]
                print(f"   Testing auto-execution on item: {test_item['subject'][:50]}...")
                success, analyzed_item = self.run_test("Analyze Item for Auto-execution", "POST", f"inbox/{test_item['inbox_id']}/analyze", 200, timeout=25)
                
                if success and analyzed_item:
                    # Check for auto-execution indicators
                    auto_executed = analyzed_item.get('auto_executed', False)
                    execution_results = analyzed_item.get('execution_results', [])
                    policy_action = analyzed_item.get('policy_action')
                    escalation = analyzed_item.get('escalation')
                    
                    print(f"   Auto-executed: {auto_executed}")
                    print(f"   Policy action: {policy_action}")
                    print(f"   Escalation: {escalation is not None}")
                    if execution_results:
                        print(f"   Execution results: {len(execution_results)} actions")
                    
                    # Verify auto-execution fields are properly set
                    if auto_executed:
                        if analyzed_item.get('status') != 'auto_actioned':
                            self.failed_tests.append("Auto-executed item should have status=auto_actioned")
                        if not analyzed_item.get('auto_executed_at'):
                            self.failed_tests.append("Auto-executed item should have auto_executed_at timestamp")
                        if not execution_results:
                            self.failed_tests.append("Auto-executed item should have execution_results")
            
            # Test batch analysis with auto-execution
            if len(unprocessed_items) >= 2:
                batch_ids = [item['inbox_id'] for item in unprocessed_items[:2]]
                print(f"   Testing batch auto-execution on {len(batch_ids)} items...")
                batch_data = {"inbox_ids": batch_ids}
                success, batch_result = self.run_test("Batch Analyze with Auto-execution", "POST", "inbox/batch-analyze", 200, batch_data, timeout=35)
                
                if success and batch_result:
                    results = batch_result.get('results', [])
                    auto_executed_count = sum(1 for r in results if r.get('auto_executed', False))
                    escalated_count = sum(1 for r in results if r.get('escalation') is not None)
                    
                    print(f"   Batch results: {len(results)} processed, {auto_executed_count} auto-executed, {escalated_count} escalated")
        
        # Clean up created escalation rules
        for rule_id in created_rule_ids:
            self.run_test(f"Cleanup Escalation Rule", "DELETE", f"escalation-rules/{rule_id}", 200)
        
        return True

def main():
    print("🚀 Starting Quantro Flow | Business OS API Tests")
    print("🔬 Focus: AI Billing System & Authentication")
    print("=" * 60)
    
    tester = QuantroOSAPITester()

    # Test authentication first
    print("\n🔐 AUTHENTICATION TESTS")
    auth_success = tester.test_supabase_auth()
    if auth_success:
        tester.test_auth_me_endpoint()
    
    # Test basic health endpoints (no auth required)
    print("\n📊 BASIC HEALTH & METRICS")
    tester.test_health_check()
    
    # Test AI billing system (requires auth)
    if auth_success:
        print("\n🤖 AI BILLING SYSTEM TESTS")
        tester.test_ai_billing_endpoints()
        
        print("\n🔒 AUTHENTICATION REQUIREMENT TESTS")
        tester.test_ai_endpoints_without_auth()
        
        # Test some core functionality with auth
        print("\n📧 SMART INBOX OPERATIONS (with auth)")
        tester.test_inbox_operations()
        
        print("\n✍️ CONTENT ENGINE (with auth)")
        tester.test_content_operations()
    else:
        print("\n⚠️ Skipping authenticated tests - authentication failed")
        print("   This may be expected if test credentials are not set up")

    # Print final results
    print("\n" + "=" * 60)
    print(f"📊 FINAL RESULTS: {tester.tests_passed}/{tester.tests_run} tests passed")
    
    if tester.failed_tests:
        print(f"\n❌ FAILED TESTS ({len(tester.failed_tests)}):")
        for failure in tester.failed_tests:
            print(f"   • {failure}")
    else:
        print("\n✅ ALL TESTS PASSED!")

    success_rate = (tester.tests_passed / tester.tests_run * 100) if tester.tests_run > 0 else 0
    print(f"\n📈 Success Rate: {success_rate:.1f}%")
    
    # Special handling for AI billing tests
    if auth_success:
        print(f"\n🤖 AI Billing System: Authentication successful")
        print(f"   User authenticated: {tester.user_info.get('email', 'N/A') if tester.user_info else 'N/A'}")
        print(f"   Access token: {'✓ Available' if tester.access_token else '✗ Missing'}")
    else:
        print(f"\n🤖 AI Billing System: Could not test due to authentication issues")
        print(f"   This may indicate:")
        print(f"   - Test credentials need to be updated")
        print(f"   - Supabase configuration issues")
        print(f"   - Network connectivity problems")
    
    return 0 if success_rate >= 80 else 1

if __name__ == "__main__":
    sys.exit(main())