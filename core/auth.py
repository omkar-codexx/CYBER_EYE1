import hashlib
from functools import wraps
from flask import request, jsonify, redirect, session, render_template
from config import ADMIN_EMAIL, ADMIN_DEFAULT_PASSWORD
from core.database import users_database, database

def hash_password(password):
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def check_password(password, hashed):
    return hash_password(password) == hashed

ADMIN_PASSWORD_HASH = hash_password(ADMIN_DEFAULT_PASSWORD)

def check_maintenance_policy():
    policy = users_database.get("system_policy", {})
    if policy.get("maintenance_mode", False):
        allowed_paths = [
            '/admin', '/admin/login', '/admin/logout', '/login', '/logout', '/static/',
            '/api/admin/apply_maintenance', '/api/admin/bulk_op', '/api/admin/list_users_keys',
            '/api/admin/create_user', '/api/admin/generate_license', '/api/admin/toggle_device_visibility'
        ]
        path = request.path
        is_allowed = any(path.startswith(p) for p in allowed_paths)
        if not is_allowed and not session.get('admin_logged', False):
            if request.is_json or path.startswith('/api/'):
                return jsonify({'error': 'System maintenance mode is active.', 'code': 503}), 503
            return render_template('maintenance.html', message=policy.get("maintenance_message"))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized', 'code': 401}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged' not in session:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Unauthorized', 'code': 401}), 401
            return redirect('/admin/login')
        return f(*args, **kwargs)
    return decorated_function

def has_device_access(username, device_id):
    if not username:
        return False
    if username == ADMIN_EMAIL:
        return True
        
    user_data = users_database.get("users", {}).get(username, {})
    hidden_devices = user_data.get("hidden_devices", [])
    if device_id in hidden_devices:
        return False
        
    # Get all active licenses assigned to this username
    user_licenses = [
        k for k, v in users_database.get("licenses", {}).items()
        if v.get("assigned_to") == username and v.get("is_active", True)
    ]
    
    # Get device license key from persistent database
    device_data = database.get(device_id, {})
    device_license = device_data.get("license_key")
    
    # STRICT LICENSE MATCHING: Device must have a matching license key to be displayed
    return (device_license in user_licenses)
