<!--
Copyright 2026 Mahendra GURAV

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Release100 Platform — End-User & Operator Manual

> **Document Version:** 1.3.0  
> **Target Audience:** Field Operators, Depot Supervisors, Plant Managers, Project Coordinators  
> **Author:** Platform Engineering Team  
> **Copyright:** © 2026 Mahendra GURAV  

---

## 1. Welcome to Release100

**Release100** provides an automated, intelligent companion for factory floor operations and office project management. Using standard WhatsApp messages and simple web dashboards, you can:
* Log chiller temperatures and operator check-ins using smartphone photos.
* Verify physical presence via 1-click GPS geofence links.
* Triage incoming emails and dispatch actionable tasks to project management tools.
* Approve or reject project management actions on the go directly from WhatsApp.

---

## 2. WhatsApp Field Operator Workflows

All operator interactions can be performed by chatting directly with the official **Release100 WhatsApp Business Number**.

```
  Field Operator                   WhatsApp Business                  Release100 Platform
       │                                   │                                   │
       │─── 1. Send Chiller Photo ────────>│                                   │
       │                                   │─── 2. Stream to Relay ───────────>│ (Display OCR Skill)
       │                                   │                                   │ (Check Sanity: -30°C to +50°C)
       │<── 3. "Reading: 4.2°C [OK]" ──────│<─── [Pass / Fail Response] ───────│
       │                                   │                                   │
       │─── 4. Send Location /loc ────────>│                                   │
       │                                   │─── 5. Geofence Verification ─────>│ (Haversine Distance < 200m)
       │<── 6. "Attendance Marked: OK" ────│<─── [Verified Response] ──────────│
```

---

### 2.1 Daily Shift Check-in & Temperature Logging
1. **Take a Clear Photo:** Take a photo of the cold-room or chiller digital display. Ensure the LED/LCD numbers are legible.
2. **Send via WhatsApp:** Send the photo directly to the Release100 WhatsApp contact.
3. **Automated Verification:**
   * **Skill Execution:** The `DisplayOCRSkill` extracts the numerical value and unit (°C).
   * **Sanity Boundary:** The system deterministically verifies that the reading is physically realistic (-30.0°C to +50.0°C).
   * **Cold-Chain Rule:** For chillers, temperatures must be within compliant limits ($2.0^\circ\text{C} - 8.0^\circ\text{C}$).
4. **Immediate Confirmation:** You will receive a reply within 2–3 seconds:
   > *"✅ Chiller #04 logged: **4.2°C**. Shift Check-in verified for John Doe. Have a safe shift!"*

---

### 2.2 Geofence Location Verification (1-Click Link)
If your check-in requires physical presence confirmation:
1. The bot will send a 1-click verification link:
   > *"📍 Please verify your depot location: http://kiosk-ip:8000/loc"*
2. Tap the link on your mobile browser.
3. Tap **"Allow Location Access"** when prompted by your phone.
4. The web page captures your high-accuracy GPS coordinates, verifies you are within the 200m geofence radius of your assigned depot, and marks your attendance record in the cryptographic audit ledger.

---

### 2.3 Interactive Commands Cheatsheet

Send any of the following text commands to WhatsApp:

| Command | Action | Example |
| :--- | :--- | :--- |
| `help` or `/help` | Displays the platform command menu and active applications. | `help` |
| `status` | Checks kiosk status, active shift, and connectivity. | `status` |
| `mail <text>` | Forwards email subject & body into the AI triage engine. | `mail Urgent: Motor replacement quotes required` |
| `#email <text>` | Alternative trigger for email triage. | `#email Client feedback on CaneBot Batch 4` |
| `approve <task_id>` | Approves a proposed PM task or urgent email action. | `approve TASK-104` |
| `reject <task_id>` | Rejects or dismisses a proposed PM task. | `reject TASK-104` |

---

## 3. Email Triage & Project Management Workflows

Release100 includes the **Mail Organizer** cartridge, powered by LangGraph state workflows and Gemini intelligence, to automate email organization and task tracking.

### 3.1 Automatic Email Triage
When an email is forwarded to the platform:
1. **Classification:** Categorized as `Urgent`, `Action Required`, `Informational`, `Follow-up`, or `Spam`.
2. **Summary:** A concise 2-sentence executive summary is generated.
3. **PM Task Proposal:** If an action item is identified (e.g. *“Order replacement filter by Friday”*), a structured PM task is prepared with priority and due date.
4. **WhatsApp Alert:** If high urgency, an alert is pushed to the plant supervisor's WhatsApp:
   > *"⚠️ Urgent Email from Vendor: 'Spare parts delayed'. Proposed PM Task: **TASK-202** (Investigate alternate supplier). Reply `approve TASK-202` or `reject TASK-202`."*

---

## 4. Web Administration Dashboards

Supervisors and managers can access visual dashboards from any browser on the local depot network: `http://<kiosk-ip>:8000/`.

### 4.1 Temperature Marker Fleet Dashboard
* **URL:** `http://localhost:8000/admin/apps/temperature-marker/fleet`
* **Features:**
  * **Live Fleet Status:** Real-time cards for all depot chillers, displays, and sensors.
  * **Review Queue:** Any OCR or face match with confidence below 85% is held in the **Admin Review Gate**. Supervisors can manually approve or override readings with one click.
  * **Temperature Trends:** Visual graphs showing 24-hour temperature stability against target compliance thresholds ($2^\circ\text{C} - 8^\circ\text{C}$).

### 4.2 Mail Organizer Dashboard
* **URL:** `http://localhost:8000/admin/apps/mail-organizer/dashboard`
* **Navigation Tabs:**
  * **Triage Feed (`/triage`):** Live stream of incoming classified emails, confidence scores, and action items.
  * **PM Task Queue (`/pm-queue`):** Kanban-style board showing pending, approved, and synchronized project management tasks.
  * **Draft Responses (`/drafts`):** AI-generated professional email replies awaiting supervisor review before sending.
  * **Triage Rules (`/rules`):** Custom VIP sender rules and routing policies.

---

## 5. Mobile Operator Self-Service Geolocation (`/loc`)

If WhatsApp does not automatically transmit your physical location when sending an attendance photo:
1. You will receive an automated reply containing a secure one-time verification link:
   ```text
   📍 Location Verification Required:
   https://kiosk.domain.com/loc?session=TOKEN
   ```
2. Tap the link in WhatsApp to open the verification page on your mobile browser.
3. Tap **"Share Current Location"** and grant browser location permissions when prompted.
4. Once verified within your kiosk's geofence, your duty check-in is instantly confirmed without needing to resend your photo.

---

## 6. Safety & Quality Assurance (GEES v1.0)

Release100 follows strict safety guidelines to prevent mistakes:
* **Zero Autonomous Destruction:** The AI cannot delete emails, remove database records, or drop tasks autonomously.
* **Human-in-the-Loop Threshold (<85%):** If a photo is blurry, dark, or partially obscured, the system does not guess. It notifies the operator to re-take the photo and flags the record for manual supervisor review.
* **Cryptographic Tamper-Proof Audit:** Every log is sealed with SHA-256 encryption, ensuring records cannot be modified after the fact (FDA 21 CFR Part 11 / ISO 22000 compliant).

---

## 7. Support & Escalation

* **Depot Support Hotline:** Contact your local site IT or Plant Automation team.
* **Platform Administration:** Platform Operations Team (`ops@canebot.internal`)
* **Feedback & Feature Requests:** Submit via the Admin Dashboard feedback modal.
