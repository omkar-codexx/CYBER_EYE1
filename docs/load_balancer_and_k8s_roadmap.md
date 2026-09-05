# Nginx Load Balancer & High-Concurrency Device Scaling Guide

## 1. Overview

To handle **20–25+ continuously streaming hardware devices** (and scale to 100–1,000+ devices in production), an **Nginx Reverse Proxy & Load Balancer** is placed in front of the application.

```
                              ┌───────────────────────────────────┐
                              │         INCOMING TRAFFIC          │
                              └─────────┬─────────────────┬───────┘
                                        │                 │
             Hardware Devices           │                 │ Web Browsers
             (Port 5000)                │                 │ (Port 8800)
                                        ▼                 ▼
                         ┌──────────────────────────────────────────────┐
                         │             NGINX LOAD BALANCER              │
                         │   - 10,240 Worker Connections (epoll)        │
                         │   - WebSocket Upgrade (Connection: Upgrade)  │
                         │   - 3600s Keep-Alive / Long-Poll Timeouts    │
                         │   - 100MB File/Media Upload Buffering        │
                         │   - IP Hash / Persistent Device Pinning      │
                         └──────────────┬─────────────────┬─────────────┘
                                        │                 │
                       Proxy Port 5000  │                 │ Proxy Port 8800
                                        ▼                 ▼
                         ┌──────────────────────────────────────────────┐
                         │           INTERNAL DOCKER NETWORK            │
                         │   cybereye-app:5000    cybereye-app:8800     │
                         └──────────────────────┬───────────────────────┘
                                                │
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │           SHARED PERSISTENCE                 │
                         │   database.json | users_db.json              │
                         │   data/ | media/                             │
                         └──────────────────────────────────────────────┘
```

---

## 2. High-Concurrency Performance Tuning

In [`nginx/nginx.conf`](file:///home/vedx/Videos/Proton/nginx/nginx.conf):
* **Worker Connections**: Set to `10240` with `multi_accept on` and `use epoll;` to effortlessly support thousands of simultaneous socket connections without CPU spikes.
* **Persistent Streaming**: `proxy_read_timeout 3600s;` ensures long camera feeds and telemetry streams never get abruptly terminated by proxy timeouts.
* **Large Media Buffering**: `client_max_body_size 100M;` allows high-resolution photos and voice recordings to upload cleanly.
* **Sticky Socket Pinning**: `ip_hash;` keeps each device reliably connected to its active socket session.

---

## 3. Localhost-Only Admin Security (`WEB_BIND`)

If you want the **Admin Web Dashboard (Port 8800)** to be accessible **only on localhost** (e.g. via SSH tunnel or physical machine) while the **famX Hardware Gateway (Port 5000)** remains open to remote field devices:

In your `.env` file or environment:
```bash
# Bind admin portal strictly to localhost (127.0.0.1)
WEB_BIND=127.0.0.1
WEB_PORT=8800

# Keep hardware gateway open to all remote devices
DEVICE_BIND=0.0.0.0
DEVICE_PORT=5000
```

When you start Docker:
```bash
docker compose up -d
```
- Admin portal will only respond to `http://127.0.0.1:8800`. Outside attackers cannot reach the login page!
- Field hardware devices can connect freely to `http://<server-public-ip>:5000`.

---

## 4. Kubernetes (k8s) Migration Roadmap

When expanding from Docker Compose to a full Kubernetes cluster:

### Step 1: Deployment & Pods
Deploy `cybereye-app` as a Kubernetes `Deployment` with horizontal pod autoscaling (HPA) based on CPU/memory usage.

### Step 2: Internal Services
Create two `ClusterIP` services:
1. `famx-gateway-service` &rarr; TargetPort: `5000`
2. `web-dashboard-service` &rarr; TargetPort: `8800`

### Step 3: Kubernetes Ingress (Nginx Ingress Controller)
Apply standard Nginx Ingress annotations mirroring our `nginx.conf`:
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: proton-ingress
  annotations:
    nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/websocket-services: "famx-gateway-service,web-dashboard-service"
spec:
  rules:
  - host: devices.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: famx-gateway-service
            port:
              number: 5000
  - host: admin.yourdomain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: web-dashboard-service
            port:
              number: 8800
```
