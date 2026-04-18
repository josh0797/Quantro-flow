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