import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.database import database, save_db, SessionLocal
from core.models import Device

def clean_ghost_media():
    print("=== Cleaning Ghost Media Entries with No Files on Disk ===")
    if not SessionLocal:
        print("Error: No database connection")
        return

    for device_id in list(database.keys()):
        db_media = database.get(device_id, {}).get("media", {})
        if not isinstance(db_media, dict):
            continue

        removed = []
        for k in list(db_media.keys()):
            item = db_media[k]
            if not isinstance(item, dict):
                continue
            fn = item.get("name", "")
            if not fn:
                continue

            candidates = [
                os.path.join("media", device_id, fn),
                os.path.join("media", device_id, "voice", fn),
                os.path.join("media", device_id, "photos", fn),
                os.path.join("media", device_id, "videos", fn)
            ]
            if not any(os.path.isfile(p) for p in candidates):
                db_media.pop(k, None)
                removed.append(fn)

        if removed:
            print(f"Device {device_id}: Pruned {len(removed)} ghost media items: {removed}")
            save_db(device_id)
        else:
            print(f"Device {device_id}: No ghost media items found.")

    print("\nVerification in PostgreSQL:")
    with SessionLocal() as session:
        for dev in session.query(Device).all():
            m_keys = list((dev.media or {}).keys())
            print(f"  Device {dev.device_id}: {len(m_keys)} valid media entries in PostgreSQL.")

if __name__ == "__main__":
    clean_ghost_media()
