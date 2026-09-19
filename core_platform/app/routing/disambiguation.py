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
Disambiguation Engine.

When SemanticRouter.confidence < 0.75, this engine generates an
interactive clarification message to send back to the user.
"""

from typing import Dict, List


class DisambiguationEngine:
    """Generates user-facing clarification prompts for ambiguous intents."""

    # Human-friendly app labels for the clarification message.
    _APP_LABELS: Dict[str, str] = {
        "temperature_marker": "📷 Temperature & Attendance Check-in",
        "mail_organizer": "📧 Email Triage & Calendar Management",
    }

    @classmethod
    def build_clarification_message(
        cls,
        candidate_apps: List[str],
        confidence: float,
    ) -> str:
        """Build a plain-text or WhatsApp-formatted clarification message.

        Args:
            candidate_apps: Apps that matched the user's request.
            confidence: Router confidence score that triggered disambiguation.

        Returns:
            Human-readable clarification prompt with numbered options.
        """
        options = []
        for i, app_id in enumerate(candidate_apps, start=1):
            label = cls._APP_LABELS.get(app_id, app_id)
            options.append(f"{i}. {label}")

        options_text = "\n".join(options)
        return (
            f"🤔 I'm not sure which service you need (confidence: {confidence:.0%}).\n\n"
            f"Please reply with a number:\n{options_text}"
        )

    @classmethod
    def resolve_selection(cls, user_reply: str, candidate_apps: List[str]) -> str:
        """Resolve a user's disambiguation reply to an app_id.

        Accepts a numeric reply ("1", "2") or a keyword matching the app name.

        Args:
            user_reply: The user's response text.
            candidate_apps: Ordered list of candidate apps shown to the user.

        Returns:
            Resolved app_id, or the first candidate if resolution fails.
        """
        text = user_reply.strip().lower()

        # Numeric selection.
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(candidate_apps):
                return candidate_apps[idx]

        # Keyword match against app_id or label.
        for app_id in candidate_apps:
            label = cls._APP_LABELS.get(app_id, app_id).lower()
            if app_id in text or any(kw in text for kw in label.split()):
                return app_id

        return candidate_apps[0]
