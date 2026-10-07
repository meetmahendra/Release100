# ISSUE-008: Manager Push Notification Omission and Inverted Role Triage Classification

**Status:** LOGGED / BACKLOG  
**Severity:** HIGH  
**Component:** `core_platform.app.ingress.whatsapp_router` / `core_platform.app.ingress.intent_router` / `apps.temperature_marker.ui.routes`  
**Date Logged:** 2026-09-24  

---

## 1. Problem Description

### Defect 8.1: No WhatsApp Push Delivered to Manager on Operator Message
When an operator sends an operational message via WhatsApp (e.g., `"The cups are about to be empty"`), the bot returns an immediate confirmation to the operator:
```text
📦 Message Dispatched to Mahendra Gurav (EMP-1001)
Machine: KioskNode Eka Elitas
----------------------------------------
"The cups are about to be empty"
----------------------------------------
Priority: 50 | Ref: MSG-1
Your manager has been notified and will reply directly.
```
**Actual Behavior:** The manager's phone (`+918087545430`) never receives any WhatsApp notification or push message.

### Defect 8.2: Manager Greeting Inverted into Operator Duty Greeting with Misattributed "Supervisor Instruction"
When the manager attempts to query the bot by sending `"Hello"` or `"Hi"`:
1. The bot responds with an **Operator Duty Check-in** greeting (showing attendance status, location link, and chiller status).
2. The operator's pending message (`"The cups are about to be empty"`) is mislabeled and presented back to the manager as:
   `📬 Supervisor Instruction: "The cups are about to be empty"`.
3. The expected manager triage instructions (*"Reply to answer directly, send 'NEXT' to skip, or 'ALL' to view all"*) are completely missing.

---

## 2. Root Cause Analysis

### 2.1 Lack of Outbound Push for Regular Priority Messages
- In [`core_platform/app/ingress/whatsapp_router.py`](file:///D:/Release100/core_platform/app/ingress/whatsapp_router.py#L705-L714), outbound delivery to the manager is guarded by:
  ```python
  if intent_result.priority >= 100:
      await send_urgent_meta_template_alert(...)
  ```
- Any message with `priority < 100` is solely enqueued into SQLite (`internal_message_queue` with `status='QUEUED'`). No outbound WhatsApp message (`send_whatsapp_raw_message`) is ever dispatched to `mgr_phone`.
- This creates an architectural disconnect: the system promises the operator that *"Your manager has been notified"*, but relies entirely on a passive "pull" model where the manager must proactively message the bot.

### 2.2 Inverted Role Inference & Missing Role Field in Web UI
- In [`apps/temperature_marker/ui/routes.py`](file:///D:/Release100/apps/temperature_marker/ui/routes.py) and `fleet.html`, the member enrollment API does not expose a `role` field and defaults all enrolled employees to `role = 'OPERATOR'`.
- Consequently, manager accounts (such as `EMP-1001`) are persisted with `role = 'OPERATOR'`.
- In [`core_platform/app/ingress/intent_router.py`](file:///D:/Release100/core_platform/app/ingress/intent_router.py#L144), `is_manager_role` only checks:
  ```python
  is_manager_role = sender_role.upper() in ["SUPERVISOR", "MANAGER", "ADMIN"]
  ```
- Because `sender_role` is `'OPERATOR'`, `is_manager_role` evaluates to `False`. The router fails to recognize that `EMP-1001` has subordinate operators reporting to him in the database.
- As a result:
  1. The manager's `"Hello"` is classified as `OPERATOR_GREETING` instead of `MANAGER_GREETING`.
  2. `OPERATOR_GREETING` inspects `internal_message_queue` for messages where `recipient_phone == sender_phone`. Finding the operator's message (`MSG-1`), it erroneously presents it as an incoming `📬 Supervisor Instruction`.
  3. The interactive triage digest (`build_top10_digest()`) is bypassed, omitting all navigation and reply instructions.

---

## 3. Desired Behavior & Resolution Plan (For Future Implementation)

1. **Real-Time Outbound Push Notification**:
   - Immediately upon enqueuing an operator note in `whatsapp_router.py`, dispatch an outbound WhatsApp message to `mgr_phone` via `send_whatsapp_raw_message()`, alerting the manager in real time with the operator's note and direct reply prompt.
2. **Dynamic Manager Role Detection**:
   - In `intent_router.py`, determine manager status dynamically:
     ```python
     is_manager_role = (
         sender_role.upper() in ["SUPERVISOR", "MANAGER", "ADMIN"]
         or db_service.has_subordinates(sender_emp_code)
         or db_service.is_assigned_kiosk_manager(sender_phone)
     )
     ```
3. **Explicit Role Assignment in Fleet UI**:
   - Add a `Role` dropdown in `apps/temperature_marker/ui/templates/fleet.html` (`Operator` vs `Fleet Supervisor / Manager`), passing `role` through `CreateMemberRequest` and `register_employee()`.
4. **Clean Triage Digest Flow**:
   - When a manager texts `"Hello"`, execute `build_top10_digest()` to render the prioritized digest and step-by-step 1-by-1 reply prompts.
