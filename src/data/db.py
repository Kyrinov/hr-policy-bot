from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import aiosqlite

from src.config import get_config
from src.models.schemas import (
    AgentResponseRecord,
    FeedbackRecord,
    FetchCacheEntry,
    KISSDocument,
    OrchestratorResponseRecord,
    PolicyTriple,
    QueryRecord,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    query_id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agents_invoked TEXT NOT NULL,
    overall_confidence TEXT,
    processing_time_ms INTEGER
);

CREATE TABLE IF NOT EXISTS agent_responses (
    response_id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL REFERENCES queries(query_id),
    agent_id TEXT NOT NULL,
    findings TEXT,
    citations TEXT,
    caveats TEXT,
    confidence TEXT,
    retrieval_status TEXT,
    processing_time_ms INTEGER
);

CREATE TABLE IF NOT EXISTS orchestrator_responses (
    response_id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL REFERENCES queries(query_id),
    summary TEXT NOT NULL,
    detailed_analysis TEXT,
    policy_tensions TEXT,
    citations TEXT,
    gaps_and_limitations TEXT,
    recommended_consultation TEXT,
    overall_confidence TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL REFERENCES queries(query_id),
    rating TEXT NOT NULL,
    comment TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fetch_cache (
    url TEXT PRIMARY KEY,
    content_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ttl_hours INTEGER NOT NULL DEFAULT 168,
    status_code INTEGER,
    content_length INTEGER
);

CREATE TABLE IF NOT EXISTS kiss_documents (
    doc_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    instrument_title TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    sentence_count INTEGER,
    token_count INTEGER,
    model_version TEXT NOT NULL,
    parsed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fetch_cache_url TEXT REFERENCES fetch_cache(url)
);

CREATE TABLE IF NOT EXISTS policy_triples (
    triple_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES kiss_documents(doc_id),
    source_url TEXT NOT NULL,
    instrument_title TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    section_heading TEXT,
    sentence_text TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    predicate_lemma TEXT NOT NULL,
    is_deontic BOOLEAN NOT NULL DEFAULT FALSE,
    deontic_type TEXT,
    object_ TEXT NOT NULL,
    modifier TEXT,
    validation_flags TEXT,
    llm_validated BOOLEAN DEFAULT FALSE,
    llm_validation_note TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,
    entity_text TEXT NOT NULL,
    entity_type TEXT,
    mention_count INTEGER DEFAULT 1,
    first_seen_url TEXT,
    UNIQUE(entity_text)
);

CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id TEXT PRIMARY KEY,
    subject_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
    predicate TEXT NOT NULL,
    object_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
    triple_id TEXT NOT NULL REFERENCES policy_triples(triple_id),
    weight REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS rule_refinements (
    refinement_id TEXT PRIMARY KEY,
    triple_id TEXT REFERENCES policy_triples(triple_id),
    validation_flag TEXT,
    llm_correction TEXT NOT NULL,
    correction_type TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_to_rule TEXT
);

CREATE INDEX IF NOT EXISTS idx_triples_url ON policy_triples(source_url);
CREATE INDEX IF NOT EXISTS idx_triples_subject ON policy_triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON policy_triples(predicate_lemma);
CREATE INDEX IF NOT EXISTS idx_triples_agent ON policy_triples(agent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_text ON graph_nodes(entity_text);
"""


class DatabaseManager:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or self._default_db_path()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _default_db_path() -> Path:
        storage = get_config().storage
        if storage.db_path:
            path = Path(storage.db_path)
        else:
            path = Path(storage.data_dir) / "hr_policy_agent.db"
        if not path.is_absolute():
            path = _PROJECT_ROOT / path
        return path

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def initialize(self) -> None:
        """Create tables if they do not exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()
        logger.info("Database initialized at %s", self._db_path)

    # ------------------------------------------------------------------
    # Query records
    # ------------------------------------------------------------------

    async def save_query(self, record: QueryRecord) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO queries
                  (query_id, query_text, timestamp, agents_invoked,
                   overall_confidence, processing_time_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.query_id,
                    record.query_text,
                    record.timestamp.isoformat(),
                    json.dumps(record.agents_invoked),
                    record.overall_confidence,
                    record.processing_time_ms,
                ),
            )
            await db.commit()

    async def get_query(self, query_id: str) -> QueryRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM queries WHERE query_id = ?", (query_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return QueryRecord(
            query_id=row["query_id"],
            query_text=row["query_text"],
            timestamp=row["timestamp"],
            agents_invoked=json.loads(row["agents_invoked"]),
            overall_confidence=row["overall_confidence"],
            processing_time_ms=row["processing_time_ms"],
        )

    async def list_queries(self, limit: int = 50) -> list[QueryRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM queries ORDER BY timestamp DESC LIMIT ?", (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            QueryRecord(
                query_id=r["query_id"],
                query_text=r["query_text"],
                timestamp=r["timestamp"],
                agents_invoked=json.loads(r["agents_invoked"]),
                overall_confidence=r["overall_confidence"],
                processing_time_ms=r["processing_time_ms"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Agent responses
    # ------------------------------------------------------------------

    async def save_agent_response(self, record: AgentResponseRecord) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO agent_responses
                  (response_id, query_id, agent_id, findings, citations,
                   caveats, confidence, retrieval_status, processing_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.response_id,
                    record.query_id,
                    record.agent_id,
                    record.findings,
                    json.dumps([c.model_dump() for c in record.citations]),
                    record.caveats,
                    record.confidence,
                    json.dumps(record.retrieval_status.model_dump())
                    if record.retrieval_status
                    else None,
                    record.processing_time_ms,
                ),
            )
            await db.commit()

    async def get_agent_responses(self, query_id: str) -> list[AgentResponseRecord]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM agent_responses WHERE query_id = ?", (query_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [
            AgentResponseRecord(
                response_id=r["response_id"],
                query_id=r["query_id"],
                agent_id=r["agent_id"],
                findings=r["findings"],
                citations=json.loads(r["citations"]) if r["citations"] else [],
                caveats=r["caveats"],
                confidence=r["confidence"],
                retrieval_status=json.loads(r["retrieval_status"])
                if r["retrieval_status"]
                else None,
                processing_time_ms=r["processing_time_ms"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Orchestrator responses
    # ------------------------------------------------------------------

    async def save_orchestrator_response(
        self, record: OrchestratorResponseRecord
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO orchestrator_responses
                  (response_id, query_id, summary, detailed_analysis,
                   policy_tensions, citations, gaps_and_limitations,
                   recommended_consultation, overall_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.response_id,
                    record.query_id,
                    record.summary,
                    record.detailed_analysis,
                    record.policy_tensions,
                    json.dumps([c.model_dump() for c in record.citations]),
                    record.gaps_and_limitations,
                    record.recommended_consultation,
                    record.overall_confidence,
                ),
            )
            await db.commit()

    async def get_orchestrator_response(
        self, query_id: str
    ) -> OrchestratorResponseRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM orchestrator_responses WHERE query_id = ?",
                (query_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return OrchestratorResponseRecord(
            response_id=row["response_id"],
            query_id=row["query_id"],
            summary=row["summary"],
            detailed_analysis=row["detailed_analysis"],
            policy_tensions=row["policy_tensions"],
            citations=json.loads(row["citations"]) if row["citations"] else [],
            gaps_and_limitations=row["gaps_and_limitations"],
            recommended_consultation=row["recommended_consultation"],
            overall_confidence=row["overall_confidence"],
        )

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    async def save_feedback(self, record: FeedbackRecord) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO feedback
                  (feedback_id, query_id, rating, comment, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.feedback_id,
                    record.query_id,
                    record.rating,
                    record.comment,
                    record.timestamp.isoformat(),
                ),
            )
            await db.commit()

    async def get_feedback_for_query(self, query_id: str) -> FeedbackRecord | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM feedback WHERE query_id = ? ORDER BY timestamp DESC LIMIT 1",
                (query_id,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return FeedbackRecord(
            feedback_id=row["feedback_id"],
            query_id=row["query_id"],
            rating=row["rating"],
            comment=row["comment"],
            timestamp=row["timestamp"],
        )

    async def export_feedback(self) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM feedback ORDER BY timestamp DESC"
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Fetch cache
    # ------------------------------------------------------------------

    async def get_cached(self, url: str) -> FetchCacheEntry | None:
        """Return a cache entry if it exists and is within TTL, else None."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM fetch_cache
                WHERE url = ?
                  AND datetime(fetched_at, '+' || ttl_hours || ' hours') > datetime('now')
                """,
                (url,),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return FetchCacheEntry(**dict(row))

    async def get_stale(self, url: str) -> FetchCacheEntry | None:
        """Return an expired cache entry if available (for fallback on fetch failure)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM fetch_cache WHERE url = ?", (url,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return FetchCacheEntry(**dict(row))

    async def set_cached(self, entry: FetchCacheEntry) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO fetch_cache
                  (url, content_text, content_hash, fetched_at,
                   ttl_hours, status_code, content_length)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.url,
                    entry.content_text,
                    entry.content_hash,
                    entry.fetched_at.isoformat(),
                    entry.ttl_hours,
                    entry.status_code,
                    entry.content_length,
                ),
            )
            await db.commit()

    async def clear_expired(self) -> int:
        """Remove expired cache entries. Returns number of rows deleted."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                DELETE FROM fetch_cache
                WHERE datetime(fetched_at, '+' || ttl_hours || ' hours') <= datetime('now')
                """
            )
            await db.commit()
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Deterministic parsing graph
    # ------------------------------------------------------------------

    async def save_kiss_document(self, doc_id: str, document: KISSDocument) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO kiss_documents
                  (doc_id, source_url, instrument_title, agent_id, sentence_count,
                   token_count, model_version, parsed_at, fetch_cache_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    document.source_url,
                    document.instrument_title,
                    document.agent_id,
                    document.sentence_count,
                    document.token_count,
                    document.model_version,
                    document.parsed_at,
                    document.source_url,
                ),
            )
            await db.commit()

    async def save_policy_triples(self, triples: list[PolicyTriple]) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            for triple in triples:
                await db.execute(
                    """
                    INSERT OR REPLACE INTO policy_triples
                      (triple_id, doc_id, source_url, instrument_title, agent_id,
                       section_heading, sentence_text, subject, predicate,
                       predicate_lemma, is_deontic, deontic_type, object_, modifier,
                       validation_flags, llm_validated, llm_validation_note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._triple_params(triple),
                )
                subject_node_id = await self._upsert_node(
                    db, triple.subject, None, triple.source_url
                )
                object_node_id = await self._upsert_node(
                    db, triple.object_, None, triple.source_url
                )
                weight = 2.0 if "CROSS_INSTRUMENT_CORROBORATION" in triple.validation_flags else 1.0
                await db.execute(
                    """
                    INSERT OR REPLACE INTO graph_edges
                      (edge_id, subject_node_id, predicate, object_node_id, triple_id, weight)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{triple.triple_id}:edge",
                        subject_node_id,
                        triple.predicate_lemma,
                        object_node_id,
                        triple.triple_id,
                        weight,
                    ),
                )
            await db.commit()

    async def query_triples_by_url(self, source_url: str) -> list[PolicyTriple]:
        return await self._load_triples(
            "SELECT * FROM policy_triples WHERE source_url = ?",
            (source_url,),
        )

    async def search_policy_triples(
        self,
        query_entities: list[str],
        query_verbs: list[str],
        agent_id: str | None,
        limit: int,
    ) -> list[PolicyTriple]:
        params: list[str] = []
        clauses: list[str] = []
        for entity in query_entities:
            pattern = f"%{entity.lower()}%"
            clauses.append("(lower(subject) LIKE ? OR lower(object_) LIKE ?)")
            params.extend([pattern, pattern])
        for verb in query_verbs:
            clauses.append("lower(predicate_lemma) = ?")
            params.append(verb.lower())
        where = " OR ".join(clauses) if clauses else "1 = 0"
        if agent_id is not None:
            where = f"({where}) AND agent_id = ?"
            params.append(agent_id)
        triples = await self._load_triples(
            f"SELECT * FROM policy_triples WHERE {where} LIMIT ?",
            tuple([*params, str(limit * 4)]),
        )
        return triples

    async def find_conflicting_triples(
        self, subject: str, predicate: str
    ) -> list[PolicyTriple]:
        return await self._load_triples(
            """
            SELECT * FROM policy_triples
            WHERE lower(subject) = lower(?) AND lower(predicate_lemma) = lower(?)
            ORDER BY object_
            """,
            (subject, predicate),
        )

    async def is_document_parsed(self, source_url: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT 1 FROM kiss_documents WHERE source_url = ? LIMIT 1",
                (source_url,),
            ) as cursor:
                row = await cursor.fetchone()
        return row is not None

    async def get_coverage_stats(self) -> dict:
        async with aiosqlite.connect(self._db_path) as db:
            doc_count = await self._count(db, "kiss_documents")
            triple_count = await self._count(db, "policy_triples")
            node_count = await self._count(db, "graph_nodes")
            edge_count = await self._count(db, "graph_edges")
        return {
            "documents": doc_count,
            "triples": triple_count,
            "nodes": node_count,
            "edges": edge_count,
        }

    async def save_rule_refinement(
        self,
        refinement_id: str,
        triple_id: str,
        validation_flag: str,
        llm_correction: str,
        correction_type: str,
        applied_to_rule: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO rule_refinements
                  (refinement_id, triple_id, validation_flag, llm_correction,
                   correction_type, applied_to_rule)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    refinement_id,
                    triple_id,
                    validation_flag,
                    llm_correction,
                    correction_type,
                    applied_to_rule,
                ),
            )
            await db.commit()

    def _triple_params(self, triple: PolicyTriple) -> tuple:
        return (
            triple.triple_id,
            triple.doc_id,
            triple.source_url,
            triple.instrument_title,
            triple.agent_id,
            triple.section_heading,
            triple.sentence_text,
            triple.subject,
            triple.predicate,
            triple.predicate_lemma,
            triple.is_deontic,
            triple.deontic_type,
            triple.object_,
            triple.modifier,
            json.dumps(triple.validation_flags),
            triple.llm_validated,
            triple.llm_validation_note,
        )

    async def _load_triples(self, sql: str, params: tuple) -> list[PolicyTriple]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_triple(row) for row in rows]

    def _row_to_triple(self, row: aiosqlite.Row) -> PolicyTriple:
        return PolicyTriple(
            triple_id=row["triple_id"],
            doc_id=row["doc_id"],
            source_url=row["source_url"],
            instrument_title=row["instrument_title"],
            agent_id=row["agent_id"],
            section_heading=row["section_heading"],
            sentence_text=row["sentence_text"],
            subject=row["subject"],
            predicate=row["predicate"],
            predicate_lemma=row["predicate_lemma"],
            is_deontic=bool(row["is_deontic"]),
            deontic_type=row["deontic_type"],
            object_=row["object_"],
            modifier=row["modifier"],
            validation_flags=json.loads(row["validation_flags"] or "[]"),
            llm_validated=bool(row["llm_validated"]),
            llm_validation_note=row["llm_validation_note"],
        )

    async def _upsert_node(
        self, db: aiosqlite.Connection, entity_text: str, entity_type: str | None, url: str
    ) -> str:
        node_id = hashlib.sha256(entity_text.lower().encode("utf-8")).hexdigest()
        await db.execute(
            """
            INSERT INTO graph_nodes (node_id, entity_text, entity_type, first_seen_url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(entity_text) DO UPDATE SET mention_count = mention_count + 1
            """,
            (node_id, entity_text, entity_type, url),
        )
        return node_id

    async def _count(self, db: aiosqlite.Connection, table_name: str) -> int:
        async with db.execute(f"SELECT COUNT(*) FROM {table_name}") as cursor:
            row = await cursor.fetchone()
        return int(row[0])
