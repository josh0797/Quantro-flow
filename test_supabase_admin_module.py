#!/usr/bin/env python3
"""
Direct test of supabase_admin module functions
"""

import sys
import os

# Add backend to path
sys.path.insert(0, '/app/backend')

# Load environment variables
from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

print("=" * 60)
print("TESTING SUPABASE_ADMIN MODULE")
print("=" * 60)

try:
    import supabase_admin
    print("✅ supabase_admin module imported successfully")
except Exception as e:
    print(f"❌ Failed to import supabase_admin: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 1: is_dual_write_enabled()")
print("=" * 60)
try:
    result = supabase_admin.is_dual_write_enabled()
    print(f"Result: {result}")
    if result is True:
        print("✅ PASS - is_dual_write_enabled() returns True")
    else:
        print(f"❌ FAIL - Expected True, got {result}")
except Exception as e:
    print(f"❌ ERROR - {e}")

print("\n" + "=" * 60)
print("TEST 2: is_supabase_primary()")
print("=" * 60)
try:
    result = supabase_admin.is_supabase_primary()
    print(f"Result: {result}")
    # Phase 1 default is supabase when configured; mongo is rollback.
    primary = os.environ.get("QUANTRO_DB_PRIMARY", "supabase").lower()
    expected = primary == "supabase"
    if result is expected:
        print(f"✅ PASS - is_supabase_primary() returns {result} (QUANTRO_DB_PRIMARY={primary})")
    else:
        print(f"⚠️  WARN - Expected {expected} for primary={primary}, got {result}")
except Exception as e:
    print(f"❌ ERROR - {e}")

print("\n" + "=" * 60)
print("TEST 3: resolve_default_org_id()")
print("=" * 60)
try:
    result = supabase_admin.resolve_default_org_id()
    print(f"Result: {result}")
    expected = "1250ff9b-ac04-4370-8fd3-f846f34d1159"
    if result == expected:
        print(f"✅ PASS - resolve_default_org_id() returns correct UUID")
    else:
        print(f"❌ FAIL - Expected {expected}, got {result}")
except Exception as e:
    print(f"❌ ERROR - {e}")

print("\n" + "=" * 60)
print("TEST 4: Environment Variables")
print("=" * 60)
print(f"SUPABASE_URL: {os.environ.get('SUPABASE_URL', 'NOT SET')}")
print(f"SUPABASE_ANON_KEY: {'SET' if os.environ.get('SUPABASE_ANON_KEY') else 'NOT SET'}")
print(f"QUANTRO_DB_PRIMARY: {os.environ.get('QUANTRO_DB_PRIMARY', 'NOT SET')}")
print(f"QUANTRO_DEFAULT_ORG_ID: {os.environ.get('QUANTRO_DEFAULT_ORG_ID', 'NOT SET')}")
print(f"SUPABASE_SERVICE_ROLE_KEY: {'SET' if os.environ.get('SUPABASE_SERVICE_ROLE_KEY') else 'NOT SET (expected)'}")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("All module function tests completed.")
print("Check results above for any failures.")
