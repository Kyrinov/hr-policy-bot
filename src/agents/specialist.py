from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.base import GenericAgent
from src.agents.prompts.specialist_prompts import get_specialist_prompt, get_validate_mode_prompt
from src.config import get_config
from src.data.db import get_db_manager
from src.data.stopwords import QUERY_STOPWORDS
from src.fetch.case_law import format_case_law_context, get_case_law_index
from src.llm.client import get_specialist_client
from src.models.schemas import CitationItem, PolicyTriple, QueryKISSResult, RetrievalStatus, SpecialistResponse
from src.parsing.graph_query import get_graph_query

if TYPE_CHECKING:
    from src.fetch.engine import FetchEngine

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "policy_registry.json"
_MAX_CONTENT_CHARS = 24_000     # ~6,000 tokens per document
_MAX_INSTRUMENTS_PER_QUERY = 4  # 4 docs × ~6k tokens + prompt + query fits within 32k context
_DOCUMENT_OPENING_CHARS = 3_000
_MIN_QUERY_TERM_LENGTH = 3


_SPECIALIST_METADATA: dict[str, tuple[str, str]] = {
    "staffing": (
        "Staffing & Recruitment Agent",
        "Staffing and recruitment; Student and youth programs",
    ),
    "classification": (
        "Classification & Compensation Agent",
        "Classification; Compensation and benefits",
    ),
    "labour": (
        "Labour Relations Agent",
        "Labour relations and workplace management",
    ),
    "learning": (
        "Learning & Performance Agent",
        "Learning, training and development; Performance management",
    ),
    "equity": (
        "Equity, Diversity & Inclusion Agent",
        "Diversity, equity and inclusion; Employment equity and accessibility",
    ),
    "ohs": (
        "Health, Safety & Wellness Agent",
        "Occupational health and safety",
    ),
    "languages": (
        "Official Languages Agent",
        "Official languages",
    ),
    "governance": (
        "Values, Ethics & HR Governance Agent",
        "Values and ethics; Conflict of interest; HR governance; Executive services; Leave and attendance",
    ),
}


