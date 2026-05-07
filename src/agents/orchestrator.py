from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable

from src.agents.base import GenericAgent
from src.agents.prompts.specialist_prompts import get_specialist_prompt
from src.config import get_config
from src.llm.client import get_orchestrator_client, get_specialist_client
from src.models.schemas import (
    DeterministicGrounding,
    OrchestratorCitation,
    OrchestratorResponse,
    RetrievalStatus,
    WSAgentStatusUpdate,
)
from src.parsing.query_kiss_parser import QueryKISSParser

if TYPE_CHECKING:
    from src.fetch.engine import FetchEngine

logger = logging.getLogger(__name__)


ORCHESTRATOR_PROMPT = """You are the Orchestrator Agent for the DND HR-Civ Multi-Agent Policy Advisory System. Your role is to coordinate specialist policy agents to provide comprehensive, accurate, and well-referenced HR policy guidance.

You manage 8 specialist agents:
- staffing: Staffing & Recruitment (incl. student programs)
- classification: Classification & Compensation (incl. collective agreements)
- labour: Labour Relations & Workplace Management
- learning: Learning, Training & Performance Management
- equity: Equity, Diversity & Inclusion (incl. accessibility)
- ohs: Health, Safety & Wellness
- languages: Official Languages
- governance: Values, Ethics, HR Governance, Executive Services & Leave

WORKFLOW:
1. ANALYZE the user's query. Identify which HR policy domains are implicated.
   Many real-world questions span multiple domains — be thorough.
2. SELECT which specialist agents to invoke. Provide a brief rationale.
3. FORMULATE a focused sub-query for each selected agent, tailored to extract
   the specific policy information needed from that domain.
4. After receiving specialist responses, SYNTHESIZE a unified answer that:
   a. Opens with a direct, natural-language answer to the user's question
   b. Integrates findings across all consulted specialists
   c. Identifies any tensions or conflicts between policy instruments
   d. Presents all citations in a consolidated reference list
   e. Notes any gaps — areas the question touches that the agents could not
      fully address
   f. Where professional judgment or management discretion is required,
      states this explicitly rather than presenting interpretation as settled policy

TONE: Professional, precise, and accessible. Write for an experienced HR advisor
who values accuracy and completeness but does not want to read a legal brief.
Use plain language. Avoid jargon unless it is the established term of art in
federal HR (in which case, use it precisely).

EPISTEMIC STANDARDS:
- Distinguish clearly between what the policy STATES, what it IMPLIES, and what
  is a matter of INTERPRETATION or DISCRETION.
- If specialist agents report low confidence or retrieval failures, disclose this
  to the user.
- Never present general HR knowledge as if it were a specific policy provision.
- When in doubt, recommend consultation with the relevant functional specialist
  (e.g., "This question may benefit from consultation with your labour relations
  advisor").

CRITICAL — OUTPUT FORMAT: Respond with ONLY a valid JSON object. Do not write any text, preamble, or explanation outside the JSON. The JSON must match this structure exactly:
{
  "summary": "string — the direct answer in natural language (2-4 sentences)",
  "detailed_analysis": "string — the full multi-layered analysis integrating all specialties",
  "policy_tensions": "string or null — any identified conflicts between instruments",
  "citations": [
    {
      "instrument_title": "string",
      "instrument_type": "string",
      "url": "string",
      "relevant_section": "string or null",
      "sourced_from_agent": "string — agent_id"
    }
  ],
  "gaps_and_limitations": "string or null",
  "recommended_consultation": "string or null",
  "agents_consulted": ["string — list of agent IDs"],
  "overall_confidence": "high | medium | low"
}

Begin your synthesis directly with the JSON object. Do not include any preface, introductory text, or text outside the JSON.
"""


