# ENHANCEMENT-001: Multi-Role Support (Simultaneous Operator & Manager Capabilities)

**Status:** PROPOSED / LOGGED TO BACKLOG  
**Severity:** FEATURE ENHANCEMENT  
**Component:** `core_platform.app.ingress` / `core_platform.app.database` / `apps.temperature_marker`  
**Date Logged:** 2026-09-24  
**Author:** AI Pair Programmer / Mahendra Gurav  

---

## 1. Executive Summary & Business Rationale

In real-world retail, Quick Service Restaurant (QSR), and automated food/beverage kiosk networks (e.g., CaneBOT), staff responsibilities are fluid:
- **Kiosk Leads & Shift Supervisors** simultaneously operate a physical machine (performing morning attendance, submitting chiller HACCP logs, dispensing beverages) while supervising junior operators across multiple kiosks or shifts.
- Currently, the system models employee hierarchy via a rigid, mutually exclusive scalar string: `role: 'OPERATOR' | 'MANAGER' | 'ADMIN'`.
- If an employee is set to `OPERATOR`, they cannot triage subordinate inquiries or receive manager digests over WhatsApp.
- If set to `MANAGER`, the system expects them to be remote, impairing local attendance verification and kiosk-specific HACCP telemetry.

**Objective:** Enable a person to possess dual capabilities (**Operator + Manager**) seamlessly without cognitive friction or role collisions.

---

## 2. Technical Architecture & Data Model

### 2.1 Dynamic Capability Model vs Rigid Role Enums
Instead of a single scalar role string, an employee's capabilities are determined through:
1. **Explicit Multi-Role Assignment:**
   - Database field: `roles TEXT` (JSON-encoded list, e.g., `["OPERATOR", "MANAGER"]`) or relational table `employee_roles(emp_code, role)`.
2. **Implicit / Dynamic Inference (Zero-Config Fallback):**
   - Even if `role = 'OPERATOR'`, if an employee has one or more subordinates registered with `reporting_manager_emp_code == emp.emp_code`, the system automatically infers `is_manager = True`.
   - Formula:
     $$\text{IsManager}(emp) \iff \text{"MANAGER"} \in emp.\text{roles} \lor \text{Count}(\text{Subordinates}(emp.\text{emp\_code})) > 0$$

### 2.2 Relational Integrity
- An employee can have an assigned kiosk (`assigned_kiosk_id`) for operator duties.
- The same employee can also be designated as the `reporting_manager_emp_code` for team members.
- Circular reporting lines are prevented at DB validation time:
  $$\text{reporting\_manager\_emp\_code} \neq \text{emp\_code} \quad \text{and} \quad \text{CycleCheck}(G) = \text{False}$$

---

## 3. Conversational UX & Intent Disambiguation on WhatsApp

Dual-role users interact through a single WhatsApp number. The ingress router disambiguates intent contextually based on message modality and payload:

### 3.1 Unambiguous Action Routing
| Incoming Modality / Payload | Inferred Context | Target Pipeline |
| :--- | :--- | :--- |
| **GPS Location Pin** | Operator | Kiosk Geofence & Shift Check-In |
| **Selfie / Face Photo** | Operator | Biometric Attendance Verification |
| **Gauge / Chiller Temperature Photo** | Operator | Vision OCR HACCP Thermal Logging |
| **Ticket Quoted Reply** (e.g., *"Restock arriving in 20 mins"*) | Manager | Operational Queue Resolution & Push to Operator |
| **Triage Navigation Keywords** (`"NEXT"`, `"ALL"`, `"QUEUE"`) | Manager | Team Message Queue Triage |

### 3.2 Unified Composite Greeting UX
When a dual-role employee sends `"Hello"`, `"Hi"`, or `"Status"`, rather than picking only one persona, the bot returns a **Unified Composite Dashboard**:

```text
👋 Namaste Mahendra Gurav (EMP-1001)
Role: Lead Operator & Supervisor | CaneBOT Eka Elitas

📍 PERSONAL SHIFT STATUS:
• Attendance: ✅ Checked-in at 09:15 AM (On-Time)
• Chiller Temp: ⚠️ Missing (Required by 11:00 AM)
👉 Send chiller photo or location pin to update.

----------------------------------------
📬 TEAM TRIAGE INBOX (1 Pending Action):
From: Dnyaneshwari Gurav (EMP-1002 - CaneBOT Eka Elitas)
Ref: MSG-1 (Priority: 50)
"The cups are about to be empty"
----------------------------------------
👉 Reply directly to this message to send instructions to Dnyaneshwari.
Type 'NEXT' to skip, or 'ALL' to view all pending messages.
```

---

## 4. Web UI & Fleet Management Impact

1. **Staff Enrollment Modal (`fleet.html` & `routes.py`):**
   - Replace single `<select name="role">` with multi-select capability checkboxes:
     - `[x] Kiosk Operator` (Enables assigned kiosk, attendance, HACCP logs)
     - `[x] Shift Manager / Supervisor` (Enables team inbox, escalation alerts)
2. **Subordinate Assignment Dropdown:**
   - Allows selecting any employee with Manager capability as the reporting supervisor.

---

## 5. Backward Compatibility & Compliance

- **Single-Role Operators:** Receive standard clean Operator greeting.
- **Pure Remote Managers:** Receive standard Manager Triage greeting without kiosk attendance prompts.
- **Safety Pre-Gate (Layer 0):** Zero disruption to VIP whitelists or hardcoded sanity boundaries.
- **Audit Logging:** Tri-format audit logs (`.jsonl`, `.csv`, `.html`) record the effective active persona for each transaction.

---

## 6. Implementation Prerequisites
- Implement after resolving `ISSUE-008` (Manager Push Notification & Inverted Triage Classification).