class SpecialistAgent(GenericAgent):
    """Domain specialist that fetches relevant policy content and queries the LLM."""

    def __init__(self, agent_id: str, display_name: str, domain_description: str) -> None:
        super().__init__(
            agent_id=agent_id,
            display_name=display_name,
            domain_description=domain_description,
            system_prompt=get_specialist_prompt(agent_id),
        )
        self._llm_client = get_specialist_client()
        self._config = get_config()
        self._db = get_db_manager()
        self._instruments = self._load_instruments(agent_id)

    def _load_instruments(self, agent_id: str) -> list[dict]:
        with open(_REGISTRY_PATH) as f:
            registry = json.load(f)
        return [r for r in registry if agent_id in r["agent_ids"]]

    async def process(
        self, query_text: str, query_kiss_result: QueryKISSResult | None = None
    ) -> SpecialistResponse:
        """Process a query without a fetch engine (no live retrieval)."""
        return await self.process_with_fetch(query_text, None, query_kiss_result)

    async def process_with_fetch(
        self,
        query_text: str,
        fetch_engine: FetchEngine | None,
        query_kiss_result: QueryKISSResult | None = None,
    ) -> SpecialistResponse:
        """Fetch relevant policy content and query the LLM."""
        attempted = 0
        fetched: list[tuple[dict, str]] = []
        failed: list[str] = []

        graph_triples = await self._try_graph_retrieval(query_kiss_result)
        if len(graph_triples) >= self._config.parsing.validate_mode_threshold:
            raw = await self._llm_validate(graph_triples, query_text)
            await self._save_teacher_notes(graph_triples, raw)
            return self._parse_response(raw, 0, len(graph_triples), [], "validate")

        if fetch_engine and self._instruments:
            to_fetch = self._instruments[:_MAX_INSTRUMENTS_PER_QUERY]
            attempted = len(to_fetch)

            async def fetch_one(instrument: dict) -> tuple[dict, str | None]:
                try:
                    content = await fetch_engine.fetch(instrument["url"])
                    return (
                        instrument,
                        select_relevant_content(content, query_text, _MAX_CONTENT_CHARS),
                    )
                except Exception as e:
                    logger.warning(
                        "Specialist %s failed to fetch %s: %s",
                        self._agent_id, instrument["url"], e,
                    )
                    return (instrument, None)

            results = await asyncio.gather(*[fetch_one(i) for i in to_fetch])
            for instrument, content in results:
                if content:
                    fetched.append((instrument, content))
                else:
                    failed.append(instrument["title"])

        retrieval_context = "\n\n".join(
            part
            for part in [
                self._build_policy_context(fetched),
                self._build_case_law_context(query_text),
            ]
            if part
        )
        user_message = (
            f"QUERY: {query_text}\n\n{retrieval_context}"
            if retrieval_context
            else f"QUERY: {query_text}"
        )

        raw = await self._llm_client.chat(
            system_prompt=self._system_prompt,
            user_message=user_message,
        )

        return self._parse_response(raw, attempted, len(fetched), failed)

    async def _try_graph_retrieval(
        self, query_kiss_result: QueryKISSResult | None
    ) -> list[PolicyTriple]:
        if query_kiss_result is None or query_kiss_result.fallback_triggered:
            return []
        try:
            return await get_graph_query().search_triples_semantic(
                query_entities=query_kiss_result.entities,
                query_verbs=query_kiss_result.verbs,
                agent_id=self._agent_id,
            )
        except Exception as e:
            logger.warning("Graph retrieval failed for %s: %s", self._agent_id, e)
            return []

    async def _llm_validate(self, triples: list[PolicyTriple], query_text: str) -> str:
        user_message = (
            f"QUERY: {query_text}\n\n"
            "EXTRACTED RULES BEGIN\n"
            f"{self._format_triples(triples)}\n"
            "EXTRACTED RULES END\n\n"
            "Respond using the same structured JSON output format as always."
        )
        return await self._llm_client.chat(
            system_prompt=get_validate_mode_prompt(self._agent_id),
            user_message=user_message,
        )

    def _format_triples(self, triples: list[PolicyTriple]) -> str:
        lines: list[str] = []
        for index, triple in enumerate(triples, start=1):
            flags = ", ".join(triple.validation_flags) or "none"
            lines.append(
                f"{index}. Source: {triple.instrument_title} | URL: {triple.source_url}\n"
                f"   Rule: {triple.subject} -- {triple.predicate} "
                f"({triple.deontic_type or 'non-deontic'}) -- {triple.object_}\n"
                f"   Sentence: {triple.sentence_text}\n"
                f"   Validation flags: {flags}"
            )
        return "\n".join(lines)

    async def _save_teacher_notes(self, triples: list[PolicyTriple], raw: str) -> None:
        if not self._config.parsing.teacher_loop_enabled:
            return
        flagged = [triple for triple in triples if triple.validation_flags]
        if not flagged:
            return
        try:
            await self._db.initialize()
            for triple in flagged:
                await self._db.save_rule_refinement(
                    refinement_id=str(uuid.uuid4()),
                    triple_id=triple.triple_id,
                    validation_flag=",".join(triple.validation_flags),
                    llm_correction=raw[:1000],
                    correction_type="nuance",
                    applied_to_rule=None,
                )
        except Exception as e:
            logger.warning("Teacher-loop note save failed for %s: %s", self._agent_id, e)

    def _build_policy_context(self, fetched: list[tuple[dict, str]]) -> str:
        if not fetched:
            return ""
        parts = ["RETRIEVED POLICY CONTENT:\n"]
        for instrument, content in fetched:
            parts.append(f"\n--- {instrument['title']} ({instrument['type']}) ---\n")
            parts.append(f"URL: {instrument['url']}\n\n")
            parts.append(content)
            parts.append("\n")
        return "".join(parts)

    def _build_case_law_context(self, query_text: str) -> str:
        if self._agent_id != "labour":
            return ""
        cases = get_case_law_index().search(query_text, self._agent_id, limit=5)
        return format_case_law_context(cases)

    def _parse_response(
        self,
        raw: str,
        attempted: int,
        retrieved: int,
        failed: list[str],
        grounding_mode: str = "extract",
    ) -> SpecialistResponse:
        retrieval_status = RetrievalStatus(
            instruments_attempted=attempted,
            instruments_successfully_retrieved=retrieved,
            instruments_failed=failed,
        )
        try:
            text = raw.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()
            start = text.find('{')
            if start > 0:
                text = text[start:]
            end = text.rfind('}')
            if end >= 0:
                text = text[:end + 1]
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # Second pass: strip control characters that break the parser
                import re
                sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
                parsed = json.loads(sanitized)
            citations = [CitationItem(**c) for c in parsed.get("citations", [])]
            return SpecialistResponse(
                agent_id=parsed.get("agent_id", self._agent_id),
                findings=parsed.get("findings", raw),
                citations=citations,
                caveats=parsed.get("caveats"),
                scope_flags=parsed.get("scope_flags", []),
                confidence=parsed.get("confidence", "low"),
                retrieval_status=retrieval_status,
                grounding_mode=grounding_mode,
            )
        except Exception as e:
            logger.warning(
                "Failed to parse specialist response for %s: %s — raw: %r",
                self._agent_id, e, raw[:200],
            )
            return SpecialistResponse(
                agent_id=self._agent_id,
                findings=raw,
                citations=[],
                confidence="low",
                retrieval_status=retrieval_status,
                grounding_mode=grounding_mode,
            )


