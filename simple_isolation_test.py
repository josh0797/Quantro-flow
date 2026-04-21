#!/usr/bin/env python3
"""
Simple verification test for simulation/live mode isolation
"""

import requests
import json

BASE_URL = "https://quantro-os.preview.emergentagent.com"

def test_basic_isolation():
    print("🔍 Testing Basic Simulation/Live Mode Isolation")
    print("=" * 60)
    
    # Get current profile
    response = requests.get(f"{BASE_URL}/api/business-profile")
    profile = response.json()
    print(f"Current profile: {profile}")
    
    # Test Live Mode
    print("\n--- Testing Live Mode ---")
    profile['simulation_mode'] = False
    response = requests.put(f"{BASE_URL}/api/business-profile", json=profile)
    print(f"Set Live Mode: {response.status_code}")
    
    # Get counts in live mode
    contacts_live = requests.get(f"{BASE_URL}/api/contacts").json()
    inbox_live = requests.get(f"{BASE_URL}/api/inbox").json()
    calendar_live = requests.get(f"{BASE_URL}/api/calendar").json()
    
    print(f"Live Mode - Contacts: {len(contacts_live)}, Inbox: {len(inbox_live)}, Calendar: {len(calendar_live)}")
    
    # Test Simulation Mode
    print("\n--- Testing Simulation Mode ---")
    profile['simulation_mode'] = True
    response = requests.put(f"{BASE_URL}/api/business-profile", json=profile)
    print(f"Set Simulation Mode: {response.status_code}")
    
    # Get counts in simulation mode
    contacts_sim = requests.get(f"{BASE_URL}/api/contacts").json()
    inbox_sim = requests.get(f"{BASE_URL}/api/inbox").json()
    calendar_sim = requests.get(f"{BASE_URL}/api/calendar").json()
    
    print(f"Simulation Mode - Contacts: {len(contacts_sim)}, Inbox: {len(inbox_sim)}, Calendar: {len(calendar_sim)}")
    
    # Test Dashboard Metrics
    print("\n--- Testing Dashboard Metrics ---")
    profile['simulation_mode'] = False
    requests.put(f"{BASE_URL}/api/business-profile", json=profile)
    metrics_live = requests.get(f"{BASE_URL}/api/dashboard/metrics").json()
    
    profile['simulation_mode'] = True
    requests.put(f"{BASE_URL}/api/business-profile", json=profile)
    metrics_sim = requests.get(f"{BASE_URL}/api/dashboard/metrics").json()
    
    print(f"Live Metrics - simulation_mode: {metrics_live.get('simulation_mode')}, contacts: {metrics_live.get('contacts', {}).get('total', 0)}")
    print(f"Sim Metrics - simulation_mode: {metrics_sim.get('simulation_mode')}, contacts: {metrics_sim.get('contacts', {}).get('total', 0)}")
    
    # Test Write Isolation
    print("\n--- Testing Write Isolation ---")
    
    # Create contact in live mode
    profile['simulation_mode'] = False
    requests.put(f"{BASE_URL}/api/business-profile", json=profile)
    
    contact_data = {
        "name": "Live Test Contact",
        "email": "live@test.com",
        "phone": "555-LIVE",
        "type": "lead",
        "source": "test",
        "notes": "Live mode test"
    }
    
    response = requests.post(f"{BASE_URL}/api/contacts", json=contact_data)
    if response.status_code == 200:
        live_contact = response.json()
        contact_id = live_contact['contact_id']
        print(f"Created live contact: {contact_id}")
        
        # Switch to simulation mode and try to access
        profile['simulation_mode'] = True
        requests.put(f"{BASE_URL}/api/business-profile", json=profile)
        
        response = requests.get(f"{BASE_URL}/api/contacts/{contact_id}")
        if response.status_code == 404:
            print("✅ Live contact correctly NOT visible in simulation mode")
        else:
            print("❌ Live contact visible in simulation mode - DATA LEAKAGE!")
            
        # Switch back to live mode and verify visibility
        profile['simulation_mode'] = False
        requests.put(f"{BASE_URL}/api/business-profile", json=profile)
        
        response = requests.get(f"{BASE_URL}/api/contacts/{contact_id}")
        if response.status_code == 200:
            print("✅ Live contact correctly visible in live mode")
        else:
            print("❌ Live contact not visible in live mode")
    else:
        print(f"Failed to create live contact: {response.status_code}")
    
    print("\n" + "=" * 60)
    print("Basic isolation test completed")

if __name__ == "__main__":
    test_basic_isolation()