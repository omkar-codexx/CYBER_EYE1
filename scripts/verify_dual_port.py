import os
import sys
import io
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app as web_app

from gateway import gateway_app
from extensions import socketio as web_sio, gateway_socketio as gw_sio
from core.gateway_auth import generate_famx_token, verify_famx_token

print("=== 1. Testing famX Token Generation & Verification ===")
dev_id = "DEV_FAMX_001"
token = generate_famx_token(dev_id)
print(f"Generated token for {dev_id}: {token}")
assert token.startswith("famX_")
assert verify_famx_token(dev_id, token) is True
assert verify_famx_token("DEV_OTHER", token) is False
assert verify_famx_token(dev_id, "invalid_token") is False
print("famX Token Cryptographic Validation: OK")

print("\n=== 2. Testing Port Isolation (Web vs Gateway) ===")
web_client = web_app.test_client()
gw_client = gateway_app.test_client()

# Web Dashboard should serve /login and /
web_resp = web_client.get('/login')
assert web_resp.status_code == 200, f"Web expected 200, got {web_resp.status_code}"
print("Web Server: /login accessible: OK")

# Gateway should NOT serve /login or /admin (Shielded from hardware)
gw_login = gw_client.get('/login')
assert gw_login.status_code == 404, f"Gateway expected 404 for /login, got {gw_login.status_code}"
gw_admin = gw_client.get('/admin')
assert gw_admin.status_code == 404, f"Gateway expected 404 for /admin, got {gw_admin.status_code}"
print("famX Gateway: Web Dashboard & Admin shielded (returns 404): OK")

# Gateway root should return JSON service status
gw_status = gw_client.get('/')
assert gw_status.status_code == 200
json_data = gw_status.get_json()
assert json_data.get("service") == "famX Device Gateway"
assert json_data.get("status") == "online"
print("famX Gateway: Health check JSON: OK")

print("\n=== 3. Testing Hardware Ingestion on famX Gateway ===")
# Upload info telemetry with famX token
file_data = io.BytesIO(b"model: SensorX\nandroid: 12\n")
resp = gw_client.post(
    f'/api/device/{dev_id}/upload_media',
    data={'file': (file_data, 'info.txt'), 'category': 'info'},
    headers={'X-famX-Token': token}
)
assert resp.status_code == 200, f"Upload expected 200, got {resp.status_code}: {resp.data}"
assert resp.get_json().get("success") is True
print("famX Gateway: Device telemetry upload with famX token: OK")

print("\n=== 4. Testing Cross-Server Real-Time Socket Relay ===")
# Connect web dashboard client to Web SocketIO (Port 8800)
sock_web = web_sio.test_client(web_app, flask_test_client=web_client)

# Manually join device room on web socket to listen for relays
from flask_socketio import join_room
@web_sio.on('_test_join')
def _on_test_join(d):
    join_room(d['device_id'])
sock_web.emit('_test_join', {'device_id': dev_id})

# Connect device client to Gateway SocketIO (Port 5000)
sock_dev = gw_sio.test_client(gateway_app, query_string=f"device_id={dev_id}&token={token}")

# Send camera frame from device on Port 5000
test_frame = "base64_telemetry_frame_data_xyz"
sock_dev.emit('camera_frame', {'frame': test_frame})

# Check if Web Dashboard client received camera frame relay
web_events = sock_web.get_received()
relays = [e for e in web_events if e['name'] == 'camera_frame_relay']
assert len(relays) > 0, f"Expected camera_frame_relay on web client, got: {web_events}"
assert relays[0]['args'][0]['frame'] == test_frame
print("Cross-Port Live Telemetry Relay (Port 5000 -> Port 8800): OK")

print("\n=======================================================")
print(" ALL DUAL-PORT & famX GATEWAY VERIFICATIONS PASSED! ")
print("=======================================================")
