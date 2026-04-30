#!/usr/bin/env python3
"""
Check MongoDB for existing users and try to generate a test token
"""

import sys
import asyncio
sys.path.insert(0, '/app/backend')

from dotenv import load_dotenv
load_dotenv('/app/backend/.env')

from motor.motor_asyncio import AsyncIOMotorClient
import os

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "quantro_os")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
users_col = db["users"]
workspace_members_col = db["workspace_members"]

async def check_users():
    print("=" * 60)
    print("CHECKING MONGODB FOR EXISTING USERS")
    print("=" * 60)
    
    # Get all users
    users = await users_col.find({}, {"_id": 0}).to_list(100)
    print(f"\nFound {len(users)} user(s) in MongoDB:")
    
    for user in users[:10]:  # Show first 10
        print(f"\n  User ID: {user.get('user_id')}")
        print(f"  Email: {user.get('email')}")
        print(f"  Name: {user.get('name')}")
        print(f"  Auth Provider: {user.get('auth_provider', 'N/A')}")
        print(f"  Current Workspace: {user.get('current_workspace_id', 'N/A')}")
        
        # Check workspace memberships
        memberships = await workspace_members_col.find(
            {"user_id": user.get('user_id')},
            {"_id": 0, "workspace_id": 1, "role": 1}
        ).to_list(10)
        
        if memberships:
            print(f"  Workspace Memberships:")
            for m in memberships:
                print(f"    - {m.get('workspace_id')}: {m.get('role')}")
    
    client.close()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total users: {len(users)}")
    print("\nNote: To test authenticated endpoints, we need a valid Supabase JWT.")
    print("Since Supabase login is unreliable, we'll test what we can without auth.")

if __name__ == "__main__":
    asyncio.run(check_users())
