import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app
from extensions import socketio

def test_routes():
    print("=== Testing Route Map ===")
    rules = [rule.rule for rule in app.url_map.iter_rules()]
    print(f"Total registered routes: {len(rules)}")
    
    expected_critical_routes = [
        '/', '/login', '/logout', '/check_auth', '/admin/login', '/admin/logout',
        '/introl', '/dashboard', '/keylogs', '/file_manager', '/social_media',
        '/location_3d', '/route_history', '/geofencing', '/ai_chatbot',
        '/Screen_mirroring.html', '/Live_Camera.html', '/Live_Audio.html',
        '/admin', '/introl.mp4', '/logo.png', '/logo1.png',
        '/api/devices', '/api/device/<device_id>/data',
        '/api/device/<device_id>/ai_context', '/api/device/<device_id>/ai_chat',
        '/api/device/<device_id>/action', '/api/device/<device_id>/location',
        '/api/admin/list_users_keys', '/api/admin/create_user',
        '/api/admin/generate_license', '/api/admin/apply_maintenance',
        '/api/network_status', '/api/user/details'
    ]
    
    missing = []
    for r in expected_critical_routes:
        if r not in rules:
            missing.append(r)
            
    if missing:
        print(f"FAILED: Missing routes: {missing}")
        sys.exit(1)
    else:
        print("SUCCESS: All critical routes verified!")

def test_client_access():
    print("\n=== Testing Flask Test Client ===")
    client = app.test_client()
    
    # 1. Unauthenticated root redirects to /login
    resp = client.get('/', follow_redirects=False)
    assert resp.status_code in [301, 302], f"Expected redirect, got {resp.status_code}"
    print("1. Root redirect: OK")
    
    # 2. Login page loads
    resp = client.get('/login')
    assert resp.status_code == 200, f"Expected 200 for /login, got {resp.status_code}"
    print("2. /login page: OK")
    
    # 3. Check auth returns false when logged out
    resp = client.get('/check_auth')
    assert resp.status_code == 200
    assert resp.json.get('authorized') is False
    print("3. /check_auth logged-out: OK")
    
    # 4. Media routes serve
    resp = client.get('/logo.png')
    assert resp.status_code == 200
    print("4. /logo.png serve: OK")
    
    print("\nALL SYSTEM VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_routes()
    test_client_access()
