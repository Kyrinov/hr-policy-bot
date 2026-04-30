from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from src.agents.base import GenericAgent
from src.agents.prompts.specialist_prompts import get_specialist_prompt
from src.llm.client import get_client
from src.models.schemas import CitationItem, RetrievalStatus, SpecialistResponse

if TYPE_CHECKING:
    from src.fetch.engine import FetchEngine

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "policy_registry.json"
_MAX_CONTENT_CHARS = 24_000     # ~6,000 tokens per document
_MAX_INSTRUMENTS_PER_QUERY = 4  # 4 docs × ~6k tokens + prompt + query fits within 32k context

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
        self._llm_client = get_client()
        self._instruments = self._load_instruments(agent_id)

    def _load_instruments(self, agent_id: str) -> list[dict]:
        with open(_REGISTRY_PATH) as f:
            registry = json.load(f)
        return [r for r in registry if agent_id in r["agent_ids"]]

    async def process(self, query_text: str) -> SpecialistResponse:
        """Process a query without a fetch engine (no live retrieval)."""
        return await self.process_with_fetch(query_text, None)

    async def process_with_fetch(
        self, query_text: str, fetch_engine: FetchEngine | None
    ) -> SpecialistResponse:
        """Fetch relevant policy content and query the LLM."""
        attempted = 0
        fetched: list[tuple[dict, str]] = []
        failed: list[str] = []

        if fetch_engine and self._instruments:
            to_fetch = self._instruments[:_MAX_INSTRUMENTS_PER_QUERY]
            attempted = len(to_fetch)

            async def fetch_one(instrument: dict) -> tuple[dict, str | None]:
                try:
                    content = await fetch_engine.fetch(instrument["url"])
                    return (instrument, content[:_MAX_CONTENT_CHARS])
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

        policy_context = self._build_policy_context(fetched)
        user_message = (
            f"QUERY: {query_text}\n\n{policy_context}"
            if policy_context
            else f"QUERY: {query_text}"
        )

        raw = await self._llm_client.chat(
            system_prompt=self._system_prompt,
            user_message=user_message,
        )

        return self._parse_response(raw, attempted, len(fetched), failed)

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

    def _parse_response(
        self, raw: str, attempted: int, retrieved: int, failed: list[str]
    ) -> SpecialistResponse:
        retrieval_status = RetrievalStatus(
            instruments_attempted=attempted,
            instruments_successfully_retrieved=retrieved,
            instruments_failed=failed,
        )
        try:
            text = raw.strip()
            start = text.find('{')
            if start > 0:
                text = text[start:]
            end = text.rfind('}')
            if end >= 0:
                text = text[:end + 1]
            parsed = json.loads(text)
            citations = [CitationItem(**c) for c in parsed.get("citations", [])]
            return SpecialistResponse(
                agent_id=parsed.get("agent_id", self._agent_id),
                findings=parsed.get("findings", raw),
                citations=citations,
                caveats=parsed.get("caveats"),
                scope_flags=parsed.get("scope_flags", []),
                confidence=parsed.get("confidence", "low"),
                retrieval_status=retrieval_status,
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
