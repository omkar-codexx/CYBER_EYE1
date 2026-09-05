import time
import random
import string
from flask import Blueprint, request, jsonify
from extensions import socketio
from core.auth import admin_required, hash_password
from core.database import (
    users_database, database, connected_devices,
    connected_device_licenses, save_users_db
)

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/api/admin/list_users_keys', methods=['GET'], endpoint='admin_list_users_keys')
@admin_required
def admin_list_users_keys():
    users_list = []
    for username, u_info in users_database.get("users", {}).items():
        user_licenses = []
        for l_key, l_info in users_database.get("licenses", {}).items():
            if l_info.get("assigned_to") == username:
                user_licenses.append({
                    "key": l_key,
                    "expires_at": l_info.get("expires_at", 0),
                    "is_active": l_info.get("is_active", True)
                })
        
        device_details = []
        for dev_id in u_info.get("devices", []):
            is_online = dev_id in connected_devices
            is_hidden = dev_id in u_info.get("hidden_devices", [])
            model = database.get(dev_id, {}).get("info", {}).get("model", dev_id)
            device_details.append({
                "id": dev_id,
                "model": model,
                "online": is_online,
                "hidden": is_hidden
            })
            
        users_list.append({
            "username": username,
            "plain_password": u_info.get("plain_password", "******"),
            "last_seen": u_info.get("last_seen", 0),
            "licenses": user_licenses,
            "devices": device_details
        })
            
    return jsonify({
        "success": True,
        "users": users_list,
        "system_policy": users_database.get("system_policy", {})
    })

@admin_bp.route('/api/admin/create_user', methods=['POST'], endpoint='admin_create_user')
@admin_required
def admin_create_user():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({"success": False, "error": "Username and password are required"}), 400
        
    if username in users_database.get("users", {}):
        return jsonify({"success": False, "error": "User already exists"}), 400
        
    users_database["users"][username] = {
        "password_hash": hash_password(password),
        "plain_password": password,
        "role": "user",
        "devices": [],
        "hidden_devices": []
    }
    save_users_db()
    return jsonify({"success": True, "message": "User created successfully"})

@admin_bp.route('/api/admin/delete_user', methods=['POST'], endpoint='admin_delete_user')
@admin_required
def admin_delete_user():
    data = request.json or {}
    username = data.get('username', '').strip()
    
    if not username:
        return jsonify({"success": False, "error": "Username is required"}), 400
        
    if username not in users_database.get("users", {}):
        return jsonify({"success": False, "error": "User not found"}), 404
        
    keys_to_del = [k for k, v in users_database.get("licenses", {}).items() if v.get("assigned_to") == username]
    for k in keys_to_del:
        users_database["licenses"].pop(k, None)
        
    users_database["users"].pop(username, None)
    save_users_db()
    return jsonify({"success": True, "message": f"User '{username}' and associated licenses deleted permanently."})

@admin_bp.route('/api/admin/generate_license', methods=['POST'], endpoint='admin_generate_license')
@admin_required
def admin_generate_license():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    license_key = data.get('license_key', '').strip()
    duration_days = data.get('duration_days')
    
    if not username:
        return jsonify({"success": False, "error": "Username is required"}), 400
        
    user_info = users_database.get("users", {}).get(username)
    if not user_info:
        if not password:
            return jsonify({"success": False, "error": "Password is required for new user creation"}), 400
        users_database["users"][username] = {
            "password_hash": hash_password(password),
            "plain_password": password,
            "role": "user",
            "devices": [],
            "hidden_devices": []
        }
        user_info = users_database["users"][username]
    else:
        if password:
            user_info["password_hash"] = hash_password(password)
            user_info["plain_password"] = password

    if not license_key:
        existing_keys = [k for k, v in users_database.get("licenses", {}).items() if v.get("assigned_to") == username]
        if existing_keys:
            license_key = existing_keys[0]
        else:
            chars = string.ascii_uppercase + string.digits
            part1 = ''.join(random.choice(chars) for _ in range(4))
            part2 = ''.join(random.choice(chars) for _ in range(4))
            part3 = ''.join(random.choice(chars) for _ in range(4))
            part4 = ''.join(random.choice(chars) for _ in range(4))
            license_key = f"CYBER-{part1}-{part2}-{part3}-{part4}"

    lic_info = users_database.get("licenses", {}).get(license_key)
    current_ts = int(time.time())

    if str(duration_days).startswith("+"):
        days_to_add = int(str(duration_days).replace("+", "").replace("d", "").strip())
        if lic_info:
            base_exp = max(lic_info.get("expires_at", current_ts), current_ts)
        else:
            base_exp = current_ts
        expires_at = base_exp + (days_to_add * 86400)
    else:
        try:
            days = int(duration_days)
        except Exception:
            days = 30
        expires_at = current_ts + (days * 86400)

    old_keys = [k for k, v in users_database.get("licenses", {}).items() if v.get("assigned_to") == username and k != license_key]
    for k in old_keys:
        users_database["licenses"].pop(k, None)

    created_ts = lic_info.get("created_at", current_ts) if lic_info else current_ts
    users_database["licenses"][license_key] = {
        "assigned_to": username,
        "expires_at": expires_at,
        "is_active": True,
        "created_at": created_ts
    }
    
    for dev_id, l_key in list(connected_device_licenses.items()):
        if l_key == license_key:
            if "devices" not in users_database["users"][username]:
                users_database["users"][username]["devices"] = []
            if dev_id not in users_database["users"][username]["devices"]:
                users_database["users"][username]["devices"].append(dev_id)
                print(f"[RBAC] Auto-mapped already connected device {dev_id} to user {username} on key save")
                
    save_users_db()
    return jsonify({
        "success": True, 
        "message": "User and license updated successfully",
        "license_key": license_key, 
        "expires_at": expires_at
    })

