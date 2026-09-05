# Walkthrough: Dual-Port Architecture (Port 8800 & Port 5000) & famX Gateway

## Overview
Successfully implemented the **Dual-Port Topology** separating user and admin web interaction from hardware telemetry ingestion with **100% backwards compatibility and zero breaking changes**.

---

## Architectural Changes

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

## Key Features

1. **Configurable Ports**:
   - **Port 8800** (Default `WEB_PORT`): Web Dashboard, Admin portal, HTML pages, and session login.
   - **Port 5000** (Default `DEVICE_PORT`): Headless `famX` Ingestion Gateway. All web views return `404`, shielding the dashboard from hardware endpoints.
   - Fully customizable via `export WEB_PORT=...` and `export DEVICE_PORT=...` or in [`config.py`](file:///home/vedx/Videos/Proton/config.py).

2. **famX Device Token Authentication**:
   - Implemented in [`core/gateway_auth.py`](file:///home/vedx/Videos/Proton/core/gateway_auth.py) using HMAC-SHA256 tokens (`famX_<device_id>_<sig>`).
   - Constant-time validation prevents timing attacks.
   - Fallback supports legacy devices using their existing license keys with zero breaking changes.

3. **Cross-Port Real-Time Event Relay**:
   - Hardware connects to Port 5000 &rarr; Camera frames, GPS coordinates, and keylogs are relayed in real time to browsers connected to Port 8800.
   - Actions triggered by Admins on Port 8800 are dispatched to hardware on Port 5000 via [`extensions.emit_device_command`](file:///home/vedx/Videos/Proton/extensions.py).

4. **Single-Command Launch**:
   - Running `python3 app.py` or `docker-compose up` launches both servers concurrently in the same process with shared storage.

---

## Verification Results

Ran automated test suite via [`scripts/verify_dual_port.py`](file:///home/vedx/Videos/Proton/scripts/verify_dual_port.py):

```text
=== 1. Testing famX Token Generation & Verification ===
Generated token for DEV_FAMX_001: famX_DEV_FAMX_001_4b8a3b628ba9d882d1267d36
famX Token Cryptographic Validation: OK

=== 2. Testing Port Isolation (Web vs Gateway) ===
Web Server: /login accessible: OK
famX Gateway: Web Dashboard & Admin shielded (returns 404): OK
famX Gateway: Health check JSON: OK

=== 3. Testing Hardware Ingestion on famX Gateway ===
[famX Gateway] Uploaded info.txt for device: DEV_FAMX_001
famX Gateway: Device telemetry upload with famX token: OK

=== 4. Testing Cross-Server Real-Time Socket Relay ===
[famX Gateway] Device online: DEV_FAMX_001 (Model: Unknown) on Port 5000
Cross-Port Live Telemetry Relay (Port 5000 -> Port 8800): OK

=======================================================
 ALL DUAL-PORT & famX GATEWAY VERIFICATIONS PASSED! 
=======================================================
```

Existing route map verification via [`scripts/verify_routes.py`](file:///home/vedx/Videos/Proton/scripts/verify_routes.py):
```text
Total registered routes: 61
SUCCESS: All critical routes verified!
ALL SYSTEM VERIFICATIONS PASSED SUCCESSFULLY!
```