_specialists: dict[str, SpecialistAgent] | None = None


def get_specialists() -> dict[str, SpecialistAgent]:
    """Return singleton dict of all specialist agents."""
    global _specialists
    if _specialists is None:
        _specialists = {
            agent_id: SpecialistAgent(agent_id, display_name, domain)
            for agent_id, (display_name, domain) in _SPECIALIST_METADATA.items()
        }
    return _specialists


def select_relevant_content(content: str, query_text: str, max_chars: int) -> str:
    """Return a compact query-focused excerpt from a potentially large policy document."""
    if len(content) <= max_chars:
        return content

    terms = _query_terms(query_text)
    if not terms:
        return content[:max_chars]

    opening_chars = min(_DOCUMENT_OPENING_CHARS, max(500, max_chars // 4))
    opening = content[:opening_chars].strip()
    budget = max_chars - len(opening) - 500
    if budget <= 0:
        return content[:max_chars]

    blocks = [block.strip() for block in re.split(r"\n\s*\n", content) if block.strip()]
    scored: list[tuple[int, int, str]] = []
    for index, block in enumerate(blocks):
        lower = block.lower()
        score = sum(lower.count(term) for term in terms)
        if score == 0:
            continue
        if re.match(r"^(article|appendix|part|section)\s+[\w\d.\-]+", lower):
            score += 2
        scored.append((score, index, block))

    if not scored:
        return content[:max_chars]

    selected: list[tuple[int, str]] = []
    used = 0
    for _score, index, block in sorted(scored, key=lambda item: (-item[0], item[1])):
        excerpt = block[:4_000]
        if used + len(excerpt) > budget:
            remaining = budget - used
            if remaining < 500:
                continue
            excerpt = excerpt[:remaining]
        selected.append((index, excerpt))
        used += len(excerpt)
        if used >= budget:
            break

    selected.sort(key=lambda item: item[0])
    sections = "\n\n".join(block for _index, block in selected)
    excerpted = (
        "DOCUMENT OPENING\n"
        f"{opening}\n\n"
        "QUERY-RELEVANT EXCERPTS\n"
        f"{sections}"
    ).strip()
    return excerpted[:max_chars]


def _query_terms(query_text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9'-]+", query_text.lower())
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        token = token.strip("'")
        if len(token) < _MIN_QUERY_TERM_LENGTH or token in QUERY_STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
    return terms
