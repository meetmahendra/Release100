# ISSUE-006: Ghost Kiosk & Hardcoded Geofence Fallback on Clean Slate

**Status:** LOGGED / BACKLOG  
**Severity:** HIGH  
**Component:** `apps.temperature_marker.graph.nodes.layer0_location_node` / `core_platform.app.ingress.whatsapp_router`  
**Date Logged:** 2026-09-24  

---

## 1. Problem Description
On a 100% clean slate system where:
- The database has **0 enrolled operators/employees**.
- The fleet roster has **0 registered kiosks/sites**.

When an unregistered mobile phone sends a WhatsApp location pin without any prior configuration or onboarding:
1. The system accepts and processes the location pin instead of rejecting the unregistered sender.
2. It evaluates the pin against hardcoded fallback coordinates (e.g. Pune coordinates `18.5077, 73.7913` for `CANEBOT-PUNE-04` / `CANEBOT-PUNE-05`).
3. It replies to the mobile user: *"You are too far away from [Kiosk]"*.

---

## 2. Root Cause Analysis
- **Hardcoded Fallbacks:** In `layer0_location_node.py` and `whatsapp_router.py`, when `kiosk_id` cannot be resolved from the roster or operator profile, the pipeline defaults to `settings.KIOSK_ID` or `"CANEBOT-PUNE-04"`.
- **Missing Zero-Kiosk Guard:** If no kiosk is configured or exists in the database, the geofencing node still looks up default coordinates rather than raising a strict domain error or returning a "No Active Kiosk Registered" prompt.
- **Pre-execution Gate Bypass:** Location messages from unknown senders bypass the Layer 0 unregistered sender validation.

---

## 3. Desired Behavior
1. If the sender's phone number is not enrolled in the database, the system must immediately reject or divert to self-onboarding:
   > *"This phone number (+91XXXXXXXXXX) is not registered with any CaneBot kiosk. Please contact your administrator."*
2. If the database/roster has 0 registered kiosks, the system must never compute geofencing distances or reference ghost kiosks.
