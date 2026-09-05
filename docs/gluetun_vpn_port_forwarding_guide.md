# Gluetun ProtonVPN Port Forwarding & Nginx Enterprise Guide

## 1. How the Architecture Works

This setup allows remote field hardware devices to connect back to your server without needing a public static IP, port forwarding on your home/office WiFi router, or dealing with ISP CGNAT:

```
                      ┌──────────────────────────────────────────────────┐
                      │                 PUBLIC INTERNET                  │
                      └────────┬────────────────────────────────┬────────┘
                               │                                │
        Remote Field Hardware  │ (ProtonVPN Public Tunnel)      │ Local Host / Admin
        (Via Forwarded Port)   │                                │ (Localhost:8800)
                               ▼                                ▼
                      ┌──────────────────────────────────────────────────┐
                      │              PROTON-VPN (GLUETUN)                │
                      │  - OpenVPN Tunnel + NAT-PMP Port Forward         │
                      │  - Writes port to /gluetun/forwarded_port        │
                      │  - Exposes 5000 (Hardware) & 8800 (Admin)        │
                      └────────────────────────┬─────────────────────────┘
                                               │ (Shared Network Namespace)
                                               ▼
                      ┌──────────────────────────────────────────────────┐
                      │             NGINX REVERSE PROXY                  │
                      │  - WebSocket Upgrade (Connection: Upgrade)       │
                      │  - 3600s Keep-Alive (Handles VPN packet jitter)  │
                      │  - 100MB File/Media Upload Buffering             │
                      │  - 10,240 Concurrent Connections (epoll)         │
                      └────────────────────────┬─────────────────────────┘
                                               │
                                               ▼
                      ┌──────────────────────────────────────────────────┐
                      │                 CYBEREYE-APP                     │
                      │  - famX Hardware Ingestion (Port 5001)           │
                      │  - Web Dashboard UI (Port 8801)                  │
                      │  - Telegram Notifier (Reads /gluetun/...)        │
                      └────────────────────────┬─────────────────────────┘
                                               │ (Private Local Docker Network)
                                               ▼
                      ┌──────────────────────────────────────────────────┐
                      │           POSTGRESQL 15  &  REDIS 7              │
                      │  - 100% Private, Local & Secure                  │
                      │  - 0% Exposed to VPN or Public Internet          │
                      └──────────────────────────────────────────────────┘
```

---

## 2. Configuration Steps (`.env`)

1. **Copy the example configuration**:
   ```bash
   cp .env.example .env
   ```
2. **Fill in ProtonVPN Credentials**:
   > [!IMPORTANT]
   > Your OpenVPN username **MUST** end with `+pmp` to enable NAT-PMP port forwarding!
   > Example: `PROTON_OPENVPN_USER=user123+pmp`
   
   ```bash
   PROTON_OPENVPN_USER=your_openvpn_username+pmp
   PROTON_OPENVPN_PASSWORD=your_openvpn_password
   ```

3. **Configure Telegram Bot Notifications**:
   Create a bot on Telegram via `@BotFather`, get your numeric ID via `@userinfobot`, and add:
   ```bash
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxyz
   TELEGRAM_CHAT_ID=987654321
   ```

4. **Start the Stack**:
   ```bash
   docker compose up -d --build
   ```

---

## 3. Real-Time Telegram Alerts

Whenever Gluetun establishes or renews the VPN connection, ProtonVPN assigns an external public port (e.g. `52341`).
`services/telegram_notifier.py` automatically detects this and sends a message to your Telegram:

```text
🚀 ProtonVPN Port Forwarding Active!
Public IP: 185.107.56.23
Forwarded Port: 52341
famX Hardware Endpoint: http://185.107.56.23:52341
Admin Dashboard: http://localhost:8800
```

---

## 4. Local Admin Protection (`WEB_BIND`)

The Admin Web Dashboard is bound to `127.0.0.1:8800` by default:
- Accessible only on your physical machine at `http://127.0.0.1:8800` (or via SSH tunnel).
- Attackers on the public internet or VPN network **cannot** reach the admin dashboard or login page.
- Field devices communicate strictly with the forwarded hardware port.
