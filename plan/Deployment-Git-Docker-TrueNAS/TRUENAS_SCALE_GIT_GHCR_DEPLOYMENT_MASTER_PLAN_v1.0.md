# TrueNAS SCALE (`ElectricEel-24.10`) Multi-Container Deployment, GitHub Container Registry (`ghcr.io`) CI/CD, and ZFS Storage Architecture Plan

```
Document Reference : R100-DEPLOY-TRUENAS-2026-V1.0
Version            : 1.0.0 (Initial Master Specification for TrueNAS SCALE Exclusive Deployment)
Status             : Architectural & Implementation Plan (Ready for Review)
Author             : Mahendra GURAV
License            : Apache License, Version 2.0
Location           : /plan/Deployment-Git-Docker-TrueNAS/TRUENAS_SCALE_GIT_GHCR_DEPLOYMENT_MASTER_PLAN_v1.0.md
Target Platform    : TrueNAS SCALE ElectricEel-24.10.0.2 (Native Docker & Docker Compose Engine on Debian Linux + ZFS)
Delivery Pipeline  : Option B — Git Push -> GitHub Actions -> GitHub Container Registry (ghcr.io) -> TrueNAS SCALE "Install via YAML"
Governed By        : Global Engineering Excellence Standard (GEES v3.1)
```

---

## Revision History

| Version | Date | Author | Summary of Architectural Scope & Decisions |
| :--- | :--- | :--- | :--- |
| **`v1.0.0`** | 2026-10-20 | Mahendra GURAV | Established **TrueNAS SCALE (`ElectricEel-24.10.0.2`)** as the sole deployment target. Designed the zero-cost, zero-Git-bloat **`ghcr.io` CI/CD Container Pipeline (Option B)**, the **Multi-Container Microservice-Ready Topology** (`release100-core`, `release100-ops`, `app-mail-organizer`, `app-temperature-marker`, `cloudflared`), the **Admin-Selectable Polyglot Database Architecture** (Single Shared DB Container vs. Per-Cartridge DB Containers vs. ZFS SQLite WAL), and the **TrueNAS ZFS Dataset & Non-Root ACL Specification**. |

---

## Table of Contents

