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
Tier 2 Stage A: Hybrid Neuro-Symbolic Context Assembler Node (`context_assembler_node`).

Adheres strictly to v1.3.0 Section 7.2 (Stage A) and REV-01 / REV-08.
Retrieves symbolic EntityFactGraph triples (chronologically superseding older facts),
active CommitmentLedger obligations, and FTS5 + Semantic Chunk citations across
Email, WhatsApp, and Meeting transcripts before draft synthesis.
"""

import re
import time
from typing import Any, Dict, List, Optional

from apps.mail_organizer.graph.state import MailOrganizerState


# [CODE-MARKER: MO-TIER2-01] Stage A Hybrid Neuro-Symbolic Context Assembler
async def context_assembler_node(
    state: MailOrganizerState,
    db_service: Optional[Any] = None,
) -> MailOrganizerState:
    """Assemble cross-channel hybrid context (EntityFactGraph + CommitmentLedger + FTS5 + Semantic Chunks)."""
    t0 = time.perf_counter()

    subject = state.get("subject") or ""
    body = state.get("body") or ""
    tenant_id = str(state.get("tenant_id") or "public")
    user_id = state.get("user_id")

    content = f"{subject}\n{body}"
    entities = re.findall(r"\b((?:PO|INV|PRJ|CR|INC)[-\s#]?\d{2,8})\b", content, re.IGNORECASE)
    norm_entities = sorted({e.upper().replace(" ", "-") for e in entities})

    words = [
        w.lower()
        for w in re.findall(r"[a-zA-Z0-9_\-]{4,}", content)
        if w.lower() not in {"please", "kindly", "thanks", "regards", "hello", "dear", "would", "could", "should", "about", "attached"}
    ]
    query_terms = list(dict.fromkeys(norm_entities + words[:8]))

    bundle: Dict[str, Any] = {
        "entity_facts": [],
        "open_commitments": [],
        "fts_matches": [],
        "semantic_matches": [],
    }
    citations: List[str] = []

    if db_service is not None:
        try:
            bundle = db_service.search_hybrid_context(
                tenant_id=tenant_id,
                user_id=user_id,
                query_terms=query_terms,
                entities=norm_entities if norm_entities else None,
                limit=6,
            )
            for f in bundle.get("entity_facts") or []:
                ch = str(f.get("source_channel") or "EMAIL").capitalize()
                mid = str(f.get("source_msg_id") or f.get("id") or "fact")
                citations.append(f"[{ch} #{mid}]")
            for m in bundle.get("fts_matches") or []:
                ch = str(m.get("source_channel") or "EMAIL").capitalize()
                mid = str(m.get("msg_id") or "fts")
                tag = f"[{ch} #{mid}]"
                if tag not in citations:
                    citations.append(tag)
            for sm in bundle.get("semantic_matches") or []:
                ch = str(sm.get("source_channel") or "EMAIL").capitalize()
                mid = str(sm.get("msg_id") or "sem")
                tag = f"[{ch} #{mid}]"
                if tag not in citations:
                    citations.append(tag)
        except Exception:
            pass

    state["hybrid_context_bundle"] = bundle
    state["citation_ids"] = citations

    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
    trace = list(state.get("pipeline_trace") or [])
    trace.append({
        "node": "context_assembler",
        "duration_ms": duration_ms,
        "facts_count": len(bundle.get("entity_facts") or []),
        "fts_count": len(bundle.get("fts_matches") or []),
        "semantic_count": len(bundle.get("semantic_matches") or []),
        "citations_count": len(citations),
    })
    state["pipeline_trace"] = trace
    return state
