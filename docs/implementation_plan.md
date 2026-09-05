# Implementation Plan: Modularize and Split `app.py` into Flask Blueprints and Core Modules

## Overview
Originally, [`app.py`](file:///home/vedx/Videos/Proton/app.py) was a 1,900+ line monolithic file containing application configuration, database state management, password hashing, authentication decorators, data parsing routines, Socket.IO real-time event handlers, API endpoints, admin operations, and HTML view routes.

This document details the architecture and specifications used to decompose `app.py` into a clean, industry-standard Flask application structure with zero breaking changes to existing endpoints, WebSocket event streams, or device client connections.

---

## Architectural Guarantees

> [!IMPORTANT]
> **Zero Breaking Changes Policy**: All URL routes, socket event names (`connect`, `camera_frame`, `keylogs`, etc.), payload formats, and template render targets remain identical so that active connected devices, dashboards, and background services continue functioning seamlessly.

> [!NOTE]
> **Environment Variables**: Hardcoded credentials (`GEMINI_API_KEY`, `SECRET_KEY`, `ADMIN_PASSWORD_HASH`) were moved into a central configuration module (`config.py`) that reads from environment variables with backwards-compatible defaults.

---

## Target Project Architecture

```
Proton/
├── app.py                      # Clean app entrypoint (registers blueprints, initializes SocketIO)
├── config.py                   # Centralized configuration & environment variables
├── extensions.py               # Shared SocketIO extension instance
├── core/
│   ├── __init__.py
│   ├── database.py             # JSON DB storage (devices, users, licenses, policies)
│   ├── auth.py                 # Auth decorators (@login_required, @admin_required, device access guards)
│   └── parsers.py              # Cloud device data parser (get_and_parse_cloud_data)
├── routes/
│   ├── __init__.py             # Blueprint exports & registration helper
│   ├── views.py                # Page routes (dashboard, camera, audio, location, etc.)
│   ├── auth.py                 # User & Admin authentication (/login, /logout, etc.)
│   ├── api.py                  # Device data, actions, AI chat, media streaming endpoints
│   └── admin.py                # Admin management APIs (license, users, maintenance, bulk ops)
├── sockets/
│   ├── __init__.py
│   └── events.py               # Socket.IO handlers (connect, disconnect, camera_frame, keylogs, location)
├── services/
│   ├── __init__.py
│   └── telegram_notifier.py    # IP/port notification service
├── scripts/
│   ├── migrate_mock.py         # DB migration script
│   └── verify_routes.py        # Automated route test suite
├── docs/                       # Project documentation & architectural guides
├── static/
└── templates/
```

---

## Component Specifications

### 1. Core & Configuration

#### [`config.py`](file:///home/vedx/Videos/Proton/config.py)
- Centralizes configuration variables:
  - `SECRET_KEY` (from `os.environ.get("SECRET_KEY", "cybereye-secret")`)
  - `GEMINI_API_KEY` (from `os.environ.get("GEMINI_API_KEY", "...")`)
  - `DB_FILE = 'database.json'`
  - `USERS_DB_FILE = 'users_db.json'`
  - `BLACKLIST`
  - `ADMIN_EMAIL = "Admin@cybereye.co.in"`

#### [`extensions.py`](file:///home/vedx/Videos/Proton/extensions.py)
- Initializes shared `socketio = SocketIO(cors_allowed_origins="*")` to eliminate circular import dependencies between routes and events.

#### [`core/database.py`](file:///home/vedx/Videos/Proton/core/database.py)
- Houses JSON database state and persistence:
  - `database`, `load_db()`, `save_db()`
  - `users_database`, `load_users_db()`, `save_users_db()`
  - In-memory tracking: `connected_devices`, `sid_to_device`, `connected_device_licenses`

#### [`core/auth.py`](file:///home/vedx/Videos/Proton/core/auth.py)
- Authentication helpers and route protection decorators:
  - `hash_password(password)`, `check_password(password, hashed)`
  - `@login_required`
  - `@admin_required`
  - `has_device_access(username, device_id)`
  - `check_maintenance_policy` hook

#### [`core/parsers.py`](file:///home/vedx/Videos/Proton/core/parsers.py)
- Cloud data parsing utility:
  - `get_and_parse_cloud_data(device_id, category)` for calls, sms, apps, contacts, accounts, notifications, usage, and files.
  - `update_device_record(device_id, data)`

---

### 2. Flask Blueprints (`routes/`)

#### [`routes/auth.py`](file:///home/vedx/Videos/Proton/routes/auth.py)
- Blueprint: `auth_bp`
- Endpoints:
  - `GET /login`, `POST /login`
  - `GET /logout`
  - `GET /check_auth`
  - `GET /admin/login`, `POST /admin/login`
  - `GET /admin/logout`

#### [`routes/views.py`](file:///home/vedx/Videos/Proton/routes/views.py)
- Blueprint: `views_bp`
- Endpoints:
  - `GET /` &rarr; Redirects to login or dashboard
  - `GET /introl` &rarr; Serves intro gateway
  - `GET /dashboard` &rarr; Serves main dashboard
  - `GET /keylogs`, `/file_manager`, `/social_media`, `/location_3d`, `/route_history`, `/geofencing`, `/ai_chatbot`
  - `GET /Screen_mirroring.html`, `/Live_Camera.html`, `/Live_Audio.html`
  - `GET /admin` &rarr; Serves admin dashboard
  - Static media alias routes (`/introl.mp4`, `/logo.png`, `/logo1.png`)

#### [`routes/api.py`](file:///home/vedx/Videos/Proton/routes/api.py)
- Blueprint: `api_bp`
- Device & User REST API endpoints:
  - `/api/devices`
  - `/api/device/<device_id>/data`
  - `/api/device/<device_id>/ai_context`
  - `/api/device/<device_id>/ai_chat`
  - `/api/device/<device_id>/monitored_apps`
  - `/api/device/<device_id>/mirror_status`
  - `/api/device/<device_id>/live_camera_status`
  - `/api/device/<device_id>/live_audio_status`
  - `/api/device/<device_id>/previews`
  - `/api/media/stream/<device_id>/<filename>`
  - `/api/device/<device_id>/upload_media`
  - `/api/device/<device_id>/action`
  - `/api/device/<device_id>/clear_route`
  - `/api/device/<device_id>/location`
  - `/api/device/<device_id>/geofence/...`
  - `/api/device/<device_id>/clear_keylogs`
  - `/api/device/<device_id>/clear_notif_pending`
  - `/api/device/<device_id>/delete_media/<media_key>`
  - `/api/device/<device_id>/clear_chats`
  - `/api/network_status`
  - `/api/user/details`
  - `/api/user/report_issue`

#### [`routes/admin.py`](file:///home/vedx/Videos/Proton/routes/admin.py)
- Blueprint: `admin_bp`
- Admin management endpoints:
  - `/api/admin/list_users_keys`
  - `/api/admin/create_user`
  - `/api/admin/delete_user`
  - `/api/admin/generate_license`
  - `/api/admin/toggle_license_active`
  - `/api/admin/apply_maintenance`
  - `/api/admin/bulk_op`
  - `/api/admin/toggle_device_visibility`
  - `/api/admin/list_reports`
  - `/api/admin/resolve_report`

---

### 3. Real-Time WebSockets (`sockets/`)

#### [`sockets/events.py`](file:///home/vedx/Videos/Proton/sockets/events.py)
- SocketIO event handlers registered with the `socketio` instance:
  - `connect`
  - `disconnect`
  - `join_device_room`
  - `camera_frame`
  - `keylogs`
  - `notification_logged`
  - `location`
  - `social_message`

---

### 4. Application Entrypoint

#### [`app.py`](file:///home/vedx/Videos/Proton/app.py)
- Initializing `Flask` and `SocketIO`
- Registering Blueprints (`auth_bp`, `views_bp`, `api_bp`, `admin_bp`)
- Registering Socket.IO event listeners via `register_socket_events(socketio)`
- Starting Telegram IP/port monitor service on startup
- Running via `socketio.run(app, ...)`
