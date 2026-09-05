# famX Dual-Port Architecture & Device Gateway Guide

## Architecture Overview

Proton utilizes a **Dual-Port Topology** separating user/admin web interaction from high-throughput hardware telemetry ingestion with **zero breaking changes**:

```
                         ┌─────────────────────────────────┐
                         │        NETWORK TRAFFIC          │
                         └────────┬───────────────┬────────┘
                                  │               │
       Existing Hardware Devices  │               │ Web Browsers
       (Port 5000 / Configurable) │               │ (Port 8800 / Configurable)
                                  ▼               ▼
                     ┌──────────────────┐   ┌──────────────────┐
                     │   PORT 5000      │   │   PORT 8800      │
                     │   famX Gateway   │   │  Web Dashboard   │
                     │ (Headless Device │   │ (Admin & Users   │
                     │ Ingestion + Sockets) │  HTML & Session) │
                     └────────┬─────────┘   └────────┬─────────┘
                              │                      │
                              │   Live Event Relay   │
                              ├──────────────────────┘
                              │
                              ▼
                     ┌─────────────────────────────────────────┐
                     │        SHARED STORAGE & STATE           │
                     │  database.json | users_db.json          │
                     │  data/ | media/                         │
                     └─────────────────────────────────────────┘
```

---

## Port Allocation & Configuration

Both ports are fully configurable via environment variables or [`config.py`](file:///home/vedx/Videos/Proton/config.py):

| Service | Default Port | Environment Variable | Purpose |
| :--- | :--- | :--- | :--- |
| **Web Dashboard** | `8800` | `WEB_PORT` | Admin portal, user dashboard, HTML views, session auth |
| **famX Gateway** | `5000` | `DEVICE_PORT` | Hardware telemetry ingestion, GPS location, camera streaming, media uploads |

### Changing Ports

To customize ports on startup:
```bash
export WEB_PORT=9000
export DEVICE_PORT=5050
python3 app.py
```

In `docker-compose.yml`:
```yaml
ports:
  - "${WEB_PORT:-8800}:8800"
  - "${DEVICE_PORT:-5000}:5000"
environment:
  WEB_PORT: "${WEB_PORT:-8800}"
  DEVICE_PORT: "${DEVICE_PORT:-5000}"
```

---

## famX Hardware Token Security

To prevent unauthorized telemetry injection, hardware devices authenticate using `famX` tokens:

### Token Format
```text
famX_<device_id>_<signature>
```
* **Generation**: Generated using HMAC-SHA256 keyed with `SECRET_KEY` and the device ID.
* **Verification**: Constant-time verification prevents timing attacks.
* **Backwards Compatibility**: Legacy devices without tokens continue to connect using their existing license key handshake with zero breaking changes.

### Sending famX Tokens from Hardware
1. **HTTP Headers**:
   ```http
   X-famX-Token: famX_DEV001_4b8a3b628ba9d882d1267d36
   ```
2. **URL Query Parameter**:
   ```http
   POST /api/device/DEV001/upload_media?token=famX_DEV001_...
   ```
3. **Socket.IO Query String**:
   ```javascript
   const socket = io("http://<server-ip>:5000", {
       query: {
           device_id: "DEV001",
           token: "famX_DEV001_4b8a3b628ba9d882d1267d36"
       }
   });
   ```

---

## Cross-Port Event Relay
Hardware devices sending telemetry to Port 5000 are automatically relayed in-memory to the Web Dashboard on Port 8800:
- **Camera Frames**: Hardware emits `camera_frame` on Port 5000 &rarr; Dashboard receives `camera_frame_relay` on Port 8800.
- **GPS Location**: Hardware emits `location` on Port 5000 &rarr; Dashboard receives `location_update` on Port 8800.
- **Commands**: Admin on Port 8800 triggers an action &rarr; Dispatched to device socket on Port 5000 via `emit_device_command`.