@admin_bp.route('/api/admin/toggle_license_active', methods=['POST'], endpoint='admin_toggle_license_active')
@admin_required
def admin_toggle_license_active():
    data = request.json or {}
    username = data.get('username', '').strip()
    is_active = data.get('is_active', True)
    
    if not username:
        return jsonify({"success": False, "error": "Username is required"}), 400
        
    found = False
    for l_key, l_info in users_database.get("licenses", {}).items():
        if l_info.get("assigned_to") == username:
            l_info["is_active"] = is_active
            found = True
            
    if not found:
        return jsonify({"success": False, "error": "No licenses found for this user"}), 404
        
    save_users_db()
    action = "activated" if is_active else "suspended"
    return jsonify({"success": True, "message": f"License successfully {action}."})

@admin_bp.route('/api/admin/apply_maintenance', methods=['POST'], endpoint='admin_apply_maintenance')
@admin_required
def admin_apply_maintenance():
    data = request.json or {}
    enabled = data.get('enabled', False)
    message = data.get('message', '').strip()
    
    policy = users_database.get("system_policy", {})
    policy["maintenance_mode"] = enabled
    if message:
        policy["maintenance_message"] = message
        
    users_database["system_policy"] = policy
    save_users_db()
    
    if enabled:
        socketio.emit('system_maintenance', {"message": policy["maintenance_message"]})
    else:
        socketio.emit('maintenance_end', {})
        
    return jsonify({"success": True, "message": "System policy updated successfully"})

@admin_bp.route('/api/admin/bulk_op', methods=['POST'], endpoint='admin_bulk_op')
@admin_required
def admin_bulk_op():
    action = request.json.get('action')
    if not action:
        return jsonify({"success": False, "error": "Action is required"}), 400
        
    current_ts = int(time.time())
    
    if action == "force_logout":
        socketio.emit('force_logout_all', {})
        return jsonify({"success": True, "message": "Force logout broadcast sent."})
        
    elif action == "extend_all":
        for l_key, l_info in users_database.get("licenses", {}).items():
            base_exp = max(l_info.get("expires_at", current_ts), current_ts)
            l_info["expires_at"] = base_exp + (7 * 86400)
        save_users_db()
        return jsonify({"success": True, "message": "All licenses extended by 7 days."})
        
    elif action == "suspend_all":
        for l_key, l_info in users_database.get("licenses", {}).items():
            l_info["is_active"] = False
        save_users_db()
        return jsonify({"success": True, "message": "All licenses suspended."})
        
    elif action == "activate_all":
        for l_key, l_info in users_database.get("licenses", {}).items():
            l_info["is_active"] = True
        save_users_db()
        return jsonify({"success": True, "message": "All licenses activated."})
        
    return jsonify({"success": False, "error": "Invalid bulk action"}), 400

@admin_bp.route('/api/admin/toggle_device_visibility', methods=['POST'], endpoint='admin_toggle_device_visibility')
@admin_required
def admin_toggle_device_visibility():
    data = request.json or {}
    username = data.get('username', '').strip()
    device_id = data.get('device_id', '').strip()
    
    if not username or not device_id:
        return jsonify({"success": False, "error": "Username and device_id are required"}), 400
        
    user_info = users_database.get("users", {}).get(username)
    if not user_info:
        return jsonify({"success": False, "error": "User not found"}), 404
        
    if "hidden_devices" not in user_info:
        user_info["hidden_devices"] = []
        
    if device_id in user_info["hidden_devices"]:
        user_info["hidden_devices"].remove(device_id)
        action = "unhidden"
    else:
        user_info["hidden_devices"].append(device_id)
        action = "hidden"
        
    save_users_db()
    socketio.emit('device_status_change', {'device_id': device_id})
    return jsonify({"success": True, "action": action})

@admin_bp.route('/api/admin/list_reports', endpoint='admin_list_reports')
@admin_required
def admin_list_reports():
    reports = users_database.get("reports", [])
    return jsonify({"success": True, "reports": reports})

@admin_bp.route('/api/admin/resolve_report', methods=['POST'], endpoint='admin_resolve_report')
@admin_required
def admin_resolve_report():
    data = request.json or {}
    report_id = data.get("report_id")
    action = data.get("action")
    if not report_id:
        return jsonify({"success": False, "error": "Report ID is required."}), 400
        
    reports = users_database.get("reports", [])
    found = False
    for rep in reports:
        if rep.get("id") == report_id:
            found = True
            if action == "resolve":
                rep["status"] = "resolved"
            elif action == "pending":
                rep["status"] = "pending"
            elif action == "delete":
                reports.remove(rep)
            break
            
    if not found:
        return jsonify({"success": False, "error": "Report not found."}), 404
        
    users_database["reports"] = reports
    save_users_db()
    return jsonify({"success": True, "message": f"Report action '{action}' completed."})
