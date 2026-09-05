# Complete Project Architecture, Logic, and Data Specifications (Proton / famX)

> **Purpose**: This document serves as the single source of truth for the entire Proton backend. It preserves all database schemas, route behaviors, WebSocket event flows, and business logic to ensure that future migrations (such as PostgreSQL + Redis) guarantee **100% zero breaking changes**.

---

## 1. System Topology & Dual-Port Architecture

```
                          ┌────────────────────────────────────────┐
                          │            INCOMING NETWORK            │
                          └───────────┬────────────────┬───────────┘
                                      │                │
            Hardware Devices          │                │ Web Browsers
            (Port 5000 / famX)        │                │ (Port 8800 / Web)
                                      ▼                ▼
                         ┌──────────────────────────────────────────────┐
                         │             NGINX LOAD BALANCER              │
                         │   - WebSocket Upgrade (Connection: Upgrade)  │
                         │   - 10,240 Concurrency (epoll)               │
                         │   - 3600s Stream Timeouts                    │
                         │   - 100MB Upload Buffering                   │
                         └────────────┬───────────────────┬─────────────┘
                                      │                   │
                     Internal 5000    │                   │ Internal 8800
                                      ▼                   ▼
                         ┌─────────────────┐     ┌─────────────────┐
                         │  famX Gateway   │     │  Web Dashboard  │
                         │   (gateway.py)  │     │    (app.py)     │
                         └────────┬────────┘     └────────┬────────┘
                                  │   Live Relay          │
                                  ├───────────────────────┘
                                  │
                                  ▼
                         ┌─────────────────────────────────────────┐
                         │             STORAGE LAYER               │
                         │ Current: JSON files (database.json)     │
                         │ Target:  PostgreSQL (ACID) + Redis (RAM)│
                         └─────────────────────────────────────────┘
```

---

## 2. Complete Data Schemas & Models

### A. Device Model (`database[device_id]`)
Each telemetry device has a unique `device_id` (e.g. `V2238_0A1E`) containing:

| Field | Type | Description |
| :--- | :--- | :--- |
| `_id` | String | Unique Device Identifier |
| `license_key` | String | Active license assigned to this device |
| `info` | String | System telemetry string: `model`, `manufacturer`, `android`, `ip`, `battery`, `notif_pending` |
| `logs` | List[str] | Chronological audit log of connection and operational events |
| `refs` | Dict[str, int] | Millisecond timestamps for latest category updates (`calls`, `sms`, `contacts`, `apps`, `accounts`, `notifications`, `files`, `info`) |
| `lastSeen` | Integer | Epoch millisecond timestamp of last network activity |
| `settings` | Dict | Device configuration: <br>• `lock_track_enabled` (bool)<br>• `monitored_apps` ({ key: { name, package } })<br>• `geofences` (List of geofence rules) |
| `last_geofence_states` | Dict[str, str] | Mapping of `fence_id` &rarr; `"inside"` \| `"outside"` |
| `geofence_events` | List[dict] | Capped list (50 max) of `{ fence_id, name, type, event, time }` |
| `today_route` | List[dict] | Array of `{ lat, lng, time }` coordinates for current day |
| `today_route_date` | String | Date string `"YYYY-MM-DD"` |
| `route_history` | List[dict] | Capped list (30 days max) of `{ date: "YYYY-MM-DD", route: [...] }` |
| `keylogs` | Dict[str, dict] | Keylog entries: `{ log_id: { pkg, text, time } }` |
| `chats` | Dict | Social messages: `{ platform: { contact: { contactName, messages: { m_id: { text, type, time } } } } }` |
| `media` | Dict | Categorized media files: `{ photos: [...], voice: [...], video: [...] }` |

### B. User & License Model (`users_database`)

#### `users`
```json
{
  "test": {
    "password_hash": "...",
    "plain_password": "...",
    "role": "user",
    "devices": ["V2238_0A1E", "V2238_C323"],
    "hidden_devices": [],
    "last_seen": 1788614543
  }
}
```

#### `licenses`
```json
{
  "CYBER-3ZPY-J99Y-86I1-TNPF": {
    "assigned_to": "test",
    "expires_at": 1792575619,
    "is_active": true,
    "created_at": 1788180369
  }
}
```

#### `system_policy`
```json
{
  "maintenance_mode": false,
  "maintenance_message": "Scheduled updates are in progress...",
  "maintenance_until": 0
}
```

#### `reports`
```json
[
  {
    "id": "REP-SUBBIT",
    "username": "test",
    "license_key": "CYBER-...",
    "issue_text": "camera not working",
    "timestamp": 1787809607,
    "status": "pending"
  }
]
```

### C. In-Memory Tracking State
* `connected_devices`: `{ device_id: sid }`
* `sid_to_device`: `{ sid: device_id }`
* `connected_device_licenses`: `{ device_id: license_key }`

---

## 3. Endpoints & Route Specifications (61 Routes)

