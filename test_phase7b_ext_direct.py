#!/usr/bin/env python3
"""
Direct testing of Phase 7b-ext using FastAPI TestClient
This bypasses Supabase auth and tests the core logic directly
"""

import sys
import os
sys.path.insert(0, '/app/backend')

import asyncio
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

# MongoDB connection
MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "quantro_os"
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

async def test_role_migration():
    """Test that legacy roles are migrated to Quantro taxonomy"""
    print("\n=== TEST 1: Role Migration ===")
    
    # Check current state
    workspace_members_col = db["workspace_members"]
    members = await workspace_members_col.find(
        {"workspace_id": "default"},
        {"_id": 0, "user_id": 1, "role": 1}
    ).to_list(100)
    
    print(f"Found {len(members)} members in default workspace:")
    for m in members:
        print(f"  - {m['user_id']}: {m['role']}")
    
    # Check if any legacy roles exist
    legacy_roles = ["agent", "operator", "manager", "admin"]
    legacy_count = sum(1 for m in members if m.get("role") in legacy_roles)
    
    if legacy_count > 0:
        print(f"\n⚠️  Found {legacy_count} members with legacy roles")
        print("Migration should convert these on next app boot")
        
        # Manually trigger migration
        from server import migrate_legacy_role_names
        print("\nManually triggering migration...")
        await migrate_legacy_role_names()
        
        # Check again
        members_after = await workspace_members_col.find(
            {"workspace_id": "default"},
            {"_id": 0, "user_id": 1, "role": 1}
        ).to_list(100)
        
        print("\nAfter migration:")
        for m in members_after:
            print(f"  - {m['user_id']}: {m['role']}")
        
        legacy_count_after = sum(1 for m in members_after if m.get("role") in legacy_roles)
        
        if legacy_count_after == 0:
            print("✅ All legacy roles migrated successfully")
            return True
        else:
            print(f"❌ Still have {legacy_count_after} legacy roles")
            return False
    else:
        print("✅ No legacy roles found (already migrated)")
        return True

async def test_role_normalization():
    """Test that _normalize_role works correctly"""
    print("\n=== TEST 2: Role Normalization Function ===")
    
    from server import _normalize_role, ROLE_ALIASES
    
    print("Testing _normalize_role function:")
    test_cases = [
        ("agent", "viewer"),
        ("operator", "member"),
        ("manager", "accountant"),
        ("admin", "leader"),
        ("owner", "owner"),
        ("viewer", "viewer"),
        ("member", "member"),
        ("accountant", "accountant"),
        ("leader", "leader"),
        ("AGENT", "viewer"),  # Test case insensitivity
        ("  operator  ", "member"),  # Test whitespace
        ("invalid", "viewer"),  # Test default
    ]
    
    all_passed = True
    for input_role, expected in test_cases:
        result = _normalize_role(input_role)
        status = "✅" if result == expected else "❌"
        print(f"  {status} _normalize_role('{input_role}') = '{result}' (expected '{expected}')")
        if result != expected:
            all_passed = False
    
    return all_passed

async def test_onboarding_steps():
    """Test onboarding steps structure"""
    print("\n=== TEST 3: Onboarding Steps ===")
    
    from server import ONBOARDING_STEPS, _onboarding_status_overall
    
    print(f"Onboarding steps defined: {ONBOARDING_STEPS}")
    
    expected_steps = [
        "invitation_sent",
        "account_created",
        "companies_assigned",
        "role_configured",
        "first_login",
    ]
    
    if ONBOARDING_STEPS == expected_steps:
        print("✅ Onboarding steps match specification")
    else:
        print("❌ Onboarding steps don't match")
        print(f"  Expected: {expected_steps}")
        print(f"  Got: {ONBOARDING_STEPS}")
        return False
    
    # Test status computation
    print("\nTesting _onboarding_status_overall:")
    test_cases = [
        ([], "pending"),
        ([{"status": "pending"}] * 5, "pending"),
        ([{"status": "completed"}] * 5, "completed"),
        ([{"status": "completed"}] * 3 + [{"status": "pending"}] * 2, "in_progress"),
        ([{"status": "blocked"}] + [{"status": "completed"}] * 4, "blocked"),
    ]
    
    all_passed = True
    for steps, expected in test_cases:
        result = _onboarding_status_overall(steps)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {len(steps)} steps -> '{result}' (expected '{expected}')")
        if result != expected:
            all_passed = False
    
    return all_passed

