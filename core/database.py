import os
import json
from config import DB_FILE, USERS_DB_FILE, BLACKLIST

database = {}
data_cache = {}  # RAM Cache

# Connected clients map: device_id -> socket session ID (sid)
connected_devices = {}
sid_to_device = {}
connected_device_licenses = {}

users_database = {"users": {}, "licenses": {}, "reports": [], "system_policy": {}}

def load_db():
    global database
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                for b in BLACKLIST:
                    for k in list(loaded.keys()):
                        if b in k.lower():
                            del loaded[k]
                database.clear()
                database.update(loaded)
        except Exception:
            database.clear()
    else:
        database.clear()

def save_db():
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def load_users_db():
    global users_database
    if os.path.exists(USERS_DB_FILE):
        try:
            with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if "users" not in loaded: loaded["users"] = {}
                if "licenses" not in loaded: loaded["licenses"] = {}
                if "reports" not in loaded: loaded["reports"] = []
                if "system_policy" not in loaded:
                    loaded["system_policy"] = {
                        "maintenance_mode": False,
                        "maintenance_message": "Scheduled updates are in progress. CyberEye console will be back online shortly.",
                        "maintenance_until": 0
                    }
                users_database.clear()
                users_database.update(loaded)
        except Exception:
            users_database.clear()
            users_database.update({"users": {}, "licenses": {}, "reports": [], "system_policy": {}})
    else:
        users_database.clear()
        users_database.update({
            "users": {},
            "licenses": {},
            "reports": [],
            "system_policy": {
                "maintenance_mode": False,
                "maintenance_message": "Scheduled updates are in progress. CyberEye console will be back online shortly.",
                "maintenance_until": 0
            }
        })
        save_users_db()

def save_users_db():
    try:
        with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_database, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# Initialize databases on import
load_db()
load_users_db()