### A. Authentication Blueprint (`routes/auth.py` &rarr; `auth_bp`)
* `GET /login`, `POST /login`: Validates `username`, `password`, and assigned, non-expired `license_key`.
* `GET /logout`: Clears session.
* `GET /check_auth`: Returns `{ authenticated: bool, username: ... }`.
* `GET /admin/login`, `POST /admin/login`: Dedicated admin login gate using `ADMIN_EMAIL` and `ADMIN_PASSWORD_HASH`.
* `GET /admin/logout`: Clears admin session.

### B. View Routes (`routes/views.py` &rarr; `views_bp`)
* `GET /`: Redirects to `/dashboard` or `/login`.
* `GET /dashboard`: Main interactive telemetry dashboard (devices, map, status).
* `GET /keylogs`: Keystroke surveillance view.
* `GET /file_manager`: Device filesystem inspector.
* `GET /social_media`: WhatsApp/Telegram/SMS chat inspector.
* `GET /location_3d`, `GET /route_history`, `GET /geofencing`: GPS map and tracking views.
* `GET /Live_Camera.html`, `GET /Live_Audio.html`, `GET /Screen_mirroring.html`: Real-time streaming viewers.
* `GET /ai_chatbot`: Gemini-assisted telemetry interrogation tool.
* `GET /admin`: Complete system administration console.

### C. REST API Blueprint (`routes/api.py` &rarr; `api_bp`)
* `/api/devices`: List of user's authorized devices.
* `/api/device/<device_id>/data`: Device cloud categories (calls, sms, contacts, apps, files).
* `/api/device/<device_id>/action`: Dispatches hardware action (`START_CAMERA`, `STOP_CAMERA`, `START_AUDIO`, `START_LOCK_TRACK`, etc.).
* `/api/device/<device_id>/clear_route`: Flushes current route coordinates.
* `/api/device/<device_id>/upload_media`: Telemetry and media ingestion.
* `/api/device/<device_id>/ai_chat`: Gemini telemetry query agent.
* `/api/user/report_issue`: Submits support ticket.

### D. Admin API Blueprint (`routes/admin.py` &rarr; `admin_bp`)
* `/api/admin/list_users_keys`: Complete dump of all users, licenses, and assigned devices.
* `/api/admin/create_user`, `/api/admin/delete_user`: User provisioning.
* `/api/admin/generate_license`, `/api/admin/toggle_license_active`: License lifecycle.
* `/api/admin/apply_maintenance`: Toggles system-wide maintenance lock.
* `/api/admin/bulk_op`: Executes mass operations across devices.

---

## 4. Real-time WebSocket Protocol (`sockets/events.py` & `gateway.py`)

| Event Name | Direction | Payload Structure | Action |
| :--- | :--- | :--- | :--- |
| `connect` | In (Device) | `?device_id=&model=&license_key=&token=` | Registers device, auto-maps to user, joins room |
| `disconnect` | In (Device) | None | Marks device offline, cleans up `connected_devices` |
| `join_device_room` | In (Browser) | `{ device_id }` | **RBAC Guarded**: Validates `has_device_access()` before admitting |
| `camera_frame` | In (Device) | `{ frame: <base64> }` | Relays live frame to room listeners on Port 8800 |
| `location` | In (Device) | `{ lat, lng, time }` | Appends route, triggers geofence evaluation, relays to dashboard |
| `keylogs` | In (Device) | `{ pkg, text, time }` | Saves keylog record, broadcasts `keylog_received` |
| `notification_logged`| In (Device)| `{ package, title, text, time }` | Appends to disk log and updates `notif_pending` |
| `social_message` | In (Device) | `{ platform, contact, text, isSent, time }` | Saves deduplicated chat message, emits `social_message_received` |
| `command` | Out (To Device)| `{ action: <cmd> }` | Dispatched via `emit_device_command` to execute on hardware |

---

## 5. PostgreSQL + Redis Migration Strategy (Zero Breaking Changes)

To replace `database.json` and `users_db.json` without breaking a single line of backend logic:

### A. The Transparent Data Proxy Pattern
Instead of modifying all 61 routes that currently access `database[device_id]` or `users_database["users"]`, we implement a **Database Proxy Class**:
* Implements Python dictionary magic methods (`__getitem__`, `__setitem__`, `__contains__`, `get`, `pop`).
* Reads and writes directly to **PostgreSQL** behind the scenes.
* Caches hot device telemetry in **Redis**.
* **Zero code rewrite** required across `routes/api.py`, `routes/views.py`, and `sockets/events.py`!

### B. Relational Schema in PostgreSQL
* **`devices` table**: `device_id` (PK), `license_key`, `info`, `last_seen`, `data` (JSONB for settings, geofences, chats, routes).
* **`users` table**: `username` (PK), `password_hash`, `role`, `devices` (JSONB/array), `last_seen`.
* **`licenses` table**: `license_key` (PK), `assigned_to` (FK &rarr; users), `expires_at`, `is_active`.
* **`reports` table**: `id` (PK), `username`, `license_key`, `issue_text`, `timestamp`, `status`.
* **`system_policies` table**: Key-value system configurations.

### C. Redis Role
* Stores fast in-memory maps (`connected_devices`, `sid_to_device`).
* Serves as the **Socket.IO Message Queue** (`redis://redis:6379/0`), allowing multiple backend workers or future Kubernetes pods to broadcast WebSocket events across the entire cluster without dropping messages.