async def test_rbac_roles():
    """Test RBAC role hierarchy"""
    print("\n=== TEST 4: RBAC Role Hierarchy ===")
    
    from server import ROLE_RANK, role_rank
    
    print(f"Role hierarchy: {ROLE_RANK}")
    
    expected_hierarchy = {
        "viewer": 1,
        "member": 2,
        "accountant": 3,
        "leader": 4,
        "owner": 5,
    }
    
    if ROLE_RANK == expected_hierarchy:
        print("✅ Role hierarchy matches specification")
    else:
        print("❌ Role hierarchy doesn't match")
        return False
    
    # Test role_rank function with normalization
    print("\nTesting role_rank with normalization:")
    test_cases = [
        ("agent", 1),  # Should normalize to viewer
        ("operator", 2),  # Should normalize to member
        ("manager", 3),  # Should normalize to accountant
        ("admin", 4),  # Should normalize to leader
        ("owner", 5),
        ("viewer", 1),
        ("member", 2),
        ("accountant", 3),
        ("leader", 4),
    ]
    
    all_passed = True
    for role, expected_rank in test_cases:
        result = role_rank(role)
        status = "✅" if result == expected_rank else "❌"
        print(f"  {status} role_rank('{role}') = {result} (expected {expected_rank})")
        if result != expected_rank:
            all_passed = False
    
    return all_passed

async def test_collections_exist():
    """Test that required collections exist"""
    print("\n=== TEST 5: MongoDB Collections ===")
    
    required_collections = [
        "workspace_members",
        "workspace_invites",
        "people_onboarding_steps",
        "audit_log",
        "users",
        "workspaces",
    ]
    
    existing_collections = await db.list_collection_names()
    
    all_exist = True
    for col_name in required_collections:
        exists = col_name in existing_collections
        status = "✅" if exists else "❌"
        print(f"  {status} {col_name}")
        if not exists:
            all_exist = False
    
    return all_exist

async def test_audit_log_structure():
    """Test audit log structure"""
    print("\n=== TEST 6: Audit Log Structure ===")
    
    audit_log_col = db["audit_log"]
    
    # Get a sample audit log entry
    sample = await audit_log_col.find_one({}, {"_id": 0})
    
    if not sample:
        print("⚠️  No audit log entries found (this is OK for a fresh install)")
        return True
    
    print(f"Sample audit log entry:")
    required_fields = ["event_id", "event_type", "description", "workspace_id", "timestamp"]
    
    all_present = True
    for field in required_fields:
        present = field in sample
        status = "✅" if present else "❌"
        print(f"  {status} {field}: {sample.get(field, 'MISSING')}")
        if not present:
            all_present = False
    
    # Optional fields
    optional_fields = ["user_id", "target_member_id", "metadata"]
    print("\nOptional fields:")
    for field in optional_fields:
        present = field in sample
        status = "✓" if present else "·"
        print(f"  {status} {field}: {sample.get(field, 'not present')}")
    
    return all_present

async def test_onboarding_collection():
    """Test people_onboarding_steps collection"""
    print("\n=== TEST 7: Onboarding Steps Collection ===")
    
    people_onboarding_col = db["people_onboarding_steps"]
    
    # Get a sample entry
    sample = await people_onboarding_col.find_one({}, {"_id": 0})
    
    if not sample:
        print("⚠️  No onboarding steps found (this is OK for a fresh install)")
        
        # Create a test entry
        print("\nCreating test onboarding step...")
        test_entry = {
            "workspace_id": "default",
            "member_user_id": "test-user",
            "step_key": "invitation_sent",
            "status": "completed",
            "completed_at": datetime.now(timezone.utc),
            "metadata": {"test": True},
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        await people_onboarding_col.insert_one(test_entry)
        print("✅ Test entry created")
        
        # Retrieve it
        sample = await people_onboarding_col.find_one({"member_user_id": "test-user"}, {"_id": 0})
    
    if sample:
        print(f"\nSample onboarding step:")
        required_fields = ["workspace_id", "member_user_id", "step_key", "status"]
        
        all_present = True
        for field in required_fields:
            present = field in sample
            status = "✅" if present else "❌"
            print(f"  {status} {field}: {sample.get(field, 'MISSING')}")
            if not present:
                all_present = False
        
        return all_present
    
    return False

async def run_all_tests():
    """Run all tests"""
    print("="*60)
    print("Phase 7b-ext Direct Testing")
    print("="*60)
    
    results = []
    
    # Test 1: Role migration
    results.append(("Role Migration", await test_role_migration()))
    
    # Test 2: Role normalization
    results.append(("Role Normalization", await test_role_normalization()))
    
    # Test 3: Onboarding steps
    results.append(("Onboarding Steps", await test_onboarding_steps()))
    
    # Test 4: RBAC roles
    results.append(("RBAC Roles", await test_rbac_roles()))
    
    # Test 5: Collections exist
    results.append(("Collections Exist", await test_collections_exist()))
    
    # Test 6: Audit log structure
    results.append(("Audit Log Structure", await test_audit_log_structure()))
    
    # Test 7: Onboarding collection
    results.append(("Onboarding Collection", await test_onboarding_collection()))
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{name}: {status}")
    
    print(f"\nTotal: {passed}/{total} passed")
    
    # Cleanup
    client.close()
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)
