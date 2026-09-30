# Copyright 2026 Mahendra GURAV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# PLAN 09: ENTERPRISE CLOUD SCALE, PLUGGABLE POLYGLOT DATA LAYER & DISTRIBUTED EVENT BUS (v1.0)

> **Document Status:** PROPOSED & RATIFIED FOR RELEASE100 ENTERPRISE  
> **Author:** Mahendra GURAV  
> **Governing Standards:** Global Engineering Excellence Standard (GEES v2.0), FDA 21 CFR Part 11, ISO 22000, SOC2 Type II  

---

## 1. Executive Summary & Strategic Objectives

As the platform scales from single-node edge kiosks and local retail stations to multi-facility enterprise conglomerates and regional franchise networks, it must accommodate a wide diversity of customer IT environments without changing a single line of business logic.

Plan 09 establishes the enterprise blueprint for:
1. **Pluggable Polyglot Database Architecture (Deployment-Time Database Selection):** Decoupling persistence from concrete database engines so customers can deploy on their database of choice (SQLite, PostgreSQL, TimescaleDB, MySQL, or Cloud-native AWS Aurora/Google Cloud SQL) based on their business model, cost targets, reliability requirements, and security compliance.
2. **Flexible Multi-Tenancy Isolation Models:** Supporting Database-per-Tenant (maximum regulatory isolation), Schema-per-Tenant (mid-market), and Shared RLS (cost-effective SaaS).
3. **Distributed Asynchronous Event Bus & Worker Pool:** Migrating the in-process outbox queue to Redis Streams and distributed worker pools (ARQ/Celery) with at-least-once delivery guarantees and dead-letter queues (DLQ).
4. **Enterprise Observability & OpenTelemetry (OTel) Tracing:** End-to-end transaction tracing across Edge Kiosks, Cloud Ingress Routers, LLMGateway, and Downstream Connectors (ERP, CRM, HRMS).
5. **Edge-to-Cloud Bidirectional Sync Protocol:** Resilient delta replication with cryptographic Merkle tree reconciliation ensuring edge kiosks operate 100% offline during outages and seamlessly reconcile audit records upon reconnection.

```
+-----------------------------------------------------------------------------------------+
|                                ENTERPRISE CLOUD ARCHITECTURE                             |
|                                                                                         |
|  +------------------------------------+      +---------------------------------------+  |
|  |       EDGE FLEET (Kiosks 1..N)      |      |        CLOUD CONTROL PLANE            |  |
|  |  * SQLite / SQLCipher Edge Cache   |      |  * Pluggable DB Adapter Factory       |  |
|  |  * Local ONNX Biometrics/OCR       | <==> |  * PostgreSQL / TimescaleDB / Aurora  |  |
|  |  * Offline Outbox Journal          | Sync |  * Redis Streams & Worker Fleet       |  |
|  |  * SHA-256 Audit Chaining          |      |  * OpenTelemetry / Jaeger Collector   |  |
|  +------------------------------------+      +---------------------------------------+  |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Pluggable Database Architecture & Deployment-Time Selection

### 2.1 Customer Business, Cost, Reliability & Security Matrix

The platform must never force a customer into an expensive or incompatible database vendor. Persistence is decoupled into four customer-selectable deployment tiers:

| Deployment Tier | Target Customer Profile | Recommended Database | Monthly Infrastructure Cost | Reliability / Concurrency Profile | Security & Compliance Features |
|---|---|---|---|---|---|
| **Tier 1: Edge / Offline Kiosk** | Single franchisee, standalone retail station, low-power edge PC | **SQLite / SQLCipher** (Local Embedded) | **$0** (Zero infrastructure overhead) | Local SSD read/write, zero network latency, single-node locking | Local AES-256 encryption at rest (SQLCipher) |
| **Tier 2: Mid-Market & SaaS** | Multi-store chain (10–100 kiosks), regional franchise hub | **PostgreSQL 16+** / **MySQL 8+** | **$15 – $75/mo** (Managed DigitalOcean / Supabase / AWS RDS) | High concurrent writes, ACID transactions, automated replica failover | TLS 1.3 in transit, tenant Row-Level Security (RLS) |
| **Tier 3: High-Frequency IoT & Sensors** | Industrial food processing, high-throughput HACCP thermal sensors | **TimescaleDB** (PostgreSQL extension) | **$50 – $200/mo** (Managed Timescale Cloud / Self-Hosted) | Partitioned daily hypertables, automated 90-day time-series compression | Immutable audit partition locks, automatic retention policies |
| **Tier 4: Regulated Enterprise Cloud** | Supermarket conglomerate, pharma, healthcare, banking | **AWS Aurora Serverless / GCP Cloud SQL / Azure DB / MSSQL** | **$200 – $1,000+/mo** | Multi-AZ 99.999% availability, auto-scaling connection pools | IAM authentication, Customer-Managed Keys (CMEK), private VPC peering |

---

### 2.2 Core Platform Pluggable Database Engine (`core_platform/app/db/`)

The Core Platform abstracts database connectivity behind an asynchronous connection factory that inspects `DATABASE_URL` at runtime:

```
┌────────────────────────────────────────────────────────────────────────┐
│ APPLICATION CARTRIDGES (apps/temperature_marker, apps/mail_organizer)   │
│ -> Implements standard SQLAlchemy Models & Declarative Metadata       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ CORE PLATFORM PLUGGABLE DATABASE ENGINE (core_platform/app/db/)        │
│ -> Reads DATABASE_URL / DB_ENGINE at boot time                         │
│ -> Automatically provisions Async Engine & SessionPool:                │
│    • sqlite+aiosqlite://...    (Zero-Dependency Local)                 │
│    • postgresql+asyncpg://...  (Enterprise PostgreSQL/Aurora)          │
│    • mysql+asyncmy://...       (MySQL / MariaDB)                       │
│    • mssql+aioodbc://...       (Microsoft SQL Server)                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ CUSTOMER INFRASTRUCTURE OF CHOICE                                      │
│ [ Local SSD File ] OR [ Customer AWS RDS ] OR [ Corporate On-Prem DB ] │
└────────────────────────────────────────────────────────────────────────┘
```

#### Connection Factory Specification:
```python
# core_platform/app/db/connection_factory.py
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
from core_platform.app.config import settings

