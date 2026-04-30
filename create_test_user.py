#!/usr/bin/env python3
"""
Try to sign up a new test user in Supabase
"""

import requests
import json
import uuid
from datetime import datetime

SUPABASE_URL = "https://ukootpnechabpmwsmxsi.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVrb290cG5lY2hhYnBtd3NteHNpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMwOTk2NDcsImV4cCI6MjA4ODY3NTY0N30.xAB8F7stKKJC5dIY6-dPkuwbE-IhhtYkmti7TB0NLfI"

print("=" * 60)
print("ATTEMPTING TO CREATE TEST USER IN SUPABASE")
print("=" * 60)

# Generate unique email
test_email = f"test_{uuid.uuid4().hex[:8]}@quantro-test.com"
test_password = "TestPass123!@#"

print(f"\nTest credentials:")
print(f"Email: {test_email}")
print(f"Password: {test_password}")

# Try to sign up
signup_url = f"{SUPABASE_URL}/auth/v1/signup"
headers = {
    "apikey": SUPABASE_ANON_KEY,
    "Content-Type": "application/json"
}

payload = {
    "email": test_email,
    "password": test_password,
    "data": {
        "full_name": "Test User Phase7c",
        "name": "Test User Phase7c"
    }
}

print(f"\nAttempting signup at: {signup_url}")
try:
    response = requests.post(signup_url, json=payload, headers=headers, timeout=10)
    print(f"Response status: {response.status_code}")
    
    if response.status_code in [200, 201]:
        data = response.json()
        print("✅ Signup successful!")
        
        if "access_token" in data:
            print(f"\nAccess token obtained: {data['access_token'][:50]}...")
            print(f"User ID: {data.get('user', {}).get('id')}")
            
            # Save credentials for testing
            with open('/app/test_user_credentials.json', 'w') as f:
                json.dump({
                    "email": test_email,
                    "password": test_password,
                    "access_token": data["access_token"],
                    "user_id": data.get("user", {}).get("id"),
                    "created_at": datetime.now().isoformat()
                }, f, indent=2)
            print("\n✅ Credentials saved to /app/test_user_credentials.json")
        else:
            print("\n⚠️  Signup successful but no access_token in response")
            print(f"Response: {json.dumps(data, indent=2)}")
    else:
        print(f"❌ Signup failed: {response.status_code}")
        print(f"Response: {response.text}")
        
        # Try to login with existing test credentials
        print("\n" + "=" * 60)
        print("TRYING EXISTING TEST CREDENTIALS")
        print("=" * 60)
        
        existing_creds = [
            {"email": "josias.martin@hotmail.com", "password": "testpass123"},
            {"email": "josias.martin90@hotmail.com", "password": "testpass123"},
            {"email": "contacto@quantro.ai", "password": "testpass123"}
        ]
        
        login_url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
        
        for creds in existing_creds:
            print(f"\nTrying: {creds['email']}")
            try:
                login_response = requests.post(login_url, json=creds, headers=headers, timeout=10)
                if login_response.status_code == 200:
                    login_data = login_response.json()
                    if "access_token" in login_data:
                        print(f"✅ Login successful!")
                        print(f"Access token: {login_data['access_token'][:50]}...")
                        
                        # Save credentials
                        with open('/app/test_user_credentials.json', 'w') as f:
                            json.dump({
                                "email": creds['email'],
                                "password": creds['password'],
                                "access_token": login_data["access_token"],
                                "user_id": login_data.get("user", {}).get("id"),
                                "created_at": datetime.now().isoformat()
                            }, f, indent=2)
                        print("✅ Credentials saved to /app/test_user_credentials.json")
                        break
                else:
                    print(f"   Failed: {login_response.status_code}")
            except Exception as e:
                print(f"   Error: {e}")

except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
