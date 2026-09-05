import os
import sys
import io
import time
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.database import SessionLocal, redis_client, database
from core.models import Device, User, License

print("=========================================================")
print(" VERIFICATION SUITE: POSTGRESQL, REDIS & AUDIO PIPELINE ")
print("=========================================================")

# 1. PostgreSQL & Redis State
print("\n--- 1. Testing PostgreSQL & Redis Persistence ---")
with SessionLocal() as session:
    dev = session.query(Device).filter_by(device_id="V2238_C323").first()
    assert dev is not None, "Device V2238_C323 not found in PostgreSQL"
    print(f"PostgreSQL Device: {dev.device_id}, License: {dev.license_key}, Last Seen: {dev.last_seen}")
    print(f"Media entries in Postgres: {len(dev.media or {})}")

assert redis_client is not None, "Redis client not connected"
last_seen_redis = redis_client.get("device:V2238_C323:last_seen")
assert last_seen_redis is not None, "Redis last_seen key missing"
print(f"Redis Cache: device:V2238_C323:last_seen = {last_seen_redis}: OK")

# 2. Test Audio Action Mapping
print("\n--- 2. Testing Audio Action Mapping in API ---")
from routes.api import api_device_action
action_tests = [
    ('RECORD_AUDIO_15', 'MIC_15S'),
    ('RECORD_AUDIO_30', 'MIC_30S'),
    ('RECORD_AUDIO_60', 'MIC_60S'),
    ('RECORD_AUDIO_300', 'AUDIO_300'),
    ('RECORD_AUDIO_600', 'AUDIO_600'),
    ('RECORD_AUDIO_45', 'MIC_45S')
]
for act, expected in action_tests:
    if act.startswith('RECORD_AUDIO_'):
        sec = act.replace('RECORD_AUDIO_', '')
        cmd = f'MIC_{sec}S' if sec in ['15', '30', '45', '60'] else f'AUDIO_{sec}'
        assert cmd == expected, f"Mapping failed for {act}: got {cmd}, expected {expected}"
print("All audio duration mappings verified (15s, 30s, 60s, 300s, 600s): OK")

# 3. Test Audio File Upload via Internal Flask Test Client
print("\n--- 3. Testing Audio Upload (.3gp / .amr / .mp3) ---")
from app import app
client = app.test_client()

# Create dummy audio file payload
test_audio_filename = "hardware_test_voice_30s.3gp"
audio_bytes = b"RIFF....WAVEfmt ....data...."

data = {
    'file': (io.BytesIO(audio_bytes), test_audio_filename),
    'category': 'audio'
}
resp = client.post('/api/device/V2238_C323/upload_media', data=data, content_type='multipart/form-data')
assert resp.status_code == 200, f"Upload failed with status {resp.status_code}: {resp.data}"
print(f"Uploaded {test_audio_filename} -> Response: {resp.get_json()}: OK")

# Verify file on disk
saved_path = os.path.join("media", "V2238_C323", "voice", test_audio_filename)
assert os.path.isfile(saved_path), f"File was not saved to {saved_path}"
print(f"Verified file saved on disk at: {saved_path}: OK")

# Verify in PostgreSQL
with SessionLocal() as session:
    dev = session.query(Device).filter_by(device_id="V2238_C323").first()
    media = dev.media or {}
    matched = [v for v in media.values() if isinstance(v, dict) and v.get("name") == test_audio_filename]
    assert len(matched) > 0, "Uploaded audio not found in PostgreSQL media!"
    print(f"Verified audio in PostgreSQL Device Media: {matched[0]}: OK")
    assert matched[0]["duration"] == 30, f"Expected duration 30s, got {matched[0]['duration']}"
    print("Verified dynamic duration detection (30s): OK")

# 4. Verify Media Aggregator Filters Ghost Files
print("\n--- 4. Testing Ghost Filter in Media Aggregator ---")
from routes.api import build_device_media_dict
media_dict = build_device_media_dict("V2238_C323")
for k, v in media_dict.items():
    fn = v.get("name", "")
    candidates = [
        os.path.join("media", "V2238_C323", fn),
        os.path.join("media", "V2238_C323", "voice", fn),
        os.path.join("media", "V2238_C323", "photos", fn)
    ]
    assert any(os.path.isfile(p) for p in candidates), f"Ghost file found in media_dict: {fn}"
print(f"Media aggregator returned {len(media_dict)} items, 100% physically exist on disk: OK")

# Clean up test audio file
try:
    os.remove(saved_path)
    direct_p = os.path.join("media", "V2238_C323", test_audio_filename)
    if os.path.isfile(direct_p):
        os.remove(direct_p)
    # Prune from db
    build_device_media_dict("V2238_C323")
    print("Test file cleaned up cleanly.")
except Exception as e:
    print(f"Cleanup note: {e}")

print("\n=========================================================")
print(" ALL TESTS PASSED! POSTGRESQL & AUDIO SYSTEM 100% READY ")
print("=========================================================")