class DatabaseConnectionFactory:
    """Manages asynchronous database engines and sessions across multiple dialects."""
    
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.is_sqlite = database_url.startswith("sqlite")
        self.is_postgres = "postgres" in database_url or "timescale" in database_url
        
        # Dialect-specific engine parameters
        engine_args = {"echo": False}
        if self.is_sqlite:
            engine_args["connect_args"] = {"check_same_thread": False}
        elif self.is_postgres:
            engine_args["pool_size"] = 20
            engine_args["max_overflow"] = 10
            
        self.engine: AsyncEngine = create_async_engine(database_url, **engine_args)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide deterministic, context-managed async database session."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
```

---

### 2.3 Dialect-Agnostic Schema & Alembic Migration Engine
- **Universal Field Types:** Models use universal SQLAlchemy abstractions (`Integer`, `String`, `DateTime`, `Text`, `Boolean`, and generic `JSON` which compiles to `JSONB` on PostgreSQL and `TEXT` on SQLite).
- **Conditional Dialect Features:** Advanced features (such as PostgreSQL Row-Level Security or TimescaleDB Hypertables) are encapsulated in conditional Alembic migration hooks that execute only when the target dialect supports them:

```python
# migrations/versions/002_enterprise_multitenancy.py
def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    
    if dialect == "postgresql":
        # Enable Row Level Security only on PostgreSQL
        op.execute("ALTER TABLE temperature_logs ENABLE ROW LEVEL SECURITY;")
        op.execute("""
            CREATE POLICY tenant_isolation_policy ON temperature_logs
            AS RESTRICTIVE USING (tenant_id = current_setting('app.current_tenant_id', true)::UUID);
        """)
```

---

### 2.4 Multi-Tenancy Strategy Selection

Customers can choose between three operational multi-tenancy models during deployment:

1. **Model A: Shared Database + Row-Level Security (Low-Cost Multi-Tenant SaaS):**
   - Single database cluster. All tenant queries automatically append `tenant_id` context via PostgreSQL RLS or application middleware.
2. **Model B: Schema-per-Tenant (Mid-Market B2B):**
   - Single PostgreSQL server instance, but each enterprise franchisee operates in an isolated SQL schema namespace (`tenant_alpha.*`, `tenant_beta.*`).
3. **Model C: Database-per-Tenant (High-Security / Regulated Enterprise):**
   - Physical database isolation where each enterprise customer connects to their own isolated database instance or encrypted SQLite container (HIPAA / Banking / Government compliant).

---

## 3. Distributed Asynchronous Messaging & Worker Architecture

### 3.1 Redis Streams Outbox & Task Distribution
The edge `OutboxSynchronizer` is bridged to an enterprise Redis Streams pipeline:

1. **`stream:temperature_events`**: High-priority ingestion stream for Duty Check-ins and HACCP violations.
2. **`stream:mail_events`**: Asynchronous batch queue for email categorization and Jira/Linear task synching.
3. **`stream:audit_events`**: Contemporaneous audit replication stream for centralized SIEM ingestion.

```python
# Enterprise Outbox Synchronizer Contract (Redis Streams)
class RedisOutboxSynchronizer:
    async def push_event(self, tenant_id: str, stream: str, payload: dict) -> str:
        """Push structured event to Redis Stream with correlation ID."""
        ...
    
    async def consume_group(self, group_name: str, consumer_id: str, batch_size: int = 50):
        """Consume event stream with consumer group acknowledgment."""
        ...
