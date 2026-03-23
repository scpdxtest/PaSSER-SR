#!/usr/bin/env python3
"""
PaSSER-SR: Import Users Script
==============================
Imports users from JSON configuration into MongoDB.
Supports multiple roles per user (one Antelope account can have multiple roles).

Usage:
    python import_users.py --users users.json --mongo mongodb://localhost:27017 --db passer_sr

Arguments:
    --users     Path to users JSON file (default: users.json)
    --mongo     MongoDB connection string (default: mongodb://localhost:27017)
    --db        Database name (default: passer_sr)

JSON Format:
{
  "users": [
    {
      "antelope_account": "screener1",
      "display_name": "Screener One",
      "email": "screener1@example.com",
      "roles": ["screener", "resolver"],
      "active": true
    }
  ]
}

Author: PaSSER-SR Team
Date: January 2026
"""

import argparse
import json
import re
import sys
from datetime import datetime
from typing import List, Dict, Any

try:
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure, DuplicateKeyError
except ImportError:
    print("Error: pymongo is required. Install with: pip install pymongo")
    sys.exit(1)


# Valid roles
VALID_ROLES = {"screener", "resolver", "admin"}

# Antelope account name pattern: a-z, 1-5, dots, max 12 characters
ANTELOPE_ACCOUNT_PATTERN = re.compile(r'^[a-z1-5.]{1,12}$')


def validate_antelope_account(account: str) -> bool:
    """Validate Antelope account name format."""
    if not account:
        return False
    return bool(ANTELOPE_ACCOUNT_PATTERN.match(account))


def validate_roles(roles: Any) -> tuple:
    """
    Validate roles field.
    Returns (is_valid, normalized_roles, error_message)
    """
    # Handle legacy single role format (string)
    if isinstance(roles, str):
        roles = [roles]
    
    if not isinstance(roles, list):
        return False, [], "roles must be a list"
    
    if len(roles) == 0:
        return False, [], "roles cannot be empty"
    
    # Normalize and validate each role
    normalized = []
    for role in roles:
        if not isinstance(role, str):
            return False, [], f"each role must be a string, got {type(role)}"
        role_lower = role.lower().strip()
        if role_lower not in VALID_ROLES:
            return False, [], f"invalid role '{role}'. Valid roles: {VALID_ROLES}"
        if role_lower not in normalized:
            normalized.append(role_lower)
    
    return True, normalized, None


def validate_user(user: Dict[str, Any], index: int) -> tuple:
    """
    Validate a single user record.
    Returns (is_valid, error_message)
    """
    # Required fields
    if "antelope_account" not in user:
        return False, f"User {index}: missing 'antelope_account'"
    
    if "roles" not in user and "role" not in user:
        return False, f"User {index}: missing 'roles'"
    
    # Validate antelope_account
    account = user["antelope_account"]
    if not validate_antelope_account(account):
        return False, f"User {index}: invalid antelope_account '{account}'. Must be 1-12 chars, lowercase a-z, digits 1-5, dots only."
    
    # Validate roles (support both 'roles' array and legacy 'role' string)
    roles_field = user.get("roles", user.get("role"))
    is_valid, normalized_roles, error = validate_roles(roles_field)
    if not is_valid:
        return False, f"User {index} ({account}): {error}"
    
    # Store normalized roles back
    user["roles"] = normalized_roles
    
    return True, None


def import_users(users_file: str, mongo_uri: str, db_name: str) -> Dict[str, int]:
    """
    Import users from JSON file to MongoDB.
    Returns statistics dict with counts.
    """
    stats = {
        "total": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
        "skipped": 0
    }
    
    # Load JSON file
    print(f"\n📄 Loading users from: {users_file}")
    try:
        with open(users_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {users_file}")
        return stats
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON: {e}")
        return stats
    
    # Extract users array
    users = data.get("users", [])
    if not users:
        print("❌ Error: No users found in JSON file")
        return stats
    
    stats["total"] = len(users)
    print(f"   Found {len(users)} users")
    
    # Validate all users first
    print("\n🔍 Validating users...")
    valid_users = []
    for i, user in enumerate(users):
        is_valid, error = validate_user(user, i + 1)
        if not is_valid:
            print(f"   ❌ {error}")
            stats["errors"] += 1
        else:
            valid_users.append(user)
            print(f"   ✓ {user['antelope_account']}: roles={user['roles']}")
    
    if not valid_users:
        print("\n❌ No valid users to import")
        return stats
    
    # Connect to MongoDB
    print(f"\n🔌 Connecting to MongoDB: {mongo_uri}")
    try:
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        print("   ✓ Connected")
    except ConnectionFailure as e:
        print(f"   ❌ Connection failed: {e}")
        return stats
    
    db = client[db_name]
    collection = db["users"]
    
    # Create unique index on antelope_account
    print(f"\n📁 Database: {db_name}, Collection: users")
    collection.create_index("antelope_account", unique=True)
    print("   ✓ Index created on 'antelope_account'")
    
    # Import users
    print("\n📥 Importing users...")
    now = datetime.utcnow()
    
    for user in valid_users:
        account = user["antelope_account"]
        
        # Prepare document
        doc = {
            "antelope_account": account,
            "display_name": user.get("display_name", account),
            "email": user.get("email", ""),
            "roles": user["roles"],
            "active": user.get("active", True),
            "updated_at": now
        }
        
        try:
            # Upsert: update if exists, insert if not
            result = collection.update_one(
                {"antelope_account": account},
                {
                    "$set": doc,
                    "$setOnInsert": {"created_at": now}
                },
                upsert=True
            )
            
            if result.upserted_id:
                print(f"   ✓ Inserted: {account} (roles: {user['roles']})")
                stats["inserted"] += 1
            elif result.modified_count > 0:
                print(f"   ↻ Updated: {account} (roles: {user['roles']})")
                stats["updated"] += 1
            else:
                print(f"   - Unchanged: {account}")
                stats["skipped"] += 1
                
        except Exception as e:
            print(f"   ❌ Error importing {account}: {e}")
            stats["errors"] += 1
    
    # Close connection
    client.close()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Import Summary:")
    print(f"   Total in file:  {stats['total']}")
    print(f"   Inserted:       {stats['inserted']}")
    print(f"   Updated:        {stats['updated']}")
    print(f"   Unchanged:      {stats['skipped']}")
    print(f"   Errors:         {stats['errors']}")
    print("=" * 50)
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Import PaSSER-SR users from JSON to MongoDB"
    )
    parser.add_argument(
        "--users",
        type=str,
        default="users.json",
        help="Path to users JSON file (default: users.json)"
    )
    parser.add_argument(
        "--mongo",
        type=str,
        default="mongodb://localhost:27017",
        help="MongoDB connection string (default: mongodb://localhost:27017)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default="passer_sr",
        help="Database name (default: passer_sr)"
    )
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("PaSSER-SR: Import Users")
    print("=" * 50)
    
    stats = import_users(args.users, args.mongo, args.db)
    
    # Exit code based on errors
    if stats["errors"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
