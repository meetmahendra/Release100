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
Universal Entity Extractor Skill (`EntityExtractorSkill`).

Stateless cognitive skill that extracts structured entities, identifiers,
metrics, and contact details from unstructured natural-language text.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from core_platform.app.llm.gateway import get_platform_llm_gateway
from core_platform.app.skills.base import BaseSkill

logger = logging.getLogger("core_platform.skills.entity_extractor")


class ExtractedEntities(BaseModel):
    """Container for extracted structured entity values."""

    dates: List[str] = Field(default_factory=list, description="Extracted dates or time references")
    phone_numbers: List[str] = Field(default_factory=list, description="Phone numbers found in text")
    email_addresses: List[str] = Field(default_factory=list, description="Email addresses found in text")
    ticket_ids: List[str] = Field(default_factory=list, description="Project or support ticket IDs (e.g. JIRA-123)")
    numeric_metrics: Dict[str, float] = Field(
        default_factory=dict, description="Named quantities, temperatures, or currency amounts"
    )
    custom_entities: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary custom schema key-values"
    )
    confidence: float = Field(default=0.90, ge=0.0, le=1.0, description="Extraction confidence")


class EntityExtractorSkill(BaseSkill):
    """Hermetic cognitive skill for structured entity extraction."""

    def __init__(self) -> None:
        """Initialize EntityExtractorSkill."""
        super().__init__(skill_name="entity_extractor")

    async def initialize(self) -> None:
        """Initialize skill."""
        pass

    def is_available(self) -> bool:
        """Report availability."""
        return True

    async def extract_entities(
        self,
        text: str,
        *,
        target_schema: Optional[Dict[str, str]] = None,
        context: Optional[str] = None,
        operation_id: Optional[str] = None,
    ) -> ExtractedEntities:
        """Extract structured entities from text.

        Args:
            text: Input unstructured string.
            target_schema: Optional dictionary mapping field_name -> description for custom fields.
            context: Optional domain context.
            operation_id: Optional correlation identifier.

        Returns:
            ExtractedEntities instance with all detected entity types.
        """
        await self.ensure_initialized()

        clean_text = text.strip()
        if not clean_text:
            return ExtractedEntities(confidence=1.0)

        # 1. Deterministic Regex Extraction (Layer 0 Fast Foundation)
        regex_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b", clean_text)
        regex_phones = re.findall(r"\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}", clean_text)
        regex_emails = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", clean_text)
        regex_tickets = re.findall(r"\b[A-Z]{2,8}-\d{1,6}\b", clean_text)

        # 2. AI Structured Extraction via Gateway (if custom target schema provided or complex text)
        custom_extracted: Dict[str, Any] = {}
        if target_schema:
            try:
                gateway = get_platform_llm_gateway()
                schema_desc = json.dumps(target_schema)
                prompt = (
                    "Extract structured entity values from the input text matching this schema:\n"
                    f"{schema_desc}\n\n"
                    f"Context: {context or 'General'}\n"
                    f"Input: {clean_text[:1500]}\n\n"
                    "Return a single JSON object with the extracted fields. If a field is missing, set its value to null."
                )
                res = await gateway.generate(
                    task="text_generation",
                    prompt=prompt,
                    temperature=0.0,
                    operation_id=operation_id or "op_entity_extract",
                )
                if res and isinstance(res, dict):
                    custom_extracted = {k: v for k, v in res.items() if v is not None}
            except Exception as exc:
                logger.warning("[EntityExtractorSkill] AI extraction failed, using regex: %s", exc)

        return ExtractedEntities(
            dates=list(set(regex_dates)),
            phone_numbers=list(set(regex_phones)),
            email_addresses=list(set(regex_emails)),
            ticket_ids=list(set(regex_tickets)),
            custom_entities=custom_extracted,
            confidence=0.95 if custom_extracted or (regex_dates or regex_phones or regex_tickets) else 0.85,
        )
