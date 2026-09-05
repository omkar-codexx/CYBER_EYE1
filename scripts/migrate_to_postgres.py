import os
import sys
import json
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import DB_FILE, USERS_DB_FILE, DATABASE_URL, REDIS_URL
from core.database import (
    SessionLocal, redis_client, database, users_database,
    save_db, save_users_db
)
from core.models import User, License, Device, Report, SystemPolicy

def run_migration():
    print(f"[Migration] DATABASE_URL: {DATABASE_URL}")
    print(f"[Migration] REDIS_URL: {REDIS_URL}")
    
    if not SessionLocal:
        print("[Migration] ERROR: SessionLocal is None. Cannot connect to PostgreSQL.")
        return False

    # 1. Sync Users, Licenses, Reports, Policy
    print("\n--- 1. Migrating Users & Licenses ---")
    if os.path.exists(USERS_DB_FILE) and os.path.isfile(USERS_DB_FILE):
        with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
            users_data = json.load(f)
            users_database.clear()
            users_database.update(users_data)
            users_database.sync_to_postgres()
            print(f"Synced {len(users_database.get('users', {}))} users and {len(users_database.get('licenses', {}))} licenses to PostgreSQL.")

    # 2. Sync Devices
    print("\n--- 2. Migrating Devices ---")
    if os.path.exists(DB_FILE) and os.path.isfile(DB_FILE):
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            devices_data = json.load(f)
            database.clear()
            database.update(devices_data)
            database.sync_all_to_postgres()
            print(f"Synced {len(devices_data)} devices to PostgreSQL.")

    # 3. Verify in PostgreSQL
    print("\n--- 3. Verifying in PostgreSQL ---")
    with SessionLocal() as session:
        user_count = session.query(User).count()
        lic_count = session.query(License).count()
        dev_count = session.query(Device).count()
        rep_count = session.query(Report).count()
        print(f"PostgreSQL counts: Users={user_count}, Licenses={lic_count}, Devices={dev_count}, Reports={rep_count}")
        
        for dev in session.query(Device).all():
            print(f"  Device: {dev.device_id}, License: {dev.license_key}, Last Seen: {dev.last_seen}, Extra Data Keys: {list((dev.extra_data or {}).keys())}")

    # 4. Verify Redis Cache
    print("\n--- 4. Verifying Redis Cache ---")
    if redis_client:
        try:
            keys = redis_client.keys("device:*")
            print(f"Redis keys created: {len(keys)}")
            for k in keys[:10]:
                val = redis_client.get(k)
                print(f"  Redis key: {k} -> {val}")
        except Exception as e:
            print(f"Redis error: {e}")
    else:
        print("Redis client not initialized.")

    print("\n[Migration] MIGRATION COMPLETED SUCCESSFULLY!")
    return True

if __name__ == "__main__":
    run_migration()
