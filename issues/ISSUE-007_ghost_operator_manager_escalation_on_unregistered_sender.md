# ISSUE-007: Ghost Operator & Mock Manager Escalation on Unregistered Sender

**Status:** LOGGED / BACKLOG  
**Severity:** HIGH  
**Component:** `core_platform.app.ingress.whatsapp_router` / `apps.temperature_marker.graph.nodes.router_node`  
**Date Logged:** 2026-09-24  

---

## 1. Problem Description
On a 100% clean slate system where:
- The database has **0 enrolled operators/employees**.
- The fleet roster has **0 managers configured**.

When an unregistered mobile phone sends an arbitrary, meaningless text string (e.g. `"hello"`, `"xyz123"`, random characters):
1. The app processes the message through conversational fallback.
2. It replies back to the mobile phone stating that the message has been forwarded to the manager.
3. In the communication log, it displays fictitious / mock operator and manager information despite the database being completely empty.

---

## 2. Root Cause Analysis
- **Missing Sender Identity Enforcement:** In `whatsapp_router.py`, arbitrary text messages from unauthenticated senders trigger a default conversational dispatch or escalation rule instead of an immediate registration boundary check.
- **Mock Supervisor Defaults:** When `emp` is `None` (unregistered sender) and no manager exists in the database, the router falls back to `settings.SUPERVISOR_PHONE` (e.g. `+919800000000`) and generates mock operator/manager display templates.
- **Violation of Layer 0 Directives:** Unregistered incoming phone numbers must be halted at Layer 0 deterministic gate before hitting conversational routing or manager escalation.

---

## 3. Desired Behavior
1. Unregistered senders sending arbitrary text must receive a strict, unambiguous response:
   > *"Welcome to CaneBot. Your phone number (+91XXXXXXXXXX) is not registered in the system. Please reach out to your facility manager to be enrolled."*
2. No message forwarding or manager escalation must ever trigger for unregistered phone numbers.
3. Zero mock or ghost operator/manager records should ever appear in the communication logs.
