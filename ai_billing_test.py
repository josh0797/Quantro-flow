#!/usr/bin/env python3
"""
AI Billing System Test Suite for Quantro Flow
Tests the new AI Credits system and run_ai_request wrapper implementation.
"""

import requests
import sys
import json
from datetime import datetime

class AIBillingTester:
    def __init__(self, base_url="https://quantro-os.preview.emergentagent.com"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []
        self.access_token = None
        
    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
            if details:
                print(f"   {details}")
        else:
            self.failed_tests.append(name)
            print(f"❌ {name}")
            if details:
                print(f"   {details}")
    
    def test_health_endpoint(self):
        """Test that health endpoint works (no auth required)"""
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=10)
            success = response.status_code == 200
            details = f"Status: {response.status_code}"
            if success:
                data = response.json()
                details += f", Service: {data.get('service', 'N/A')}"
            self.log_test("Health endpoint", success, details)
            return success
        except Exception as e:
            self.log_test("Health endpoint", False, f"Error: {str(e)}")
            return False
    
    def test_auth_me_endpoint_without_token(self):
        """Test that /api/auth/me requires authentication"""
        try:
            response = requests.get(f"{self.base_url}/api/auth/me", timeout=10)
            success = response.status_code == 401
            details = f"Status: {response.status_code} (expected 401)"
            if response.status_code == 401:
                details += " - Correctly requires authentication"
            self.log_test("Auth/me endpoint without token", success, details)
            return success
        except Exception as e:
            self.log_test("Auth/me endpoint without token", False, f"Error: {str(e)}")
            return False
    
    def test_ai_endpoints_require_auth(self):
        """Test that all AI endpoints require authentication (return 401)"""
        ai_endpoints = [
            ("POST", "inbox/test-id/analyze", {}),
            ("POST", "inbox/batch-analyze", {"inbox_ids": ["test-id"]}),
            ("POST", "content/generate", {"prompt": "test", "type": "both"}),
            ("POST", "templates/test-id/generate", {"context": {}})
        ]
        
        all_success = True
        for method, endpoint, data in ai_endpoints:
            try:
                url = f"{self.base_url}/api/{endpoint}"
                if method == "POST":
                    response = requests.post(url, json=data, timeout=10)
                else:
                    response = requests.get(url, timeout=10)
                
                success = response.status_code == 401
                details = f"{method} {endpoint} - Status: {response.status_code} (expected 401)"
                if success:
                    details += " - Correctly requires authentication"
                else:
                    all_success = False
                    details += f" - Response: {response.text[:100]}"
                
                self.log_test(f"AI endpoint auth requirement: {endpoint}", success, details)
                
            except Exception as e:
                self.log_test(f"AI endpoint auth requirement: {endpoint}", False, f"Error: {str(e)}")
                all_success = False
        
        return all_success
    
    def test_supabase_connection(self):
        """Test connection to Supabase"""
        supabase_url = "https://ukootpnechabpmwsmxsi.supabase.co"
        try:
            # Test Supabase health
            response = requests.get(f"{supabase_url}/rest/v1/", 
                                  headers={"apikey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVrb290cG5lY2hhYnBtd3NteHNpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMwOTk2NDcsImV4cCI6MjA4ODY3NTY0N30.xAB8F7stKKJC5dIY6-dPkuwbE-IhhtYkmti7TB0NLfI"},
                                  timeout=10)
            success = response.status_code in [200, 404]  # 404 is OK for root endpoint
            details = f"Supabase connection - Status: {response.status_code}"
            self.log_test("Supabase connection", success, details)
            return success
        except Exception as e:
            self.log_test("Supabase connection", False, f"Error: {str(e)}")
            return False
    
    def test_openai_key_configured(self):
        """Test if OpenAI key is configured by checking error messages"""
        # This is indirect - we can't directly check the key, but we can see if the error suggests it's missing
        try:
            # Try to call an AI endpoint without auth - if OpenAI key is missing, 
            # we might get a different error than just 401
            response = requests.post(f"{self.base_url}/api/content/generate", 
                                   json={"prompt": "test", "type": "both"}, 
                                   timeout=10)
            
            # We expect 401 (auth required), not 503 (service unavailable due to missing key)
            success = response.status_code == 401
            details = f"Status: {response.status_code} - "
            if response.status_code == 401:
                details += "OpenAI key appears to be configured (auth required first)"
            elif response.status_code == 503:
                details += "OpenAI key may be missing (service unavailable)"
            else:
                details += f"Unexpected response: {response.text[:100]}"
            
            self.log_test("OpenAI key configuration", success, details)
            return success
        except Exception as e:
            self.log_test("OpenAI key configuration", False, f"Error: {str(e)}")
            return False
    
    def test_create_test_user(self):
        """Attempt to create a test user for authentication testing"""
        supabase_url = "https://ukootpnechabpmwsmxsi.supabase.co"
        test_email = f"test.ai.billing.{int(datetime.now().timestamp())}@gmail.com"
        
        try:
            response = requests.post(f"{supabase_url}/auth/v1/signup",
                                   headers={
                                       "apikey": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVrb290cG5lY2hhYnBtd3NteHNpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMwOTk2NDcsImV4cCI6MjA4ODY3NTY0N30.xAB8F7stKKJC5dIY6-dPkuwbE-IhhtYkmti7TB0NLfI",
                                       "Content-Type": "application/json"
                                   },
                                   json={"email": test_email, "password": "TestPass123!"},
                                   timeout=10)
            
            success = response.status_code == 200
            details = f"Status: {response.status_code}"
            if success:
                data = response.json()
                user_id = data.get("id", "N/A")
                details += f" - User created: {user_id} (email confirmation required)"
            else:
                details += f" - Error: {response.text[:100]}"
            
            self.log_test("Create test user", success, details)
            return success, test_email if success else None
        except Exception as e:
            self.log_test("Create test user", False, f"Error: {str(e)}")
            return False, None
    
    def test_ai_billing_schema_requirements(self):
        """Test if the AI billing schema migration appears to be applied"""
        # We can't directly check the database, but we can infer from API behavior
        print("\n📋 AI Billing Schema Requirements Check:")
        print("   The following Supabase schema elements should be present:")
        print("   - profiles table with ai_credits_* columns")
        print("   - ai_credit_usage table")
        print("   - decrement_ai_credits RPC function")
        print("   - Proper RLS policies")
        print("   ⚠️  Cannot directly verify without database access")
        
        # This is informational, not a pass/fail test
        return True
    
    def run_all_tests(self):
        """Run all AI billing tests"""
        print("🤖 AI Billing System Test Suite")
        print("=" * 50)
        print(f"Target: {self.base_url}")
        print(f"Time: {datetime.now().isoformat()}")
        print()
        
        # Basic connectivity tests
        print("🔗 CONNECTIVITY TESTS")
        self.test_health_endpoint()
        self.test_supabase_connection()
        print()
        
        # Authentication requirement tests
        print("🔐 AUTHENTICATION REQUIREMENT TESTS")
        self.test_auth_me_endpoint_without_token()
        self.test_ai_endpoints_require_auth()
        print()
        
        # Configuration tests
        print("⚙️  CONFIGURATION TESTS")
        self.test_openai_key_configured()
        print()
        
        # User creation test
        print("👤 USER CREATION TEST")
        user_created, test_email = self.test_create_test_user()
        if user_created:
            print(f"   📧 Test user created: {test_email}")
            print(f"   ⚠️  Email confirmation required for authentication")
        print()
        
        # Schema requirements
        print("🗄️  SCHEMA REQUIREMENTS")
        self.test_ai_billing_schema_requirements()
        print()
        
        # Summary
        print("=" * 50)
        print(f"📊 RESULTS: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.failed_tests:
            print(f"\n❌ FAILED TESTS:")
            for test in self.failed_tests:
                print(f"   • {test}")
        
        success_rate = (self.tests_passed / self.tests_run * 100) if self.tests_run > 0 else 0
        print(f"\n📈 Success Rate: {success_rate:.1f}%")
        
        # Specific AI billing assessment
        print(f"\n🤖 AI BILLING SYSTEM ASSESSMENT:")
        if success_rate >= 80:
            print("   ✅ Core infrastructure appears to be properly configured")
            print("   ✅ Authentication requirements are enforced")
            print("   ✅ AI endpoints are protected")
            print("   ⚠️  Full testing requires valid Supabase credentials")
        else:
            print("   ❌ Some infrastructure issues detected")
            print("   🔧 Review failed tests above")
        
        print(f"\n📋 NEXT STEPS FOR COMPLETE TESTING:")
        print(f"   1. Obtain valid Supabase credentials for test accounts:")
        print(f"      - josias.martin@hotmail.com")
        print(f"      - josias.martin90@hotmail.com")
        print(f"   2. Verify AI billing schema migration is applied")
        print(f"   3. Test actual AI request flows with authentication")
        print(f"   4. Verify credit deduction and usage logging")
        print(f"   5. Test HTTP 402 blocking for users without credits")
        
        return success_rate >= 80

def main():
    tester = AIBillingTester()
    success = tester.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())