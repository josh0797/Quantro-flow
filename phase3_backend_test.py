#!/usr/bin/env python3
"""
Phase 3 Specific Backend API Testing for Quantro One | Realty OS
Tests batch AI triage and manual override features specifically
"""

import requests
import json
import sys
import time
from datetime import datetime

class Phase3APITester:
    def __init__(self, base_url="https://quantro-os.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def log_test(self, name: str, success: bool, details: str = ""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
            if details:
                print(f"   {details}")
        else:
            self.failed_tests.append({"test": name, "details": details})
            print(f"❌ {name}")
            if details:
                print(f"   {details}")

    def get_inbox_items(self):
        """Get current inbox items"""
        try:
            response = self.session.get(f"{self.base_url}/api/inbox", timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except:
            return []

    def test_batch_analyze(self):
        """Test batch analysis endpoint"""
        print("\n🔍 Testing Batch Analyze...")
        
        # Get new items
        inbox_items = self.get_inbox_items()
        new_items = [item for item in inbox_items if item.get('status') == 'new']
        
        if len(new_items) < 1:
            self.log_test("Batch Analyze", False, "No 'new' items found to analyze")
            return False
        
        # Take first 2 items (or all if less than 2)
        inbox_ids = [item['inbox_id'] for item in new_items[:2]]
        
        try:
            payload = {"inbox_ids": inbox_ids}
            print(f"   Analyzing {len(inbox_ids)} items: {[item['subject'][:30] for item in new_items[:2]]}")
            
            response = self.session.post(f"{self.base_url}/api/inbox/batch-analyze", 
                                       json=payload, timeout=60)
            
            if response.status_code == 200:
                data = response.json()
                total = data.get('total', 0)
                classified = data.get('classified', 0)
                results = data.get('results', [])
                
                success = classified > 0 and total == len(inbox_ids)
                details = f"Processed {total} items, {classified} classified successfully"
                
                # Check individual results
                for result in results:
                    if result.get('status') == 'classified':
                        item_data = result.get('data', {})
                        intent = item_data.get('ai_intent', {}).get('intent', 'unknown')
                        confidence = item_data.get('ai_intent', {}).get('confidence', 0)
                        print(f"   → {item_data.get('subject', 'Unknown')[:30]}: {intent} ({confidence:.0%})")
                
                self.log_test("Batch Analyze", success, details)
                return success
            else:
                self.log_test("Batch Analyze", False, f"HTTP {response.status_code}: {response.text[:100]}")
                return False
                
        except Exception as e:
            self.log_test("Batch Analyze", False, f"Error: {str(e)}")
            return False

    def test_batch_approve(self):
        """Test batch approval endpoint"""
        print("\n🔍 Testing Batch Approve...")
        
        # Get processed items
        inbox_items = self.get_inbox_items()
        processed_items = [item for item in inbox_items if item.get('status') == 'processed' 
                          and item.get('ai_suggested_action') is not None]
        
        if len(processed_items) < 1:
            self.log_test("Batch Approve", False, "No 'processed' items with actions found")
            return False
        
        # Take first item
        inbox_ids = [processed_items[0]['inbox_id']]
        
        try:
            payload = {"inbox_ids": inbox_ids}
            action_type = processed_items[0]['ai_suggested_action'].get('type', 'unknown')
            print(f"   Approving action '{action_type}' for: {processed_items[0]['subject'][:30]}")
            
            response = self.session.post(f"{self.base_url}/api/inbox/batch-approve", 
                                       json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                total = data.get('total', 0)
                actioned = data.get('actioned', 0)
                results = data.get('results', [])
                
                success = actioned > 0 and total == len(inbox_ids)
                details = f"Approved {actioned}/{total} actions"
                
                for result in results:
                    if result.get('status') == 'actioned':
                        print(f"   → Action executed: {result.get('action_type', 'unknown')}")
                
                self.log_test("Batch Approve", success, details)
                return success
            else:
                self.log_test("Batch Approve", False, f"HTTP {response.status_code}: {response.text[:100]}")
                return False
                
        except Exception as e:
            self.log_test("Batch Approve", False, f"Error: {str(e)}")
            return False

    def test_manual_override_details(self):
        """Test manual override of AI details"""
        print("\n🔍 Testing Manual Override Details...")
        
        # Get processed items
        inbox_items = self.get_inbox_items()
        processed_items = [item for item in inbox_items if item.get('status') == 'processed']
        
        if not processed_items:
            self.log_test("Manual Override Details", False, "No processed items found")
            return False
        
        item = processed_items[0]
        inbox_id = item['inbox_id']
        
        try:
            # Update entities and suggested action
            payload = {
                "entities": {
                    "person_name": "Test Override Name",
                    "email": "test@override.com",
                    "phone": "555-0123",
                    "property": "123 Override Street"
                },
                "suggested_action_type": "send_follow_up",
                "suggested_action_description": "Send customized follow-up message",
                "summary": "Updated summary via manual override"
            }
            
            print(f"   Updating details for: {item['subject'][:30]}")
            
            response = self.session.put(f"{self.base_url}/api/inbox/{inbox_id}/details", 
                                      json=payload, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Verify the updates were applied
                entities = data.get('ai_intent', {}).get('entities', {})
                action = data.get('ai_suggested_action', {})
                summary = data.get('ai_intent', {}).get('summary', '')
                
                name_updated = entities.get('person_name') == "Test Override Name"
                email_updated = entities.get('email') == "test@override.com"
                action_updated = action.get('type') == "send_follow_up"
                summary_updated = "manual override" in summary.lower()
                
                success = name_updated and email_updated and action_updated
                details = f"Updated entities and action successfully"
                
                if success:
                    print(f"   → Name: {entities.get('person_name')}")
                    print(f"   → Email: {entities.get('email')}")
                    print(f"   → Action: {action.get('type')}")
                
                self.log_test("Manual Override Details", success, details)
                return success
            else:
                self.log_test("Manual Override Details", False, f"HTTP {response.status_code}: {response.text[:100]}")
                return False
                
        except Exception as e:
            self.log_test("Manual Override Details", False, f"Error: {str(e)}")
            return False

    def test_approve_with_overrides(self):
        """Test approve with manual overrides"""
        print("\n🔍 Testing Approve with Overrides...")
        
        # Get processed items
        inbox_items = self.get_inbox_items()
        processed_items = [item for item in inbox_items if item.get('status') == 'processed' 
                          and item.get('ai_suggested_action') is not None]
        
        if not processed_items:
            self.log_test("Approve with Overrides", False, "No processed items with actions found")
            return False
        
        item = processed_items[0]
        inbox_id = item['inbox_id']
        action_type = item['ai_suggested_action'].get('type')
        
        try:
            # Prepare overrides based on action type
            payload = {}
            if action_type == 'schedule_meeting':
                payload = {
                    "title": "Override Meeting Title",
                    "description": "Override meeting description",
                    "location": "Override Location",
                    "contact_name": "Override Contact Name",
                    "start_time": "2024-12-20T14:00:00",
                    "end_time": "2024-12-20T15:00:00"
                }
            elif action_type == 'create_contact':
                payload = {
                    "contact_name": "Override Contact Name",
                    "contact_email": "override@test.com",
                    "contact_phone": "555-9999"
                }
            else:
                payload = {
                    "contact_name": "Override Contact Name",
                    "contact_email": "override@test.com"
                }
            
            print(f"   Executing '{action_type}' with overrides for: {item['subject'][:30]}")
            
            response = self.session.post(f"{self.base_url}/api/inbox/{inbox_id}/approve-with-overrides", 
                                       json=payload, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                action_executed = data.get('success', False)
                results = data.get('results', [])
                executed_type = data.get('action_type', 'unknown')
                
                success = action_executed and executed_type == action_type
                details = f"Executed {executed_type} with overrides"
                
                if results:
                    for result in results:
                        result_type = result.get('type', 'unknown')
                        print(f"   → Created: {result_type}")
                        if 'event_id' in result:
                            print(f"   → Event ID: {result['event_id']}")
                        if 'contact_id' in result:
                            print(f"   → Contact ID: {result['contact_id']}")
                
                self.log_test("Approve with Overrides", success, details)
                return success
            else:
                self.log_test("Approve with Overrides", False, f"HTTP {response.status_code}: {response.text[:100]}")
                return False
                
        except Exception as e:
            self.log_test("Approve with Overrides", False, f"Error: {str(e)}")
            return False

    def test_decline_action(self):
        """Test declining an action"""
        print("\n🔍 Testing Decline Action...")
        
        # Get processed items that haven't been actioned
        inbox_items = self.get_inbox_items()
        processed_items = [item for item in inbox_items if item.get('status') == 'processed']
        
        if not processed_items:
            self.log_test("Decline Action", False, "No processed items found to decline")
            return False
        
        item = processed_items[0]
        inbox_id = item['inbox_id']
        
        try:
            print(f"   Declining action for: {item['subject'][:30]}")
            
            response = self.session.post(f"{self.base_url}/api/inbox/{inbox_id}/decline", timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                declined = data.get('success', False)
                details = f"Successfully declined action"
                
                self.log_test("Decline Action", declined, details)
                return declined
            else:
                self.log_test("Decline Action", False, f"HTTP {response.status_code}: {response.text[:100]}")
                return False
                
        except Exception as e:
            self.log_test("Decline Action", False, f"Error: {str(e)}")
            return False

    def run_phase3_tests(self):
        """Run Phase 3 specific tests"""
        print("🚀 Starting Quantro One | Realty OS Phase 3 Backend Tests")
        print("Testing Batch AI Triage and Manual Override Features")
        print("=" * 60)
        
        # Test batch operations
        self.test_batch_analyze()
        time.sleep(2)  # Allow processing time
        
        self.test_batch_approve()
        time.sleep(1)
        
        # Test manual override features
        self.test_manual_override_details()
        time.sleep(1)
        
        self.test_approve_with_overrides()
        time.sleep(1)
        
        self.test_decline_action()
        
        # Summary
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        
        print("\n" + "=" * 60)
        print(f"📊 Phase 3 Test Summary: {self.tests_passed}/{self.tests_run} passed ({success_rate:.1f}%)")
        
        if self.failed_tests:
            print("\n❌ Failed Tests:")
            for failure in self.failed_tests:
                print(f"   • {failure['test']}: {failure['details']}")
        else:
            print("\n✅ ALL PHASE 3 TESTS PASSED!")
        
        return {
            "total_tests": self.tests_run,
            "passed_tests": self.tests_passed,
            "failed_tests": len(self.failed_tests),
            "success_rate": success_rate,
            "failures": self.failed_tests
        }

def main():
    """Main test execution"""
    tester = Phase3APITester()
    summary = tester.run_phase3_tests()
    
    # Return appropriate exit code
    return 0 if summary["failed_tests"] == 0 else 1

if __name__ == "__main__":
    sys.exit(main())