class OrchestratorAgent(GenericAgent):
    """
    Orchestrator agent that routes queries to specialists and synthesizes responses.

    The orchestrator operates in two phases:
    1. Routing: Determines which specialist agents to invoke and formulates sub-queries
    2. Synthesis: Combines specialist responses into a unified answer
    """

    def __init__(self) -> None:
        self._config = get_config()
        self._llm_client = get_orchestrator_client()

        super().__init__(
            agent_id="orchestrator",
            display_name="Orchestrator Agent",
            domain_description="Routes queries to specialists and synthesizes responses",
            system_prompt="",  # Overridden in methods
        )

        self._specialist_agent_ids = [
            "staffing",
            "classification",
            "labour",
            "learning",
            "equity",
            "ohs",
            "languages",
            "governance",
        ]

    async def process(
        self,
        query_text: str,
        specialist_responses: list[dict[str, Any]],
    ) -> OrchestratorResponse:
        """
        Synthesize specialist responses into a unified answer.

        Args:
            query_text: The original user query
            specialist_responses: List of responses from specialist agents

        Returns:
            OrchestratorResponse with synthesized analysis
        """
        prompt = self._build_synthesis_prompt(query_text, specialist_responses)

        response_text = await self._llm_client.chat(
            system_prompt=ORCHESTRATOR_PROMPT,
            user_message=prompt,
        )

        try:
            text = response_text.strip()
            start = text.find('{')
            if start > 0:
                text = text[start:]
            end = text.rfind('}')
            if end >= 0:
                text = text[:end + 1]
            parsed = json.loads(text)
            orch_response = OrchestratorResponse(**parsed)
            orch_response.citations = self._aggregate_citations(specialist_responses)
            orch_response.deterministic_grounding = self._deterministic_grounding(
                specialist_responses
            )
            return orch_response
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to parse orchestrator response: %s — raw: %r", e, response_text[:200])
            return OrchestratorResponse(
                summary="The system encountered an error processing your query.",
                detailed_analysis=str(e),
                citations=self._aggregate_citations(specialist_responses),
                agents_consulted=[],
                overall_confidence="low",
                deterministic_grounding=self._deterministic_grounding(specialist_responses),
            )

    def _build_synthesis_prompt(
        self, query_text: str, specialist_responses: list[dict[str, Any]]
    ) -> str:
        """Build the prompt for synthesis based on specialist responses."""
        parts = [
            f"ORIGINAL USER QUERY: {query_text}\n",
            "SPECIALIST RESPONSES:\n",
        ]

        for response in specialist_responses:
            agent_id = response.get("agent_id", "unknown")
            findings = response.get("findings", "No findings reported")
            confidence = response.get("confidence", "unknown")
            relevant = response.get("relevant_to_query", True)
            relevance_rationale = response.get("relevance_rationale")

            parts.append(
                f"\n[{agent_id.upper()} Agent] "
                f"(Confidence: {confidence}; Self-relevant: {relevant})\n"
            )
            if relevance_rationale:
                parts.append(f"RELEVANCE RATIONALE: {relevance_rationale}\n")
            parts.append(f"{findings}\n")

            citations = response.get("citations", [])
            if citations:
                parts.append("CITATIONS:\n")
                for citation in citations:
                    title = citation.get('instrument_title', 'Unknown')
                    url = citation.get('url', '')
                    sec = citation.get('relevant_section', '')
                    line = f"  - {title}"
                    if url:
                        line += f" | URL: {url}"
                    if sec:
                        line += f" | Section: {sec}"
                    parts.append(line + "\n")

        parts.append(
            "\n\nSynthesize these responses into a comprehensive answer. Respond with ONLY the JSON object described in your system prompt — no preamble, no explanation outside the JSON."
        )

        return "".join(parts)


    def _aggregate_citations(
        self, specialist_responses: list[dict[str, Any]]
    ) -> list[OrchestratorCitation]:
        """Collect citations from specialist responses, preserving registry URLs."""
        seen: set[tuple[str, str]] = set()
        result: list[OrchestratorCitation] = []
        for resp in specialist_responses:
            agent_id = resp.get("agent_id", "unknown")
            for c in resp.get("citations", []):
                key = (c.get("instrument_title", ""), c.get("url", ""))
                if key in seen:
                    continue
                seen.add(key)
                result.append(OrchestratorCitation(
                    instrument_title=c.get("instrument_title", ""),
                    instrument_type=c.get("instrument_type", ""),
                    url=c.get("url"),
                    relevant_section=c.get("relevant_section"),
                    sourced_from_agent=agent_id,
                ))
        return result

    def _filter_self_relevant_responses(
        self, specialist_responses: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not self._config.model.specialist_self_filter_enabled:
            return specialist_responses
        filtered = [
            response
            for response in specialist_responses
            if response.get("relevant_to_query", True)
        ]
        if not filtered:
            logger.warning("All specialists self-marked irrelevant; using all responses")
            return specialist_responses
        included = [response.get("agent_id", "unknown") for response in filtered]
        excluded = [
            response.get("agent_id", "unknown")
            for response in specialist_responses
            if not response.get("relevant_to_query", True)
        ]
        logger.info(
            "Specialist self-filter included=%s excluded=%s",
            included,
            excluded,
        )
        return filtered

    async def process_with_streaming(
        self,
        query_text: str,
        fetch_engine: FetchEngine,
        status_callback: Callable[[WSAgentStatusUpdate], Any],
    ) -> OrchestratorResponse:
        """Full end-to-end query processing with live status callbacks.

        1. Route the query to determine which specialists to invoke.
        2. Run selected specialists in parallel, emitting status updates.
        3. Synthesize all specialist responses into a final answer.
        """
        from src.agents.specialist import get_specialists

        specialists = get_specialists()

        await status_callback(WSAgentStatusUpdate(agent_id="orchestrator", status="working"))
        total_started = time.perf_counter()
        query_kiss_result = QueryKISSParser().parse(query_text)

        # Phase 1: routing
        routing_started = time.perf_counter()
        if self._config.model.route_with_llm:
            routing = await self._route(query_text)
            await self._unload_orchestrator()
            logger.info(
                "Routing phase completed in %.2fs with agents=%s",
                time.perf_counter() - routing_started,
                routing.get("selected_agents"),
            )
        else:
            routing = {
                "selected_agents": self._specialist_agent_ids,
                "sub_queries": {
                    aid: query_text for aid in self._specialist_agent_ids
                },
            }
            logger.info(
                "Routing phase skipped; dispatching all %d specialists",
                len(self._specialist_agent_ids),
            )
        selected_ids: list[str] = routing.get("selected_agents", self._specialist_agent_ids)
        sub_queries: dict[str, str] = routing.get(
            "sub_queries", {aid: query_text for aid in selected_ids}
        )

        # Phase 2: run specialists in parallel
        async def run_one(agent_id: str) -> dict[str, Any]:
            specialist_started = time.perf_counter()
            agent = specialists.get(agent_id)
            if agent is None:
                return {
                    "agent_id": agent_id,
                    "findings": "Agent not available.",
                    "confidence": "low",
                    "citations": [],
                }
            await status_callback(WSAgentStatusUpdate(agent_id=agent_id, status="working"))
            try:
                sub_query = sub_queries.get(agent_id, query_text)
                response = await agent.process_with_fetch(
                    sub_query, fetch_engine, query_kiss_result
                )
                await status_callback(
                    WSAgentStatusUpdate(agent_id=agent_id, status="complete")
                )
                logger.info(
                    "Specialist %s completed in %.2fs",
                    agent_id,
                    time.perf_counter() - specialist_started,
                )
                return response.model_dump()
            except Exception as e:
                logger.error("Specialist %s failed: %s", agent_id, e)
                await status_callback(
                    WSAgentStatusUpdate(agent_id=agent_id, status="error", message=str(e))
                )
                return {
                    "agent_id": agent_id,
                    "findings": f"Error during processing: {e}",
                    "confidence": "low",
                    "citations": [],
                }

        specialists_started = time.perf_counter()
        specialist_responses = await asyncio.gather(*[run_one(aid) for aid in selected_ids])
        await self._unload_specialists()
        logger.info(
            "Specialist phase completed in %.2fs for %d specialists",
            time.perf_counter() - specialists_started,
            len(selected_ids),
        )

        # Phase 3: synthesize
        final_responses = self._filter_self_relevant_responses(
            list(specialist_responses)
        )
        logger.info(
            "Self-relevance filter using %d/%d specialists for synthesis",
            len(final_responses),
            len(specialist_responses),
        )
        synthesis_started = time.perf_counter()
        result = await self.process(query_text, final_responses)
        await self._unload_orchestrator()
        logger.info(
            "Synthesis phase completed in %.2fs; total orchestrator workflow %.2fs",
            time.perf_counter() - synthesis_started,
            time.perf_counter() - total_started,
        )
        await status_callback(WSAgentStatusUpdate(agent_id="orchestrator", status="complete"))
        return result

    async def _unload_orchestrator(self) -> None:
        try:
            await self._llm_client.unload()
        except Exception as e:
            logger.warning("Failed to unload orchestrator model: %s", e)

    async def _unload_specialists(self) -> None:
        try:
            await get_specialist_client().unload()
        except Exception as e:
            logger.warning("Failed to unload specialist model: %s", e)

    def _deterministic_grounding(
        self, specialist_responses: list[dict[str, Any]]
    ) -> DeterministicGrounding:
        validate_responses = [
            response
            for response in specialist_responses
            if response.get("grounding_mode") == "validate"
        ]
        graph_hits = [
            citation.get("url")
            for response in validate_responses
            for citation in response.get("citations", [])
            if citation.get("url")
        ]
        live_fetches = [
            citation.get("url")
            for response in specialist_responses
            if response.get("grounding_mode") != "validate"
            for citation in response.get("citations", [])
            if citation.get("url")
        ]
        if validate_responses and len(validate_responses) == len(specialist_responses):
            coverage = "full"
            mode = "validate"
        elif validate_responses:
            coverage = "partial"
            mode = "mixed"
        else:
            coverage = "none"
            mode = "extract"
        return DeterministicGrounding(
            graph_coverage=coverage,
            triples_used=sum(
                response.get("retrieval_status", {}).get("instruments_successfully_retrieved", 0)
                for response in validate_responses
            ),
            documents_parsed_from_graph=len(set(graph_hits)),
            graph_hits=sorted(set(graph_hits)),
            graph_misses_fetched=sorted(set(live_fetches)),
            validation_flags_raised=[],
            llm_mode=mode,
        )

    async def _route(self, query_text: str) -> dict[str, Any]:
        """Ask the LLM which specialist agents to invoke for this query."""
        routing_request = (
            f"Analyze this HR policy query and select the specialist agents to consult.\n\n"
            f"QUERY: {query_text}\n\n"
            f"Available agents: {', '.join(self._specialist_agent_ids)}\n\n"
            f"Respond with ONLY a valid JSON object, no other text:\n"
            f'{{\n'
            f'  "selected_agents": ["agent_id1", "agent_id2"],\n'
            f'  "routing_rationale": "brief explanation",\n'
            f'  "sub_queries": {{"agent_id1": "focused sub-query for this agent"}}\n'
            f'}}\n\n'
            f"Select only agents whose domain is genuinely relevant. A typical query needs 1-3 agents."
        )
        try:
            raw = await self._llm_client.chat(
                system_prompt=ORCHESTRATOR_PROMPT,
                user_message=routing_request,
            )
            text = raw.strip()
            start = text.find('{')
            if start > 0:
                text = text[start:]
            end = text.rfind('}')
            if end >= 0:
                text = text[:end + 1]
            return json.loads(text)
        except Exception as e:
            logger.warning("Routing LLM call failed, invoking all agents: %s", e)
            return {
                "selected_agents": self._specialist_agent_ids,
                "sub_queries": {aid: query_text for aid in self._specialist_agent_ids},
            }


ORCHESTRATOR: OrchestratorAgent | None = None


def get_orchestrator() -> OrchestratorAgent:
    """Return singleton orchestrator instance."""
    global ORCHESTRATOR
    if ORCHESTRATOR is None:
        ORCHESTRATOR = OrchestratorAgent()
    return ORCHESTRATOR
