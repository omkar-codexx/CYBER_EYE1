# Proton Documentation

This directory contains architectural, design, and reference documentation for the Proton application.

## Documentation Index

- [Gluetun ProtonVPN Port Forwarding Guide](file:///home/vedx/Videos/Proton/docs/gluetun_vpn_port_forwarding_guide.md) — CGNAT bypass, automated NAT-PMP port forwarding, and Telegram alerts.
- [Multi-Device Load Testing & Benchmarking Guide](file:///home/vedx/Videos/Proton/docs/load_testing_and_benchmarking_guide.md) — Production guide to stress-testing 10–1,000 devices, measuring RPS/latency, and live server monitoring.
- [Nginx Load Balancer & Kubernetes Scaling Guide](file:///home/vedx/Videos/Proton/docs/load_balancer_and_k8s_roadmap.md) — High-concurrency device handling (25–100+ devices), localhost-only admin binding, and K8s roadmap.
- [famX Dual-Port Gateway Architecture](file:///home/vedx/Videos/Proton/docs/famx_gateway_architecture.md) — Dual-port topology (Web Port 8800 vs Hardware Port 5000) and famX token security.
- [Complete Project Architecture & Logic Reference](file:///home/vedx/Videos/Proton/docs/complete_project_architecture_and_logic.md) — Comprehensive technical reference for models, 61 routes, and socket events.
- [Walkthrough](file:///home/vedx/Videos/Proton/docs/walkthrough.md) — Summary of the modularization refactor, changes breakdown, and automated verification results.
- [Implementation Plan](file:///home/vedx/Videos/Proton/docs/implementation_plan.md) — Comprehensive plan and API specifications for Flask Blueprints, Core packages, and WebSocket events.

## Directory Structure

```
docs/
├── README.md                              # This documentation index
├── gluetun_vpn_port_forwarding_guide.md   # ProtonVPN Gluetun port forwarding guide
├── load_balancer_and_k8s_roadmap.md         # Nginx load balancer & k8s migration guide
├── famx_gateway_architecture.md           # famX Dual-port gateway architecture & token guide
├── complete_project_architecture_and_logic.md # Complete backend logic & route specifications
├── walkthrough.md                         # Post-refactor walkthrough & test evidence
└── implementation_plan.md                 # Modular architecture implementation plan & specs
```
