# ARCHITECTURAL DECISION RECORD (ADR)
## ISSUE-002: Conversational Ingress, Operator-to-Manager Dispatch, and Tagging Architecture

```
Issue ID       : ISSUE-002
Title          : Conversational Ingress Intent Inference, Anti-Spoofing & Operator-to-Manager Dispatch
Severity       : Medium (Architecture & UX Refinement)
Component      : core_platform/app/ingress/whatsapp_router.py, apps/temperature_marker/
Status         : PROPOSED / BACKLOGGED (Pending Implementation Phase)
Author         : Mahendra GURAV / Antigravity AI Pair
Date           : September 19, 2026
Standard Ref   : GEES v1.0 Standard, Pillar 1 (Fail-Safe Defaults) & Pillar 4 (Zero-Trust)
```

---

## 1. Context & Background

During field trials of the **CaneBot Attendance & Temperature Marker** at live retail kiosks (e.g. `CANEBOT-PUNE-05` at Dassault Systèmes Sky Tower), multiple operational nuances were observed regarding how operators communicate through the Meta WhatsApp Business API ingress.

Currently, all inbound interactions not explicitly matching `/mail` or `/register` are treated as attendance or chiller verification attempts. This creates friction when operators wish to send general operational queries, report maintenance issues, or message supervisors.

---

## 2. Issues & Requirements Documented

### 2.1 Geolocation Prompt Frequency
* **Observation:** The bot repeatedly sends the 1-click GPS location link (`/loc?session=...`) whenever cached coordinates expire or are missing.
* **Target Behavior:** The 1-click location link must be prompted **at most once per day per operator**, unless the operator explicitly requests it (e.g. typing `"location"` or `"link"`).

### 2.2 Intent Inference (Separating Attendance from Operational Messages)
* **Observation:** Not every message from an operator is an attendance submission. Forcing attendance validation on arbitrary notes causes spurious rejections.
* **Target Behavior:** The ingress router must infer intent:
  1. `ATTENDANCE_CHECKIN`: Explicit duty keywords or photos containing registered operator selfie.
  2. `OPERATOR_QUERY`: Operational notes, requests for supplies, or questions.
  3. `MANAGER_GREETING`: Manager initiating shift triage (`"Hi"`, `"Hello"`).

### 2.3 Attendance Capture Trust Model & Shift Window
* **Decision:** Operators are trusted to capture attendance selfies and chiller readouts using the native WhatsApp in-app camera during shift operations.
* **Requirements:**
  * Initial shift check-in requires a front-facing selfie of the registered operator.
  * Periodic chiller temperature checks may use back camera or front camera.
  * Both timestamp and geofencing are bound to the operator's scheduled shift window.

### 2.4 Tagging vs. Hierarchical Reporting Manager Routing
* **Technical Constraint Evaluated:** Meta WhatsApp Cloud API accounts are designed for 1-on-1 direct conversations and **cannot join regular user WhatsApp group chats**. In a 1-on-1 direct chat, native WhatsApp contact tagging (`@contact` picker) does not exist.
* **Decision:** Drop arbitrary `@person` tagging in 1-on-1 chat to avoid awkward manual phone typing or brittle nickname parsing.
* **Approved Alternative (Hierarchy Routing):**
  * All non-attendance operator queries and notes automatically route to the operator's assigned **Direct Reporting Manager / Supervisor**.
  * The message is attributed with operator name, employee code, and kiosk location.
  * Two-way reply context: When the manager replies, the bot relays the response back to the operator quoting the original message (`Re: "[original note]"`).

### 2.5 Subsequent Photo Handling (Self vs. Mismatch/Other)
* **Operator sends their own photo again:** Inform them: *"Shift attendance is already marked for today."* (Allow periodic chiller update if gauge is legible).
* **Operator sends another person's photo, face mismatch, or out-of-context image:**
  * **Zero False Attribution:** Never mark attendance under the registered operator's name.
  * Divert the anomaly directly to the manager's review queue for manual inspection.

### 2.6 Manager Review Digest & Interactive Triage
* When a manager sends `"Hi"` or completes manager attendance:
  * Display a **prioritized, single-screen summary of top 10 pending messages** (using concise one-liner summaries).
  * Deliver Message 1 in full so the manager can reply immediately.
  * Support batch view on demand (`"ALL"`).
* **Urgent Alert Bypass:** For critical equipment breakdowns or HACCP hazards, dispatch an approved Meta Template Message without waiting for the 24-hour conversational window.

---

## 3. Implementation Roadmap & Deferred Scope

| Component | Scope | Priority |
| :--- | :--- | :---: |
| `layer0_location_node.py` | 1-Click link rate-limiting (max 1x/day) | High |
| `layer1_face_node.py` | Distinguish duplicate own-photo vs mismatch anomaly | High |
| `intent_router.py` | Deterministic intent classifier (Attendance vs Note vs Greeting) | Medium |
| `internal_dispatch.py` | Operator-to-Manager queue, single-screen digest & two-way quote relay | Medium |
| Meta Template Dispatcher | Urgent hazard push notifications outside 24h window | Medium |

---

## 4. Next Steps
When ready to implement, reference this document (`issues/ISSUE-002_conversational_ingress_and_manager_dispatch.md`).
