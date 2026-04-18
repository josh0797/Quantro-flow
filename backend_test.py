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

    def run_test(self, name, method, endpoint, expected_status, data=None, timeout=30):
        """Run a single API test"""
        url = f"{self.base_url}/api/{endpoint}"
        headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
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
    print("🚀 Starting Quantro One | Realty OS API Tests")
    print("=" * 60)
    
    tester = QuantroOSAPITester()

    # Run all tests
    print("\n📊 BASIC HEALTH & METRICS")
    tester.test_health_check()
    tester.test_dashboard_metrics()
    tester.test_dashboard_suggestions()

    print("\n📧 SMART INBOX OPERATIONS")
    tester.test_inbox_operations()

    print("\n📅 CALENDAR OPERATIONS")
    tester.test_calendar_operations()

    print("\n👥 CRM/CONTACTS OPERATIONS")
    tester.test_contacts_operations()

    print("\n🎯 AGENTS & ONBOARDING")
    tester.test_agents_operations()

    print("\n✍️ CONTENT ENGINE")
    tester.test_content_operations()

    print("\n📈 ACTIVITY & SYSTEM")
    tester.test_activity_operations()
    tester.test_system_status()

    print("\n🤖 AUTOMATION POLICIES")
    tester.test_automation_policies()

    print("\n🚨 ESCALATION RULES")
    tester.test_escalation_rules()

    print("\n📝 CONTENT TEMPLATES")
    tester.test_content_templates()

    print("\n🔄 BATCH OPERATIONS")
    tester.test_batch_operations()

    print("\n⚡ PHASE 5 AUTO-EXECUTION PIPELINE")
    tester.test_phase5_auto_execution()

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
    
    return 0 if success_rate >= 90 else 1

if __name__ == "__main__":
    sys.exit(main())