```

### 3.2 Dead-Letter Queue (DLQ) & Exponential Backoff
Downstream connector delivery failures (e.g. ERP API timeouts or HRMS maintenance windows) trigger exponential backoff with jitter up to 5 retries. Failed payloads exceeding max retries are automatically diverted to `dlq:connector_failures` with operator alerts dispatched via WhatsApp.

---

## 4. End-to-End Observability & OpenTelemetry (OTel)

### 4.1 Distributed Tracing Across Tiers
Every inbound WhatsApp webhook, admin shell request, and internal LangGraph execution is assigned a W3C-compliant `traceparent` header.

* **Trace Hierarchy:**
  `[WhatsApp Webhook Ingress] -> [Layer 0 Pre-Gate] -> [LangGraph Workflow] -> [LLMGateway Provider] -> [Database Commit] -> [Audit SHA-256 Chaining] -> [Outbound Push]`

### 4.2 Prometheus Metrics & Grafana Dashboards
Standardized metrics exported on `GET /metrics`:
- `duty_checkins_total{tenant, kiosk_id, status}`
- `haccp_violations_total{tenant, kiosk_id, severity}`
- `llm_latency_seconds{provider, model, status}`
- `llm_cost_total_usd{tenant, provider}`
- `outbox_queue_depth{app_id}`

---

## 5. Edge-to-Cloud Bidirectional Sync & Offline Resiliency

### 5.1 Merkle Tree State Reconciliation
When a kiosk reconnects after an extended offline period:
1. The Kiosk computes the Merkle root hash of its local un-synced audit logs.
2. The Cloud Control Plane compares root hashes to identify divergent time windows.
3. Only missing leaf blocks are transmitted in chunked binary batches with SHA-256 verification.

### 5.2 Conflict Resolution Matrix
- **Audit Records:** Append-only (non-destructive). Never overwritten.
- **Roster / Operator Credentials:** Cloud authoritative. Edge downloads latest credential snapshot and local ONNX embedding vectors.
- **Kiosk Status / Operational Mode:** Edge authoritative for real-time sensor states; Cloud authoritative for administrative lockout / emergency stop.

---

## 6. Implementation Roadmap & Milestones

| Phase | Milestone Description | Target Deliverables |
|---|---|---|
| **Phase 9.1** | Pluggable Database Connection Factory & Dialect Adapters | `core_platform/app/db/connection_factory.py`, `core_platform/app/db/dialects/` |
| **Phase 9.2** | Multi-Dialect Alembic Migrations & Multi-Tenancy Middleware | `core_platform/app/migrations/`, `core_platform/app/middleware/tenant_context.py` |
| **Phase 9.3** | Redis Streams Outbox & Distributed Worker Suite | `core_platform/app/outbox/redis_outbox.py`, `workers/task_worker.py` |
| **Phase 9.4** | OpenTelemetry Tracing Instrumentation & OTLP Exporter | `core_platform/app/telemetry/otel_tracer.py`, `docker-compose.telemetry.yml` |
| **Phase 9.5** | Edge Sync Manager & Merkle Tree Reconciler | `core_platform/app/sync/merkle_reconciler.py`, `tests/unit/test_edge_sync.py` |

---

## 7. Compliance & Certification Checklist
- [x] Strict compliance with **GEES v2.0** Multi-Layered Safety & Microkernel Architecture.
- [x] Deployment-Time Database Agnosticism (Zero vendor lock-in).
- [x] Zero modifications to protected pet projects (`D:\mailOrganizer`, `D:\WhatsappClientForMailOrganized`, `D:\AI-ProjectManager`).
- [x] SHA-256 Non-Repudiation Audit Trail across edge and cloud.
- [x] 100% Type Annotations under `mypy --strict`.
