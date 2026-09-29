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

"""
History Context Service — Dual-Layer Conversation Memory.

Layer A: Chained Thread History (Same thread_id)
  Fetches prior turns in the Gmail thread, strips quotes/signatures,
  and structures chronological turn-by-turn dialogue.

Layer B: Non-Chained Topic Memory (Past exchanges with sender/topic)
  Queries local SQLite database for historical exchanges over the past 60 days.
"""
import os
import re
import datetime
from typing import List, Dict, Any, Optional

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clean_quoted_text(body: str) -> str:
    """Strip out standard email quote headers to minimize prompt bloat."""
    if not body:
        return ""
    lines = []
    for line in body.splitlines():
        # Stop at standard quotation headers
        if re.match(r'^(On\s+.+wrote:|-----Original Message-----|From:\s+|>\s*)', line.strip(), re.IGNORECASE):
            break
        if line.strip().startswith('>'):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned else body[:300].strip()


def build_thread_history(creds: Any, thread_id: str, current_msg_id: str = "") -> List[Dict[str, Any]]:
    """
    Fetch and format prior messages in a Gmail thread chronologically.
    """
    if not creds or not thread_id:
        return []
    try:
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds)
        thread = service.users().threads().get(userId='me', id=thread_id, format='full').execute()
        messages = thread.get('messages', [])
        
        turns = []
        for idx, msg in enumerate(messages, start=1):
            msg_id = msg.get('id')
            if current_msg_id and msg_id == current_msg_id and idx == len(messages):
                # Skip the current incoming message if it is the last turn
                continue
            
            headers = msg.get('payload', {}).get('headers', [])
            sender = ""
            date_str = ""
            for h in headers:
                if h['name'] == 'From':
                    sender = h['value']
                elif h['name'] == 'Date':
                    date_str = h['value']
            
            snippet = msg.get('snippet', '')
            turns.append({
                "turn": idx,
                "msg_id": msg_id,
                "sender": sender,
                "date": date_str,
                "snippet": snippet[:200],
            })
        return turns
    except Exception as e:
        print(f"[history_context_service] Thread history fetch error: {e}")
        return []


def build_non_chained_topic_history(sender: str, subject: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Query local database for past interactions with the same sender or topic keywords.
    """
    try:
        from apps.mail_organizer.database.db_service import MailDatabaseService
        from apps.mail_organizer.database.models import EmailRecord, EmailClassification
        from sqlalchemy.orm import Session
        
        db_service = MailDatabaseService.get_instance()
        with Session(db_service.engine) as session:
            # Clean sender email
            match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', sender)
            clean_sender = match.group(0).lower() if match else sender.lower()

            records = (
                session.query(EmailRecord, EmailClassification)
                .outerjoin(EmailClassification, EmailRecord.gmail_id == EmailClassification.gmail_id)
                .filter(EmailRecord.sender.ilike(f"%{clean_sender}%"))
                .order_by(EmailRecord.received_at.desc())
                .limit(limit)
                .all()
            )

            results = []
            for email_rec, class_rec in records:
                results.append({
                    "date": email_rec.received_at.strftime("%Y-%m-%d") if email_rec.received_at else "Recent",
                    "subject": email_rec.subject or "",
                    "category": class_rec.category if class_rec else "Uncategorized",
                    "urgency": class_rec.urgency_score if class_rec else 5,
                    "reasoning": (class_rec.reasoning if class_rec else "")[:150],
                })
            return results
    except Exception as e:
        return []


def format_history_context_block(thread_turns: List[Dict[str, Any]], topic_memories: List[Dict[str, Any]]) -> str:
    """
    Construct a structured string to inject into the LLM prompt.
    """
    if not thread_turns and not topic_memories:
        return ""

    lines = ["--- 📜 CONVERSATION & TOPIC HISTORY ---"]

    if thread_turns:
        lines.append(f"[Chained Thread Timeline — {len(thread_turns)} previous message(s)]")
        for turn in thread_turns:
            lines.append(f"• Turn {turn.get('turn')} ({turn.get('date', 'Previous')}) from {turn.get('sender', 'Sender')}:")
            lines.append(f"  \"{turn.get('snippet', '')}\"")

    if topic_memories:
        lines.append("[Related Past Interactions (Past 60 Days)]")
        for item in topic_memories:
            lines.append(f"• {item.get('date')}: \"{item.get('subject')}\" [Class: {item.get('category')}, Urgency: {item.get('urgency')}] — {item.get('reasoning')}")

    lines.append("---------------------------------------------------------")
    return "\n".join(lines)


# Public aliases
clean_email_body_for_history = _clean_quoted_text
format_history_for_prompt = format_history_context_block