1. [Executive Summary & Inviolable Deployment Directives](#1-executive-summary--inviolable-deployment-directives)
2. [End-to-End CI/CD Delivery Pipeline: Git $\rightarrow$ GitHub Actions $\rightarrow$ `ghcr.io` $\rightarrow$ TrueNAS SCALE](#2-end-to-end-cicd-delivery-pipeline-git--github-actions--ghcrio--truenas-scale)
3. [Multi-Container & Microservice-Ready Topology on TrueNAS SCALE](#3-multi-container--microservice-ready-topology-on-truenas-scale)
4. [Admin-Selectable Database Architecture (Single Shared vs. Per-Cartridge vs. Tenant Silo)](#4-admin-selectable-database-architecture-single-shared-vs-per-cartridge-vs-tenant-silo)
5. [TrueNAS SCALE ZFS Dataset Layout, Non-Root UID/GID ACLs & Snapshot Strategy](#5-truenas-scale-zfs-dataset-layout-non-root-uidgid-acls--snapshot-strategy)
6. [Zero-Inbound Ingress, 4-Plane Microkernel Portability & Zero-Trust Security](#6-zero-inbound-ingress-4-plane-microkernel-portability--zero-trust-security)
7. [Complete TrueNAS SCALE `docker-compose.truenas.yml` ("Install via YAML" Blueprint)](#7-complete-truenas-scale-docker-composetruenasyml-install-via-yaml-blueprint)
8. [Multi-Target `Dockerfile` & Container Entrypoint Specification](#8-multi-target-dockerfile--container-entrypoint-specification)
9. [6-Item Production Readiness Checklist & Verification Gates (GEES v3.1)](#9-6-item-production-readiness-checklist--verification-gates-gees-v31)
10. [Phased Implementation Roadmap](#10-phased-implementation-roadmap)

---

## 1. Executive Summary & Inviolable Deployment Directives

### 1.1 Sole Deployment Target: TrueNAS SCALE (`ElectricEel-24.10.0.2`)
Henceforth, **all deployment engineering for `Release100` exclusively targets TrueNAS SCALE (`ElectricEel-24.10.0.2` and newer)**.

TrueNAS SCALE `ElectricEel-24.10.0.2` replaces legacy Kubernetes (`k3s`) with **100% native Docker and Docker Compose** running directly on the TrueNAS Debian Linux host kernel:
* **Zero BIOS Hardware Virtualization (`VT-x` / `AMD-V`) Required:** Containers share the TrueNAS host Linux kernel via namespaces and `cgroups`. No KVM hypervisor, no guest OS RAM overhead, and no monitor/BIOS access is needed on the headless TrueNAS server.
* **Native Web UI "Install via YAML":** Multi-container stacks are deployed and updated directly from the TrueNAS Web UI (**Apps $\rightarrow$ Discover Apps $\rightarrow$ `⋮` $\rightarrow$ Install via YAML**) or via **Dockge / Portainer / SSH**.
* **Enterprise ZFS Storage Substrate:** All persistent databases, AES-256-GCM encrypted credential vaults, and FDA 21 CFR Part 11 / ISO 22000 SHA-256 hash-chained audit logs reside on checksummed, snapshot-protected TrueNAS ZFS datasets.

### 1.2 Core Architectural Requirements Incorporated (Zero Omissions)
This plan synthesizes every historical deployment and architectural decision established across the platform:
1. **Option B (`ghcr.io` Cloud Container Registry Pipeline at \$0.00 Cost):**
   * Pushing code to Git (`intent-router` or `main`) triggers **GitHub Actions** in the cloud to build Python wheels (`.whl`) and compile multi-stage Docker images, pushing them to **GitHub Container Registry (`ghcr.io/meetmahendra/...`)**.
   * **Zero Git Bloat:** No compiled Docker image bytes ever enter the Git repository.
   * **Instant TrueNAS Pulls:** TrueNAS SCALE pulls pre-built images from `ghcr.io` and starts containers in ~3 seconds without compiling `gcc`, OpenCV, or Python packages on the NAS.
2. **Multi-Container & Microservice-Ready Separation:**
   * **Container 1 (`release100-core`):** FastAPI Orchestrator (`:8002`), Native SSE MCP Server (`:8001`), Plane 1 Ingress Normalizer, Plane 2 Slim Microkernel, Plane 3 System Apps (`tenancy`, `iam`, `rbac`, `entitlements`, `admin_shell`), and 3-Tier Multi-Modal Semantic Router.
   * **Container 2 (`release100-ops`):** Out-of-band Operational Control Plane (`/ops/tenants`) for heavy DevOps provisioning, Deep-Clone with cryptographic re-salting, and 5-step Geo/Storage Data Transfer—isolated so management workloads never starve real-time webhook/worker threads.
   * **Container 3 (`app-mail-organizer`):** Dedicated container for the AI Mail & Omnichannel Triage Cartridge (background IMAP/Gmail polling, System 1 Jev / System 2 Gemini pipeline, Commitment Ledger, Calendar scheduling).
   * **Container 4 (`app-temperature-marker`):** Dedicated container for the Industrial Temperature & Attendance Marker Cartridge (Haversine GPS geofencing, InsightFace ONNX verification, 7-Segment/LCD Vision OCR, HACCP validation, ERP MCP sync).
   * **Container 5 (`cloudflared`):** Outbound-only Cloudflare Tunnel sidecar providing public HTTPS ingress without opening inbound ports on the router in front of TrueNAS SCALE.
   * **Optional Container 6 (`ollama` / `jev-systemone`):** Local on-premise AI model container on the internal Docker bridge network for 100% air-gapped local LLM execution.
3. **Admin-Selectable Database Topology:**
   * The Admin decides via environment configuration whether Core and Cartridges share a **Single Database Container** (`release100-postgres` with separate logical schemas + C-Kernel Row-Level Security), use **Separate Per-Cartridge Database Containers** (`postgres-core`, `postgres-mail`, `postgres-temp`), or use **Per-Tenant SQLite WAL Files** (`PRAGMA journal_mode=WAL`) on a TrueNAS ZFS dataset.

---

## 2. End-to-End CI/CD Delivery Pipeline: Git $\rightarrow$ GitHub Actions $\rightarrow$ `ghcr.io` $\rightarrow$ TrueNAS SCALE

### 2.1 How the Zero-Bloat `ghcr.io` Pipeline Works

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Developer PC (Windows)
    participant Git as GitHub Repo (Code Only)
    participant GHA as GitHub Actions (Ubuntu Cloud Runner)
    participant Pages as GitHub Pages (PEP 503 Wheel Index)
    participant GHCR as GitHub Container Registry (ghcr.io)
    participant NAS as TrueNAS SCALE (ElectricEel-24.10.0.2)

    Dev->>Git: git push origin intent-router (Lightweight source/config only)
    Git->>GHA: Triggers .github/workflows/publish-packages.yml
    GHA->>GHA: Job 1: Builds wheels (release100-core, mail_organizer, temperature_marker)
    GHA->>Pages: Publishes PEP 503 Simple Wheel Index (/intent-router/ & /main/)
    GHA->>GHA: Job 2: Builds multi-target Docker images using built wheels + Buildx GHA Cache
    GHA->>GHCR: Pushes ghcr.io/meetmahendra/release100-core:{channel, version, latest}
    GHA->>GHCR: Pushes ghcr.io/meetmahendra/release100-ops:{channel, version, latest}
    GHA->>GHCR: Pushes ghcr.io/meetmahendra/release100-mail-organizer:{channel, version, latest}
    GHA->>GHCR: Pushes ghcr.io/meetmahendra/release100-temperature-marker:{channel, version, latest}
    NAS->>GHCR: TrueNAS SCALE pulls images via "Install via YAML" (docker-compose.truenas.yml)
    GHCR-->>NAS: Streams pre-built compressed layers; containers boot in ~3s
```

### 2.2 Container Images Published to `ghcr.io`

All images share the identical `python:3.12-slim` + `/venv` base layer (meaning Docker on TrueNAS SCALE downloads the base Python/OpenCV layer **only once** and reuses it across all 4 application containers!):

| Image URI on `ghcr.io` | Role in TrueNAS SCALE Stack | Tags Published Automatically |
| :--- | :--- | :--- |
| `ghcr.io/meetmahendra/release100-core` | Plane 1–3 Core Orchestrator (`:8002`) + Native SSE MCP Server (`:8001`) | `:intent-router`, `:main`, `:latest`, `:<version>` |
| `ghcr.io/meetmahendra/release100-ops` | Out-of-Band DevOps Super-Admin Control Plane & Migration Worker | `:intent-router`, `:main`, `:latest`, `:<version>` |
| `ghcr.io/meetmahendra/release100-mail-organizer` | AI Mail & Omnichannel Triage Cartridge Worker / Service | `:intent-router`, `:main`, `:latest`, `:<version>` |
| `ghcr.io/meetmahendra/release100-temperature-marker` | Industrial Attendance & Temperature Marker Cartridge Worker / Service | `:intent-router`, `:main`, `:latest`, `:<version>` |

### 2.3 GitHub Actions Workflow Enhancement (`.github/workflows/publish-packages.yml`)

The existing `.github/workflows/publish-packages.yml` already declares `permissions: packages: write`. We extend it with a second job (`build-and-push-docker`) that:
1. Downloads the freshly built `.whl` artifacts from Job 1 (`build-and-publish`).
2. Logs into `ghcr.io` using the built-in `${{ secrets.GITHUB_TOKEN }}` (zero external secrets or credit cards needed).
3. Uses `docker/setup-buildx-action@v3` and `docker/build-push-action@v6` with GitHub Actions cache (`cache-from: type=gha`, `cache-to: type=gha,mode=max`) so subsequent builds finish in ~45 seconds.
4. Builds and pushes each target from `deployment/docker/Dockerfile` using `--target <stage_name>`.

---

## 3. Multi-Container & Microservice-Ready Topology on TrueNAS SCALE

### 3.1 Full Container Topology & Inter-Service Communication

```mermaid
flowchart TB
    subgraph External["External Internet & Clients"]
        Meta["Meta WhatsApp Cloud API"]
        Google["Google OAuth2 / Workspace"]
        Users["Tenant Admins & Operators\n(Browser / Mobile PWA / Cursor MCP)"]
    end

    subgraph CloudflareEdge["Cloudflare Zero-Trust Edge"]
        CFWorker["Cloudflare Worker + Durable Object\n(wss://whatsapp-cloud-relay.../ws/NODE-01)"]
        CFTunnel["Cloudflare Zero-Trust Tunnel\n(HTTPS -> cloudflared)"]
    end

    subgraph TrueNAS["TrueNAS SCALE ElectricEel-24.10.0.2 (Internal Docker Bridge Network: release100_net)"]
        subgraph EdgeTier["Plane 1: Edge & Tunnel Container"]
            Cloudflared["Container: cloudflared\n(Zero Inbound Firewall Ports)"]
        end

        subgraph CoreTier["Plane 2 & 3: Core & Ops Containers"]
            Core["Container 1: release100-core\n• FastAPI Host (:8002)\n• Native SSE MCP (:8001)\n• Cloudflare WS Client\n• System Apps (Tenancy, IAM, RBAC, Entitlements, Shell)"]
            Ops["Container 2: release100-ops\n• Out-of-Band /ops Control Plane (:8003)\n• Tenant Provisioning & Deep-Clone\n• 5-Step Geo/Storage Transfer Engine\n• Audit Chain Verifier"]
        end

        subgraph CartridgeTier["Plane 4: Pluggable Domain Cartridge Containers"]
            Mail["Container 3: app-mail-organizer\n• IMAP/Gmail Poller Supervisor\n• Tier 0/1/2 Triage Pipeline\n• Commitment Ledger & Outbox Worker"]
            Temp["Container 4: app-temperature-marker\n• Haversine Geofence & ONNX Face/OCR\n• HACCP Anomaly Engine\n• ERP MCP Dispatch Worker"]
        end

        subgraph DataTier["Configurable Database & Local AI Containers"]
            PGShared["Container 5A: postgres-shared\n(Single Shared PostgreSQL 16 Container\nwith Schema-per-App & Tenant RLS)"]
            PGCartridge["Container 5B (Optional): Per-Cartridge DBs\n(postgres-mail / postgres-temp)"]
            LocalLLM["Container 6 (Optional): ollama / jev\n(Local On-Premise AI Inference)"]
        end
    end

    Meta --> CFWorker
    Users & Google --> CFTunnel
    CFTunnel --> Cloudflared
    Cloudflared --> Core
    Cloudflared --> Ops
    CFWorker <-->|"Outbound WSS"| Core

    Core <-->|"Kernel Event Bus / Outbox / Protocol RPC"| Mail
    Core <-->|"Kernel Event Bus / Outbox / Protocol RPC"| Temp

    Core & Ops --> PGShared
    Mail --> PGShared
    Temp --> PGShared
    Mail -.->|"If Per-Cartridge DB Selected"| PGCartridge
    Temp -.->|"If Per-Cartridge DB Selected"| PGCartridge
    Core & Mail & Temp -.->|"Optional Local LLM"| LocalLLM
```

### 3.2 How Separate Cartridge Containers & Core Synchronize Cleanly
To satisfy both **today's modular deployment** and **future microservice scalability**:
1. **Shared Kernel Event Bus & Transactional Outbox Table:**
   * When `app-temperature-marker` (running in Container 4) detects a critical chiller or fever anomaly, it writes a `DomainEvent` to the transactional outbox / event bus.
   * `app-mail-organizer` (running in Container 3) consumes that event asynchronously and drafts an executive escalation briefing—**with zero direct Python imports between Container 3 and Container 4** (`test_e2e_cross_cartridge_synergy.py`).
2. **UI & API Gateway Aggregation in `release100-core`:**
   * `release100-core` mounts the unified Admin Shell (`/admin`) and dynamically routes cartridge UI/API requests either in-process (via installed wheel entry points `release100.cartridges`) or by proxying/dispatching to the dedicated cartridge container over `http://app-mail-organizer:8011` and `http://app-temperature-marker:8012` on the internal TrueNAS Docker bridge network (`release100_net`).
3. **Out-of-Band `release100-ops` Isolation:**
   * `release100-ops` runs on port `:8003` (or handles `/ops/*` routes and background maintenance jobs). When a Platform Operator runs a Deep-Clone or Geo-Transfer of a 10 GB tenant database, the CPU/IO work happens strictly inside `release100-ops`, ensuring `release100-core` continues answering WhatsApp webhooks in `<50ms`.

---

## 4. Admin-Selectable Database Architecture (Single Shared vs. Per-Cartridge vs. Tenant Silo)

Per your architectural directive:
> *"Admin will have choice to decide which db he want to use which application core, per cartridges etc. if same database used by everyone, we will have its single installation."*

### 4.1 Environment-Driven Database Routing Matrix

Every container resolves its database backend through explicit environment variables in the TrueNAS Compose configuration:

```ini
# ---------------------------------------------------------------------------
# DATABASE TOPOLOGY SELECTION (Configured by Admin in TrueNAS SCALE)
# ---------------------------------------------------------------------------
# Global Default Database URL (Used by any component that does not specify an override)
DATABASE_URL=postgresql+psycopg://release100:${POSTGRES_PASSWORD}@postgres-shared:5432/release100_platform

# Optional Per-Component Database URL Overrides (Leave blank to share DATABASE_URL)
CORE_DATABASE_URL=
OPS_DATABASE_URL=
MAIL_ORGANIZER_DATABASE_URL=
TEMPERATURE_MARKER_DATABASE_URL=
```

### 4.2 The 3 Supported Database Deployment Topologies on TrueNAS SCALE

| Topology Mode | How Admin Configures It | Container Layout on TrueNAS SCALE | Isolation Mechanism |
| :--- | :--- | :--- | :--- |
| **Mode 1: Single Shared PostgreSQL Container *(Recommended Default)*** | Set `DATABASE_URL` pointing to `postgres-shared:5432`; leave per-cartridge overrides blank. | **1 DB Container** (`postgres-shared`) shared by Core, Ops, Mail Organizer, and Temperature Marker. | • **App Data Sovereignty:** Each System App and Cartridge owns strictly prefixed/schema-scoped tables.<br>• **Tenant Isolation:** Schema-per-Tenant (`tenant_<id>`) + PostgreSQL C-Kernel Row-Level Security (RLS). |
| **Mode 2: Separate Per-Cartridge DB Containers** | Enable the `per-cartridge-db` Docker Compose profile and set `MAIL_ORGANIZER_DATABASE_URL=postgresql://...@postgres-mail:5432/mail_db` and `TEMPERATURE_MARKER_DATABASE_URL=postgresql://...@postgres-temp:5432/temp_db`. | **3 DB Containers** (`postgres-shared` for Core/Ops, `postgres-mail` for Mail Organizer, `postgres-temp` for Temperature Marker). | **Physical Container & ZFS Dataset Isolation** between Core, Mail Organizer, and Temperature Marker workloads. |
| **Mode 3: Lightweight ZFS SQLite WAL Mode** | Set `DATABASE_URL=sqlite:////opt/release100/data/platform_registry.db` (zero Postgres containers needed). | **0 DB Containers** (Embedded SQLite 3 with `PRAGMA journal_mode=WAL` and `synchronous=NORMAL`). | **Physical File-per-Tenant Isolation** (`/opt/release100/data/tenants/{tenant_id}/{app_id}.db`) backed directly by TrueNAS ZFS datasets. |

> [!TIP]
> **Runtime Dynamic Override for High-Compliance Tenants:**  
> Even when running in Mode 1 or Mode 3, the Super-Admin can assign a specific Enterprise Tenant its own dedicated database container at runtime via `/ops/tenants` (`db_connection_uri` in `TenantConfig`), and migrate existing data live using the 5-Step Data Transfer Engine (`POST /ops/tenants/{id}/transfer`).

---

## 5. TrueNAS SCALE ZFS Dataset Layout, Non-Root UID/GID ACLs & Snapshot Strategy

### 5.1 Recommended TrueNAS SCALE ZFS Dataset Hierarchy
On your TrueNAS SCALE pool (e.g., `/mnt/tank` or `/mnt/<your_pool>`), create a parent dataset `apps/release100` with the following child datasets:

```text
/mnt/<pool>/apps/release100/
├── config/          # Mounted to /opt/release100/config (master.env / runtime YAML)
├── data/            # Mounted to /opt/release100/data (Per-tenant SQLite WAL DBs & state)
├── creds/           # Mounted to /opt/release100/.local_credentials (AES-256-GCM encrypted vault)
├── logs/            # Mounted to /opt/release100/logs (Tri-format .jsonl, .csv, .html SHA-256 audits)
├── models/          # Mounted to /opt/release100/core_platform/app/skills/models:ro (ONNX models)
└── postgres/        # Mounted to /var/lib/postgresql/data (PostgreSQL 16 cluster storage)
```

### 5.2 ZFS Tuning Best Practices for TrueNAS SCALE
| Child Dataset | ZFS Recordsize | Compression | Rationale |
| :--- | :--- | :--- | :--- |
| `postgres/` | **`16 KiB`** (`16K`) | `LZ4` | Matches PostgreSQL's 8KB/16KB page size to eliminate ZFS write amplification. |
| `data/` (SQLite WAL) | **`64 KiB`** (`64K`) | `LZ4` | Optimal for SQLite WAL page writes and tenant state files. |
| `logs/` (Audit Ledger) | **`128 KiB`** (`128K`) | `ZSTD` | High compression ratio (~4x–6x) for append-only `.jsonl`, `.csv`, and `.html` audit logs. |
| `creds/` | **`128 KiB`** | `LZ4` | Small encrypted credential blobs. |
| `models/` | **`1 MiB`** (`1M`) | `LZ4` | Large sequential read-only ONNX neural network weights (`InsightFace`, OCR). |

### 5.3 Non-Root Container Security & TrueNAS `apps` User (`568:568`) Compatibility
In TrueNAS SCALE `ElectricEel-24.10.0.2`, standard application datasets use the built-in TrueNAS **`apps` user (`UID=568`, `GID=568`)**.
* Our `Dockerfile` will create the non-root runtime user with configurable `PUID`/`PGID` (defaulting to `568:568` for TrueNAS SCALE compatibility, or overrideable via `user: "568:568"` in `docker-compose.truenas.yml`).
* In TrueNAS UI (**Datasets $\rightarrow$ Edit Permissions** on `/mnt/<pool>/apps/release100`), setting Owner = `apps (568)` and Group = `apps (568)` with **"Apply permissions recursively"** guarantees zero `PermissionError` issues across all containers while enforcing strict non-root container execution.

### 5.4 ZFS Snapshots & Master Key Separation Rule
1. **Automated ZFS Periodic Snapshot Task:** Configure a TrueNAS Periodic Snapshot Task on `/mnt/<pool>/apps/release100` every **1 hour** (retained for 14 days).
2. **Cryptographic Master Key Separation:** The `RELEASE100_TOKEN_ENCRYPTION_KEY` (used for HKDF-SHA256 + AES-256-GCM envelope encryption) is injected via the TrueNAS Custom App / Compose environment configuration and backed up in your password manager—**never committed to Git and never stored in plaintext inside the database volume**.

---

## 6. Zero-Inbound Ingress, 4-Plane Microkernel Portability & Zero-Trust Security

### 6.1 Dual Zero-Inbound Ingress on TrueNAS SCALE
Your TrueNAS SCALE server sits safely behind your LAN firewall with **zero router port-forwarding (`0` open inbound WAN ports)**:
1. **Channel 1 — Outbound Cloudflare Worker WebSocket Relay (`RELAY_WS_URL`):**
   * `release100-core` opens an outbound persistent WebSocket (`wss://whatsapp-cloud-relay.myvirtualsecretory.workers.dev/ws/NODE-01`) to our Cloudflare Worker + SQLite Durable Object (`KioskSession`).
   * Meta WhatsApp webhooks are HMAC-verified (`X-Hub-Signature-256`) at the Cloudflare Edge in `<5ms` and streamed down the outbound WebSocket to TrueNAS SCALE.
2. **Channel 2 — Companion `cloudflared` Zero-Trust Tunnel Container:**
   * The `cloudflared` container in our Compose stack connects outbound using `CLOUDFLARE_TUNNEL_TOKEN`, exposing the Admin Shell (`/admin`), Super-Admin Ops Portal (`/ops/tenants`), Google OAuth2 Magic Link callback (`/auth/google/callback`), and Native SSE MCP Server (`/mcp/sse`) over TLS without exposing your home/factory IP address.

### 6.2 Cloud & LAN Domain Portability (Zero Host Hardcoding)
Because of our **4-Plane Microkernel Architecture**:
* **LAN Direct Access:** You can open `http://<truenas-lan-ip>:8002/admin` or `http://truenas.local:8002/ops/tenants` directly on your local Wi-Fi/LAN.
* **Custom Domain / Tunnel Access:** You can simultaneously access the exact same container via your Cloudflare Tunnel domain (`https://app.yourdomain.com` or `https://{tenant}.yourdomain.com`).
* **Capability-Based Authorization:** Route access is governed strictly by cryptographic session permissions (`SecurityContext.has_permission("platform:ops_access")`), never by fragile hostname string checks.

---

## 7. Complete TrueNAS SCALE `docker-compose.truenas.yml` ("Install via YAML" Blueprint)

Below is the production multi-container Compose specification designed for **TrueNAS SCALE `ElectricEel-24.10.0.2` (`Install via YAML`)**:

```yaml
# =============================================================================
# Release100 Enterprise Platform — TrueNAS SCALE (ElectricEel 24.10+) Stack
# Copyright 2026 Mahendra GURAV | Apache License 2.0
#
# Deployment in TrueNAS SCALE UI:
#   Apps -> Discover Apps -> Three-dots menu (top right) -> Install via YAML
# =============================================================================

name: release100-platform

x-common-env: &common-env
  TZ: ${TZ:-Asia/Kolkata}
  RELEASE100_ENV: production
  DRY_RUN: ${DRY_RUN:-false}
  BASE_DOMAIN: ${BASE_DOMAIN:-}
  # Master Encryption Key for AES-256-GCM Envelope Encryption (32-byte hex/base64)
  RELEASE100_TOKEN_ENCRYPTION_KEY: ${RELEASE100_TOKEN_ENCRYPTION_KEY}
  JWT_SECRET_KEY: ${JWT_SECRET_KEY}
  # Admin-Selectable Database URLs (Defaults to single shared Postgres container)
  DATABASE_URL: ${DATABASE_URL:-postgresql+psycopg://release100:${POSTGRES_PASSWORD}@postgres-shared:5432/release100_platform}
  CORE_DATABASE_URL: ${CORE_DATABASE_URL:-}
  OPS_DATABASE_URL: ${OPS_DATABASE_URL:-}
  MAIL_ORGANIZER_DATABASE_URL: ${MAIL_ORGANIZER_DATABASE_URL:-}
  TEMPERATURE_MARKER_DATABASE_URL: ${TEMPERATURE_MARKER_DATABASE_URL:-}
  # LLM & Channel Keys (Platform defaults; tenants can override via BYOK Vault)
  GEMINI_API_KEY: ${GEMINI_API_KEY:-}
  WHATSAPP_ACCESS_TOKEN: ${WHATSAPP_ACCESS_TOKEN:-}
  WHATSAPP_PHONE_NUMBER_ID: ${WHATSAPP_PHONE_NUMBER_ID:-}
  WHATSAPP_VERIFY_TOKEN: ${WHATSAPP_VERIFY_TOKEN:-}
  WHATSAPP_APP_SECRET: ${WHATSAPP_APP_SECRET:-}
  RELAY_WS_URL: ${RELAY_WS_URL:-wss://whatsapp-cloud-relay.myvirtualsecretory.workers.dev/ws/NODE-01}
  # Internal Service Discovery URLs on TrueNAS Docker Bridge Network
  OPS_SERVICE_URL: http://release100-ops:8003
  MAIL_CARTRIDGE_SERVICE_URL: http://app-mail-organizer:8011
  TEMP_CARTRIDGE_SERVICE_URL: http://app-temperature-marker:8012

x-common-volumes: &common-volumes
  - ${TRUENAS_APPS_PATH:-/mnt/tank/apps/release100}/data:/opt/release100/data
  - ${TRUENAS_APPS_PATH:-/mnt/tank/apps/release100}/logs:/opt/release100/logs
  - ${TRUENAS_APPS_PATH:-/mnt/tank/apps/release100}/creds:/opt/release100/.local_credentials
  - ${TRUENAS_APPS_PATH:-/mnt/tank/apps/release100}/models:/opt/release100/core_platform/app/skills/models:ro

services:
  # ---------------------------------------------------------------------------
  # 1. SHARED DATABASE CONTAINER (Default Single Installation for All Apps)
  # ---------------------------------------------------------------------------
  postgres-shared:
    image: postgres:16-alpine
    container_name: release100-postgres-shared
    restart: unless-stopped
    user: "568:568"
    environment:
      POSTGRES_USER: release100
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: release100_platform
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - ${TRUENAS_APPS_PATH:-/mnt/tank/apps/release100}/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U release100 -d release100_platform"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - release100_net

  # ---------------------------------------------------------------------------
  # 2. CORE RUNTIME CONTAINER (Plane 1 Ingress + Plane 2 Kernel + Plane 3 Apps)
  # ---------------------------------------------------------------------------
  release100-core:
    image: ghcr.io/meetmahendra/release100-core:${IMAGE_TAG:-intent-router}
    container_name: release100-core
    restart: unless-stopped
    user: "568:568"
    ports:
      - "${CORE_HTTP_PORT:-8002}:8002"   # Admin Shell, Tenant Portal & Webhook API
      - "${CORE_MCP_PORT:-8001}:8001"    # Native SSE MCP Server for Cursor/Claude
    environment:
      <<: *common-env
      CONTAINER_ROLE: core
      PORT: "8002"
      MCP_PORT: "8001"
      ENABLED_APPLICATIONS: ${ENABLED_APPLICATIONS:-mail_organizer,temperature_marker}
    volumes: *common-volumes
    depends_on:
      postgres-shared:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 30s
      timeout: 10s
      start_period: 15s
      retries: 3
    networks:
      - release100_net

  # ---------------------------------------------------------------------------
  # 3. OPERATIONAL CONTROL PLANE CONTAINER (Out-of-Band Super-Admin & Migrations)
  # ---------------------------------------------------------------------------
  release100-ops:
    image: ghcr.io/meetmahendra/release100-ops:${IMAGE_TAG:-intent-router}
    container_name: release100-ops
    restart: unless-stopped
    user: "568:568"
    ports:
      - "${OPS_HTTP_PORT:-8003}:8003"    # Dedicated DevOps Control Plane Port
    environment:
      <<: *common-env
      CONTAINER_ROLE: ops_control
      PORT: "8003"
    volumes: *common-volumes
    depends_on:
      postgres-shared:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8003/health"]
      interval: 30s
      timeout: 10s
      start_period: 15s
      retries: 3
    networks:
      - release100_net

  # ---------------------------------------------------------------------------
  # 4. DOMAIN CARTRIDGE CONTAINER 1: AI Mail & Omnichannel Organizer
  # ---------------------------------------------------------------------------
  app-mail-organizer:
    image: ghcr.io/meetmahendra/release100-mail-organizer:${IMAGE_TAG:-intent-router}
    container_name: release100-app-mail-organizer
    restart: unless-stopped
    user: "568:568"
    environment:
      <<: *common-env
      CONTAINER_ROLE: cartridge_mail_organizer
      PORT: "8011"
    volumes: *common-volumes
    depends_on:
      release100-core:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8011/health"]
      interval: 30s
      timeout: 10s
      start_period: 15s
      retries: 3
    networks:
      - release100_net

  # ---------------------------------------------------------------------------
  # 5. DOMAIN CARTRIDGE CONTAINER 2: Industrial Temperature & Attendance Marker
  # ---------------------------------------------------------------------------
  app-temperature-marker:
    image: ghcr.io/meetmahendra/release100-temperature-marker:${IMAGE_TAG:-intent-router}
    container_name: release100-app-temperature-marker
    restart: unless-stopped
    user: "568:568"
    environment:
      <<: *common-env
      CONTAINER_ROLE: cartridge_temperature_marker
      PORT: "8012"
    volumes: *common-volumes
    depends_on:
      release100-core:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8012/health"]
      interval: 30s
      timeout: 10s
      start_period: 15s
      retries: 3
    networks:
      - release100_net

  # ---------------------------------------------------------------------------
  # 6. ZERO-INBOUND CLOUDFLARE TUNNEL CONTAINER
  # ---------------------------------------------------------------------------
  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: release100-cloudflared
    restart: unless-stopped
    command: tunnel --no-autoupdate run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN:-}
    depends_on:
      release100-core:
        condition: service_healthy
    networks:
      - release100_net

networks:
  release100_net:
    driver: bridge
```

---

## 8. Multi-Target `Dockerfile` & Container Entrypoint Specification

Instead of maintaining 4 separate Dockerfiles that drift out of sync, we use a **Single Multi-Stage, Multi-Target `Dockerfile`** (`deployment/docker/Dockerfile`):

1. **Stage 1 (`base-builder`):**
   * Starts from `python:3.12-slim`.
   * Installs C/system build dependencies (`gcc`, `libpq-dev`, `libgl1`, `libglib2.0-0`) and creates `/venv` with core dependencies + `psycopg[binary]` (for PostgreSQL support alongside SQLite).
2. **Stage 2 (`base-runtime`):**
   * Clean `python:3.12-slim` image with runtime libraries (`libgl1`, `libglib2.0-0`, `curl`), non-root user `kiosk` configured with `UID=568` / `GID=568` (matching TrueNAS SCALE `apps` user), and pre-created `/opt/release100/{data,logs,.local_credentials}`.
3. **Target 1 (`core-runtime` $\rightarrow$ `ghcr.io/meetmahendra/release100-core`):**
   * Installs `release100-core` (and cartridge plugin interfaces) and boots the Core Host (`:8002`) + MCP Server (`:8001`) via `entrypoint.sh`.
4. **Target 2 (`ops-control` $\rightarrow$ `ghcr.io/meetmahendra/release100-ops`):**
   * Runs pre-boot NTP verification, `alembic upgrade head` schema migrations, and boots the dedicated Out-of-Band Operational Control Plane service (`:8003`).
5. **Target 3 (`cartridge-mail-organizer` $\rightarrow$ `ghcr.io/meetmahendra/release100-mail-organizer`):**
   * Installs `release100-cartridge-mail-organizer` wheel and runs the Mail & Omnichannel Triage worker + background IMAP/Gmail Poller Supervisor (`:8011`).
6. **Target 4 (`cartridge-temperature-marker` $\rightarrow$ `ghcr.io/meetmahendra/release100-temperature-marker`):**
   * Installs `release100-cartridge-temperature-marker` wheel and runs the Temperature & Attendance Marker worker + Outbox ERP Synchronizer (`:8012`).

---

## 9. 6-Item Production Readiness Checklist & Verification Gates (GEES v3.1)

Every deployment on TrueNAS SCALE enforces the 6 production readiness invariants established in our architecture discussions:

1. **Meta 24-Hour Customer Care Window & Utility Templates:**
   * `last_whatsapp_interaction_at` is tracked per user. Free-form `@Urgent` notifications fire when active within 24 hours; outside 24 hours, the dispatcher uses pre-approved Meta Utility Templates.
2. **Webhook Idempotency / Deduplication (`wamid`):**
   * Incoming WhatsApp messages are deduplicated against `wamid` before invoking LangGraph or spending LLM tokens.
3. **Master Encryption Key Backup Outside NAS Container Volume:**
   * `RELEASE100_TOKEN_ENCRYPTION_KEY` is injected via TrueNAS Custom App environment settings and backed up externally so encrypted database rows are never orphaned.
4. **Public Privacy Policy & Terms of Service Endpoints:**
   * `/privacy` and `/terms` routes are served for Google OAuth2 production verification.
5. **Concurrent Multi-User Database Safety:**
   * Shared PostgreSQL 16 container (or SQLite with `PRAGMA journal_mode=WAL` and `busy_timeout=5000`) eliminates write-lock contention during simultaneous multi-tenant polling.
6. **Graceful OAuth Token Revocation (`NEEDS_REAUTH`):**
   * If a user revokes Google OAuth access (`invalid_grant`), the poller marks the account `NEEDS_REAUTH`, pauses polling cleanly without crashing, and dispatches a fresh 10-minute WhatsApp Magic Link.

---

## 10. Phased Implementation Roadmap

### Phase 1: Multi-Target `Dockerfile`, Entrypoints & Database URL Resolver
* Upgrade `core_platform` database configuration to support `CORE_DATABASE_URL`, `OPS_DATABASE_URL`, `MAIL_ORGANIZER_DATABASE_URL`, and `TEMPERATURE_MARKER_DATABASE_URL` falling back cleanly to `DATABASE_URL` (supporting both SQLite WAL and PostgreSQL).
* Upgrade `deployment/docker/Dockerfile` and `deployment/docker/entrypoint.sh` to support `CONTAINER_ROLE` (`core`, `ops_control`, `cartridge_mail_organizer`, `cartridge_temperature_marker`) and TrueNAS SCALE UID/GID `568:568`.
* Create `deployment/truenas/docker-compose.truenas.yml` and `deployment/truenas/.env.truenas.example`.

### Phase 2: GitHub Actions `ghcr.io` Image Publishing Pipeline
* Extend `.github/workflows/publish-packages.yml` with the `build-and-push-ghcr-images` job to build and push all 4 images (`release100-core`, `release100-ops`, `release100-mail-organizer`, `release100-temperature-marker`) to `ghcr.io/meetmahendra/*` on every push to `intent-router` and `main`.

### Phase 3: Automated Verification & Version Bump Gate (GEES v3.1)
* Add unit and integration tests (`tests/test_truenas_deployment_topology.py`) verifying multi-container role entrypoints, per-cartridge database URL resolution, `docker-compose.truenas.yml` schema validity, and `MANIFEST-GUARD` compliance.
* Increment synchronized package versions across `pyproject.toml`, `apps/temperature_marker/pyproject.toml`, `apps/mail_organizer/pyproject.toml`, and `__version__` constants.
* Execute Tier 1 (`pytest`) and Tier 2 (`python scripts/verify_all.py --fast`) gates prior to presenting commit diff for explicit user approval ("go").

### Phase 4: Live TrueNAS SCALE (`ElectricEel-24.10.0.2`) Deployment & Smoke Verification
* Create `/mnt/<pool>/apps/release100/{data,logs,creds,models,postgres}` datasets on TrueNAS SCALE with `apps (568:568)` permissions.
* Deploy stack via TrueNAS Web UI (**Apps $\rightarrow$ Install via YAML**) pulling live images from `ghcr.io/meetmahendra/*`.
* Verify `/health` across all containers, Admin Shell login, Ops Control Plane (`/ops/tenants`), and live WhatsApp / Cloudflare Relay round-trip.
