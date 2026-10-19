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
Omnichannel Context Ingestor & Wiretapping Compliance Gate (`omnichannel_ingestor.py`).

Adheres strictly to v1.3.0 Section 6 (Omnichannel Ingestion) and REV-08 / REV-09.
Enforces deterministic CIPA / GDPR / India DPDP consent verification before indexing
WhatsApp notes, Slack threads, or Meeting/Call transcripts into the Hybrid Neuro-Symbolic
Store (FTS5 + Semantic Chunks + EntityFactGraph + CommitmentLedger).
"""

import re
from typing import Any, Dict, List, Optional

from apps.mail_organizer.database.db_service import MailDatabaseService


# [CODE-MARKER: MO-OMNI-01] Omnichannel Context Ingestor & Consent Gate
class OmnichannelContextIngestor:
    """Ingests cross-channel context (WhatsApp, Slack, Meeting Transcripts) with strict consent gating."""

    def __init__(self, db_service: Optional[MailDatabaseService] = None) -> None:
        """Initialize with MailDatabaseService."""
        self.db_service = db_service or MailDatabaseService()

    def ingest_omnichannel_event(
        self,
        session_id: str,
        channel_type: str,
        subject: str,
        transcript_or_text: str,
        participants: List[str],
        jurisdiction_policy: str = "ALL_PARTY",
        all_parties_consented: bool = True,
        tenant_id: str = "public",
        user_id: Optional[int] = None,
        entity_tags: str = "",
    ) -> Dict[str, Any]:
        """Verify consent, record cryptographic proof, and extract facts/commitments into Hybrid Store."""
        norm_channel = channel_type.strip().upper()
        norm_policy = jurisdiction_policy.strip().upper()

        # 1. Record immutable ConsentAuditLog (REV-09)
        consent_rec = self.db_service.record_consent_audit_log(
            session_id=session_id,
            channel_type=norm_channel,
            jurisdiction_policy=norm_policy,
            participants=participants,
            all_parties_consented=all_parties_consented,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        # Enforce strict All-Party Consent Gate for recorded meetings/calls (CIPA / GDPR / DPDP)
        if norm_channel in ("MEETING_TRANSCRIPT", "CALL_SUMMARY", "VOICE_NOTE") or norm_policy == "ALL_PARTY":
            if not all_parties_consented:
                raise PermissionError(
                    f"Omnichannel ingestion blocked for session '{session_id}': "
                    "All-party consent proof required under CIPA/GDPR/DPDP."
                )

        # 2. Index into FTS5 + Semantic Chunk Store
        self.db_service.index_fts_and_semantic_chunk(
            tenant_id=tenant_id,
            user_id=user_id,
            source_channel=norm_channel,
            msg_id=session_id,
            subject=subject,
            body_clean=transcript_or_text,
            entity_tags=entity_tags,
        )

        # 3. Extract and supersede Symbolic EntityFactGraph triples
        content = f"{subject}\n{transcript_or_text}"
        entity_matches = re.findall(r"\b((?:PO|INV|PRJ|CR|INC)[-\s#]?\d{2,8})\b", content, re.IGNORECASE)
        primary_entity = (
            entity_matches[0].upper().replace(" ", "-")
            if entity_matches
            else (entity_tags.split(",")[0].strip() if entity_tags else subject[:40].strip() or "OMNI-TOPIC")
        )

        facts_recorded: List[Dict[str, Any]] = []
        amt_match = re.search(r"(\$\s?\d[\d,]*(?:\.\d{1,2})?(?:\s?[kKmM])?|INR\s?\d[\d,]*)", content)
        if amt_match:
            f_amt = self.db_service.upsert_entity_fact(
                subject_entity=primary_entity,
                predicate="AMOUNT",
                object_value=amt_match.group(1).strip(),
                source_msg_id=session_id,
                source_channel=norm_channel,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            facts_recorded.append({"id": f_amt.id, "predicate": "AMOUNT", "value": f_amt.object_value})

        eta_match = re.search(
            r"(?:delivery|eta|deadline|due|revised\s+to|pushed\s+to)\s*(?:date|is|on|by|:)?\s*(\d{4}-\d{2}-\d{2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}|friday|monday|tomorrow)",
            content,
            re.IGNORECASE,
        )
        if eta_match:
            f_eta = self.db_service.upsert_entity_fact(
                subject_entity=primary_entity,
                predicate="DEADLINE_OR_ETA",
                object_value=eta_match.group(1).strip(),
                source_msg_id=session_id,
                source_channel=norm_channel,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            facts_recorded.append({"id": f_eta.id, "predicate": "DEADLINE_OR_ETA", "value": f_eta.object_value})

        # 4. Extract verbal commitments into CommitmentLedger
        commitments_recorded: List[str] = []
        promise_match = re.search(
            r"(?:i\s+will|i'll|we\s+will|agreed\s+to|promised\s+to)\s+([^\.\n\?]{5,120})",
            content,
            re.IGNORECASE,
        )
        if promise_match:
            counterparty = participants[0] if participants else "Omnichannel Participant"
            c_rec = self.db_service.upsert_commitment(
                source_msg_id=session_id,
                deliverable_summary=promise_match.group(0).strip()[:200],
                direction="OWED_TO_ME",
                speech_act="COMMIT",
                source_channel=norm_channel,
                counterparty_handle=counterparty,
                raw_deadline_text=eta_match.group(1).strip() if eta_match else "Next Business Day",
                tenant_id=tenant_id,
                user_id=user_id,
            )
            commitments_recorded.append(c_rec.commitment_uid)

        return {
            "success": True,
            "session_id": session_id,
            "channel_type": norm_channel,
            "consent_proof_hash": consent_rec.consent_proof_hash,
            "facts_recorded": facts_recorded,
            "commitments_recorded": commitments_recorded,
        }

    def query_hybrid_context(
        self,
        query: str,
        tenant_id: str = "public",
        user_id: Optional[int] = None,
        entities: Optional[List[str]] = None,
        limit: int = 8,
    ) -> Dict[str, Any]:
        """Execute Hybrid Neuro-Symbolic Retrieval across EntityFactGraph, CommitmentLedger, FTS5, and Semantic Chunks."""
        terms = [t.strip() for t in re.split(r"[\s,;]+", query) if t.strip()]
        res = self.db_service.search_hybrid_context(
            tenant_id=tenant_id,
            user_id=user_id,
            query_terms=terms,
            entities=entities,
            limit=limit,
        )
        return {
            "success": True,
            "query": query,
            "entity_facts": res.get("entity_facts", []),
            "open_commitments": res.get("open_commitments", []),
            "fts_matches": res.get("fts_matches", []),
            "semantic_matches": res.get("semantic_matches", []),
        }

