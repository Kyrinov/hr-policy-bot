from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ModelConfig(BaseModel):
    name: str = "gemma4:31b"
    temperature: float = 0.2
    num_ctx: int = 32768
    top_p: float = 0.9


# ---------------------------------------------------------------------------
# Policy registry
# ---------------------------------------------------------------------------


class PolicyInstrument(BaseModel):
    id: str
    title: str
    type: str
    url: str
    agent_ids: list[str]


# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    agent_id: str
    display_name: str
    domain_description: str
    instruments: list[PolicyInstrument]


# ---------------------------------------------------------------------------
# Specialist agent output
# ---------------------------------------------------------------------------


class CitationItem(BaseModel):
    instrument_title: str
    instrument_type: str
    url: Optional[str] = None
    relevant_section: Optional[str] = None


class RetrievalStatus(BaseModel):
    instruments_attempted: int
    instruments_successfully_retrieved: int
    instruments_failed: list[str] = Field(default_factory=list)


class SpecialistResponse(BaseModel):
    agent_id: str
    findings: str
    relevant_to_query: bool = True
    relevance_rationale: Optional[str] = None
    citations: list[CitationItem] = Field(default_factory=list)
    caveats: Optional[str] = None
    scope_flags: list[str] = Field(default_factory=list)
    confidence: str  # "high" | "medium" | "low"
    retrieval_status: RetrievalStatus
    grounding_mode: Optional[str] = None


# ---------------------------------------------------------------------------
# Orchestrator output
# ---------------------------------------------------------------------------


class OrchestratorCitation(BaseModel):
    instrument_title: str
    instrument_type: str
    url: Optional[str] = None
    relevant_section: Optional[str] = None
    sourced_from_agent: str


class RoutingDecision(BaseModel):
    selected_agents: list[str]
    routing_rationale: str
    sub_queries: dict[str, str]


class OrchestratorResponse(BaseModel):
    summary: str
    detailed_analysis: str
    policy_tensions: Optional[str] = None
    citations: list[OrchestratorCitation] = Field(default_factory=list)
    gaps_and_limitations: Optional[str] = None
    recommended_consultation: Optional[str] = None
    agents_consulted: list[str] = Field(default_factory=list)
    overall_confidence: str  # "high" | "medium" | "low"
    deterministic_grounding: Optional["DeterministicGrounding"] = None


@dataclass(frozen=True)
class KISSToken:
    text: str
    lemma: str
    pos: str
    kiss_category: str
    is_deontic: bool
    deontic_type: Optional[str]
    char_start: int
    char_end: int
    sentence_idx: int
    token_idx: int


@dataclass(frozen=True)
class KISSDocument:
    source_url: str
    instrument_title: str
    agent_id: str
    tokens: list[KISSToken]
    sentence_count: int
    token_count: int
    parsed_at: str
    model_version: str


@dataclass(frozen=True)
class QueryKISSResult:
    raw_query: str
    entities: list[str]
    entity_types: dict[str, str]
    verbs: list[str]
    deontic_verbs: list[str]
    sentence_count: int
    entity_count: int
    fallback_triggered: bool
    model_version: str


@dataclass(frozen=True)
class PolicyTriple:
    triple_id: str
    doc_id: str
    source_url: str
    instrument_title: str
    agent_id: str
    section_heading: Optional[str]
    sentence_text: str
    subject: str
    predicate: str
    predicate_lemma: str
    is_deontic: bool
    deontic_type: Optional[str]
    object_: str
    modifier: Optional[str]
    validation_flags: list[str]
    llm_validated: bool = False
    llm_validation_note: Optional[str] = None


@dataclass(frozen=True)
class DeterministicGrounding:
    graph_coverage: str
    triples_used: int
    documents_parsed_from_graph: int
    graph_hits: list[str]
    graph_misses_fetched: list[str]
    validation_flags_raised: list[str]
    llm_mode: str


# ---------------------------------------------------------------------------
# Database records
# ---------------------------------------------------------------------------


class QueryRecord(BaseModel):
    query_id: str
    query_text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agents_invoked: list[str] = Field(default_factory=list)
    overall_confidence: Optional[str] = None
    processing_time_ms: Optional[int] = None


class AgentResponseRecord(BaseModel):
    response_id: str
    query_id: str
    agent_id: str
    findings: Optional[str] = None
    citations: list[CitationItem] = Field(default_factory=list)
    caveats: Optional[str] = None
    confidence: Optional[str] = None
    retrieval_status: Optional[RetrievalStatus] = None
    processing_time_ms: Optional[int] = None


class OrchestratorResponseRecord(BaseModel):
    response_id: str
    query_id: str
    summary: str
    detailed_analysis: Optional[str] = None
    policy_tensions: Optional[str] = None
    citations: list[OrchestratorCitation] = Field(default_factory=list)
    gaps_and_limitations: Optional[str] = None
    recommended_consultation: Optional[str] = None
    overall_confidence: Optional[str] = None


class FeedbackRecord(BaseModel):
    feedback_id: str
    query_id: str
    rating: str  # "accurate" | "needs_work"
    comment: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FetchCacheEntry(BaseModel):
    url: str
    content_text: str
    content_hash: str
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    ttl_hours: int = 168
    status_code: Optional[int] = None
    content_length: Optional[int] = None


# ---------------------------------------------------------------------------
# WebSocket message types
# ---------------------------------------------------------------------------


class WSUserQuery(BaseModel):
    type: str = "user_query"
    query_id: str
    query_text: str


class WSAgentStatusUpdate(BaseModel):
    type: str = "agent_status_update"
    agent_id: str
    status: str  # "idle" | "working" | "complete" | "error"
    message: Optional[str] = None


class WSResponseChunk(BaseModel):
    type: str = "response_chunk"
    query_id: str
    chunk: str


class WSResponseComplete(BaseModel):
    type: str = "response_complete"
    query_id: str
    orchestrator_response: OrchestratorResponse
    processing_time_ms: int


class WSError(BaseModel):
    type: str = "error"
    query_id: Optional[str] = None
    message: str
