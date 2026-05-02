#!/usr/bin/env python3
"""
Test script for Welcome Onboarding Flow (Phase 7d)
Tests the POST /api/onboarding/welcome/complete endpoint
"""
import requests
import sys
import json

BASE_URL = "https://quantro-os.preview.emergentagent.com"
SUPABASE_URL = "https://ukootpnechabpmwsmxsi.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVrb290cG5lY2hhYnBtd3NteHNpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMwOTk2NDcsImV4cCI6MjA4ODY3NTY0N30.xAB8F7stKKJC5dIY6-dPkuwbE-IhhtYkmti7TB0NLfI"

# Test credentials from review request
TEST_EMAIL = "contacto@kontagroup.com"
TEST_PASSWORD = "VSu74Konta6C80"

def authenticate():
    """Authenticate with Supabase and get access token"""
    print("🔐 Authenticating with Supabase...")
    auth_url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    
    try:
        response = requests.post(auth_url, json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        }, headers={
            "apikey": SUPABASE_ANON_KEY,
            "Content-Type": "application/json"
        }, timeout=10)
        
        if response.status_code == 200:
            auth_data = response.json()
            access_token = auth_data.get("access_token")
            user = auth_data.get("user", {})
            print(f"✅ Authentication successful")
            print(f"   User ID: {user.get('id', 'N/A')}")
            print(f"   Email: {user.get('email', 'N/A')}")
            print(f"   needs_onboarding: {user.get('user_metadata', {}).get('needs_onboarding', 'N/A')}")
            return access_token, user
        else:
            print(f"❌ Authentication failed: {response.status_code}")
            print(f"   Response: {response.text}")
            return None, None
    except Exception as e:
        print(f"❌ Authentication error: {str(e)}")
        return None, None

def test_welcome_complete_endpoint(access_token):
    """Test POST /api/onboarding/welcome/complete endpoint"""
    print("\n🧪 Testing Welcome Onboarding Complete Endpoint...")
    
    endpoint = f"{BASE_URL}/api/onboarding/welcome/complete"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Test payload matching the expected request body
    payload = {
        "industry": "other",
        "start_choice": "email",
        "inbox_connected": True,
        "calendar_connected": True,
        "crm_connected": False,
        "automations_connected": False
    }
    
    print(f"   Endpoint: {endpoint}")
    print(f"   Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        
        print(f"\n📊 Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Endpoint returned 200 OK")
            print(f"\n📦 Response Data:")
            print(json.dumps(data, indent=2))
            
            # Validate response structure
            errors = []
            
            if not data.get("success"):
                errors.append("Missing or false 'success' field")
            
            if "workspace_id" not in data:
                errors.append("Missing 'workspace_id' field")
            
            if data.get("industry") != "other":
                errors.append(f"Expected industry='other', got '{data.get('industry')}'")
            
            if data.get("simulation_mode") != True:
                errors.append(f"Expected simulation_mode=true, got {data.get('simulation_mode')}")
            
            counters = data.get("counters", {})
            if not isinstance(counters, dict):
                errors.append("Missing or invalid 'counters' object")
            else:
                required_counters = ["conversations", "opportunities", "contacts", "events"]
                for counter in required_counters:
                    if counter not in counters:
                        errors.append(f"Missing counter: {counter}")
                    elif not isinstance(counters[counter], int):
                        errors.append(f"Counter '{counter}' is not an integer: {type(counters[counter])}")
                    elif counters[counter] < 0:
                        errors.append(f"Counter '{counter}' is negative: {counters[counter]}")
            
            if errors:
                print(f"\n⚠️  Response validation errors:")
                for error in errors:
                    print(f"   - {error}")
                return False
            else:
                print(f"\n✅ All response validations passed!")
                print(f"   Counters: conversations={counters['conversations']}, opportunities={counters['opportunities']}, contacts={counters['contacts']}, events={counters['events']}")
                return True
        else:
            print(f"❌ Endpoint failed with status {response.status_code}")
            print(f"   Response: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Request error: {str(e)}")
        return False

def main():
    print("=" * 60)
    print("Welcome Onboarding Backend Test (Phase 7d)")
    print("=" * 60)
    
    # Step 1: Authenticate
    access_token, user = authenticate()
    if not access_token:
        print("\n❌ Cannot proceed without authentication")
        return 1
    
    # Step 2: Test the welcome complete endpoint
    success = test_welcome_complete_endpoint(access_token)
    
    print("\n" + "=" * 60)
    if success:
        print("✅ Backend test PASSED")
        print("=" * 60)
        return 0
    else:
        print("❌ Backend test FAILED")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
