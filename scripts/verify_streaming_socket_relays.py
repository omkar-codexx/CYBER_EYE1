import os
import sys
import time
import requests
import socketio

print("=========================================================")
print(" VERIFICATION SUITE: REAL-TIME STREAMING SOCKET RELAYS  ")
print("=========================================================")

received_events = []

# 1. Authenticate and Connect Web Dashboard Client on Port 8801
print("\n--- 1. Authenticating Dashboard User & Connecting to http://127.0.0.1:8801 ---")
session = requests.Session()
login_res = session.post('http://127.0.0.1:8801/login', json={'username': 'test', 'password': 'test', 'license_key': 'CYBER-3ZPY-J99Y-86I1-TNPF'})
assert login_res.status_code == 200, f"Dashboard login failed: {login_res.text}"
print("Dashboard authenticated as 'test': OK")

web_client = socketio.Client(http_session=session)

@web_client.on('camera_frame_relay')
def on_camera_frame(data):
    print(f"Web client received 'camera_frame_relay': Bat {data.get('battery')}%")
    received_events.append(('camera_frame_relay', data))

@web_client.on('mirror_frame_relay')
def on_mirror_frame(data):
    print(f"Web client received 'mirror_frame_relay'")
    received_events.append(('mirror_frame_relay', data))

@web_client.on('live_audio_relay')
def on_audio_relay(data):
    print(f"Web client received 'live_audio_relay': {data.get('url')}")
    received_events.append(('live_audio_relay', data))

web_client.connect('http://127.0.0.1:8801')
web_client.emit('join_device_room', {'device_id': 'V2238_C323'})
print("Web client connected and joined room 'V2238_C323': OK")
time.sleep(1)

# 2. Connect Hardware Device on Gateway Port 5001 with query parameters
print("\n--- 2. Connecting Hardware Client to http://127.0.0.1:5001 ---")
hw_client = socketio.Client()
hw_client.connect(
    'http://127.0.0.1:5001/?device_id=V2238_C323&license_key=CYBER-3ZPY-J99Y-86I1-TNPF&model=V2238'
)
print("Hardware client connected to Port 5001: OK")
time.sleep(1)

# 3. Emit Camera Frame from HW
print("\n--- 3. Emitting 'camera_frame' from Hardware ---")
hw_client.emit('camera_frame', {
    'frame': 'dummy_camera_base64_data',
    'battery': '88'
})
time.sleep(1)

# 4. Emit Mirror Frame from HW
print("\n--- 4. Emitting 'mirror_frame' from Hardware ---")
hw_client.emit('mirror_frame', {
    'frame': 'dummy_mirror_base64_data',
    'battery': '88'
})
time.sleep(1)

# 5. Emit Audio Frame from HW
print("\n--- 5. Emitting 'audio_frame' from Hardware ---")
hw_client.emit('audio_frame', {
    'url': '/api/media/stream/V2238_C323/live_chunk_1.mp3'
})
time.sleep(1)

# Verification
event_names = [e[0] for e in received_events]
print(f"\nAll received events on Web Dashboard: {event_names}")
assert 'camera_frame_relay' in event_names, "camera_frame_relay was not received"
assert 'mirror_frame_relay' in event_names, "mirror_frame_relay was not received"
assert 'live_audio_relay' in event_names, "live_audio_relay was not received"

hw_client.disconnect()
web_client.disconnect()

print("\n=========================================================")
print(" ALL 3 REAL-TIME STREAMING RELAYS VERIFIED SUCCESSFULLY! ")
print("=========================================================")
