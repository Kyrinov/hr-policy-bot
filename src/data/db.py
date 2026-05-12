from __future__ import annotations

import hashlib
import json
import logging

import asyncpg

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

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS queries (
        query_id TEXT PRIMARY KEY,
        query_text TEXT NOT NULL,
        timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        agents_invoked TEXT NOT NULL,
        overall_confidence TEXT,
        processing_time_ms INTEGER
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS feedback (
        feedback_id TEXT PRIMARY KEY,
        query_id TEXT NOT NULL REFERENCES queries(query_id),
        rating TEXT NOT NULL,
        comment TEXT,
        timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fetch_cache (
        url TEXT PRIMARY KEY,
        content_text TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ttl_hours INTEGER NOT NULL DEFAULT 168,
        status_code INTEGER,
        content_length INTEGER
    )
    """,
    """
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
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_nodes (
        node_id TEXT PRIMARY KEY,
        entity_text TEXT NOT NULL,
        entity_type TEXT,
        mention_count INTEGER DEFAULT 1,
        first_seen_url TEXT,
        UNIQUE(entity_text)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_edges (
        edge_id TEXT PRIMARY KEY,
        subject_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
        predicate TEXT NOT NULL,
        object_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
        triple_id TEXT NOT NULL REFERENCES policy_triples(triple_id),
        weight REAL DEFAULT 1.0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rule_refinements (
        refinement_id TEXT PRIMARY KEY,
        triple_id TEXT REFERENCES policy_triples(triple_id),
        validation_flag TEXT,
        llm_correction TEXT NOT NULL,
        correction_type TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        applied_to_rule TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_triples_url ON policy_triples(source_url)",
    "CREATE INDEX IF NOT EXISTS idx_triples_subject ON policy_triples(subject)",
    "CREATE INDEX IF NOT EXISTS idx_triples_predicate ON policy_triples(predicate_lemma)",
    "CREATE INDEX IF NOT EXISTS idx_triples_agent ON policy_triples(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_text ON graph_nodes(entity_text)",
]


class DatabaseManager:
    def __init__(self, database_url: str | None = None) -> None:
        storage = get_config().storage
        self._database_url = database_url or storage.database_url or ""
        self._pool: asyncpg.Pool | None = None

    async def initialize(self) -> None:
        """Create connection pool and tables if they do not exist. Idempotent."""
        if self._pool is not None:
            return
        if not self._database_url:
            raise RuntimeError(
                "No DATABASE_URL configured. Set the DATABASE_URL environment variable."
            )
        self._pool = await asyncpg.create_pool(
            self._database_url, min_size=1, max_size=5
        )
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for stmt in _SCHEMA_STATEMENTS:
                    await conn.execute(stmt)
        logger.info("Database initialized")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Query records
    # ------------------------------------------------------------------

    async def save_query(self, record: QueryRecord) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO queries
                  (query_id, query_text, timestamp, agents_invoked,
                   overall_confidence, processing_time_ms)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (query_id) DO UPDATE SET
                    query_text = EXCLUDED.query_text,
                    timestamp = EXCLUDED.timestamp,
                    agents_invoked = EXCLUDED.agents_invoked,
                    overall_confidence = EXCLUDED.overall_confidence,
                    processing_time_ms = EXCLUDED.processing_time_ms
                """,
                record.query_id,
                record.query_text,
                record.timestamp,
                json.dumps(record.agents_invoked),
                record.overall_confidence,
                record.processing_time_ms,
            )

    async def get_query(self, query_id: str) -> QueryRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM queries WHERE query_id = $1", query_id
            )
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
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM queries ORDER BY timestamp DESC LIMIT $1", limit
            )
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
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_responses
                  (response_id, query_id, agent_id, findings, citations,
                   caveats, confidence, retrieval_status, processing_time_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (response_id) DO UPDATE SET
                    findings = EXCLUDED.findings,
                    citations = EXCLUDED.citations,
                    caveats = EXCLUDED.caveats,
                    confidence = EXCLUDED.confidence,
                    retrieval_status = EXCLUDED.retrieval_status,
                    processing_time_ms = EXCLUDED.processing_time_ms
                """,
                record.response_id,
                record.query_id,
                record.agent_id,
                record.findings,
                json.dumps([c.model_dump() for c in record.citations]),
                record.caveats,
                record.confidence,
                json.dumps(record.retrieval_status.model_dump()) if record.retrieval_status else None,
                record.processing_time_ms,
            )

    async def get_agent_responses(self, query_id: str) -> list[AgentResponseRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM agent_responses WHERE query_id = $1", query_id
            )
        return [
            AgentResponseRecord(
                response_id=r["response_id"],
                query_id=r["query_id"],
                agent_id=r["agent_id"],
                findings=r["findings"],
                citations=json.loads(r["citations"]) if r["citations"] else [],
                caveats=r["caveats"],
                confidence=r["confidence"],
                retrieval_status=json.loads(r["retrieval_status"]) if r["retrieval_status"] else None,
                processing_time_ms=r["processing_time_ms"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Orchestrator responses
    # ------------------------------------------------------------------

    async def save_orchestrator_response(self, record: OrchestratorResponseRecord) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestrator_responses
                  (response_id, query_id, summary, detailed_analysis,
                   policy_tensions, citations, gaps_and_limitations,
                   recommended_consultation, overall_confidence)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (response_id) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    detailed_analysis = EXCLUDED.detailed_analysis,
                    policy_tensions = EXCLUDED.policy_tensions,
                    citations = EXCLUDED.citations,
                    gaps_and_limitations = EXCLUDED.gaps_and_limitations,
                    recommended_consultation = EXCLUDED.recommended_consultation,
                    overall_confidence = EXCLUDED.overall_confidence
                """,
                record.response_id,
                record.query_id,
                record.summary,
                record.detailed_analysis,
                record.policy_tensions,
                json.dumps([c.model_dump() for c in record.citations]),
                record.gaps_and_limitations,
                record.recommended_consultation,
                record.overall_confidence,
            )

    async def get_orchestrator_response(self, query_id: str) -> OrchestratorResponseRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM orchestrator_responses WHERE query_id = $1", query_id
            )
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
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO feedback
                  (feedback_id, query_id, rating, comment, timestamp)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (feedback_id) DO UPDATE SET
                    rating = EXCLUDED.rating,
                    comment = EXCLUDED.comment,
                    timestamp = EXCLUDED.timestamp
                """,
                record.feedback_id,
                record.query_id,
                record.rating,
                record.comment,
                record.timestamp,
            )

    async def get_feedback_for_query(self, query_id: str) -> FeedbackRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM feedback WHERE query_id = $1 ORDER BY timestamp DESC LIMIT 1",
                query_id,
            )
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
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM feedback ORDER BY timestamp DESC")
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Fetch cache
    # ------------------------------------------------------------------

    async def get_cached(self, url: str) -> FetchCacheEntry | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM fetch_cache
                WHERE url = $1
                  AND fetched_at + (ttl_hours || ' hours')::interval > NOW()
                """,
                url,
            )
        if row is None:
            return None
        return FetchCacheEntry(**dict(row))

    async def get_stale(self, url: str) -> FetchCacheEntry | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM fetch_cache WHERE url = $1", url
            )
        if row is None:
            return None
        return FetchCacheEntry(**dict(row))

    async def set_cached(self, entry: FetchCacheEntry) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO fetch_cache
                  (url, content_text, content_hash, fetched_at,
                   ttl_hours, status_code, content_length)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (url) DO UPDATE SET
                    content_text = EXCLUDED.content_text,
                    content_hash = EXCLUDED.content_hash,
                    fetched_at = EXCLUDED.fetched_at,
                    ttl_hours = EXCLUDED.ttl_hours,
                    status_code = EXCLUDED.status_code,
                    content_length = EXCLUDED.content_length
                """,
                entry.url,
                entry.content_text,
                entry.content_hash,
                entry.fetched_at,
                entry.ttl_hours,
                entry.status_code,
                entry.content_length,
            )

    async def clear_expired(self) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM fetch_cache WHERE fetched_at + (ttl_hours || ' hours')::interval <= NOW()"
            )
        return int(result.split()[-1])

    # ------------------------------------------------------------------
    # Deterministic parsing graph
    # ------------------------------------------------------------------

    async def save_kiss_document(self, doc_id: str, document: KISSDocument) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO kiss_documents
                  (doc_id, source_url, instrument_title, agent_id, sentence_count,
                   token_count, model_version, parsed_at, fetch_cache_url)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (doc_id) DO UPDATE SET
                    source_url = EXCLUDED.source_url,
                    instrument_title = EXCLUDED.instrument_title,
                    sentence_count = EXCLUDED.sentence_count,
                    token_count = EXCLUDED.token_count,
                    model_version = EXCLUDED.model_version,
                    parsed_at = EXCLUDED.parsed_at
                """,
                doc_id,
                document.source_url,
                document.instrument_title,
                document.agent_id,
                document.sentence_count,
                document.token_count,
                document.model_version,
                document.parsed_at,
                document.source_url,
            )

    async def save_policy_triples(self, triples: list[PolicyTriple]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for triple in triples:
                    await conn.execute(
                        """
                        INSERT INTO policy_triples
                          (triple_id, doc_id, source_url, instrument_title, agent_id,
                           section_heading, sentence_text, subject, predicate,
                           predicate_lemma, is_deontic, deontic_type, object_, modifier,
                           validation_flags, llm_validated, llm_validation_note)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)
                        ON CONFLICT (triple_id) DO NOTHING
                        """,
                        *self._triple_params(triple),
                    )
                    subject_node_id = await self._upsert_node(
                        conn, triple.subject, None, triple.source_url
                    )
                    object_node_id = await self._upsert_node(
                        conn, triple.object_, None, triple.source_url
                    )
                    weight = 2.0 if "CROSS_INSTRUMENT_CORROBORATION" in triple.validation_flags else 1.0
                    await conn.execute(
                        """
                        INSERT INTO graph_edges
                          (edge_id, subject_node_id, predicate, object_node_id, triple_id, weight)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (edge_id) DO NOTHING
                        """,
                        f"{triple.triple_id}:edge",
                        subject_node_id,
                        triple.predicate_lemma,
                        object_node_id,
                        triple.triple_id,
                        weight,
                    )

    async def query_triples_by_url(self, source_url: str) -> list[PolicyTriple]:
        return await self._load_triples(
            "SELECT * FROM policy_triples WHERE source_url = $1",
            (source_url,),
        )

    async def search_policy_triples(
        self,
        query_entities: list[str],
        query_verbs: list[str],
        agent_id: str | None,
        limit: int,
    ) -> list[PolicyTriple]:
        params: list = []
        clauses: list[str] = []
        idx = 1
        for entity in query_entities:
            pattern = f"%{entity.lower()}%"
            clauses.append(f"(lower(subject) LIKE ${idx} OR lower(object_) LIKE ${idx + 1})")
            params.extend([pattern, pattern])
            idx += 2
        for verb in query_verbs:
            clauses.append(f"lower(predicate_lemma) = ${idx}")
            params.append(verb.lower())
            idx += 1
        where = " OR ".join(clauses) if clauses else "1 = 0"
        if agent_id is not None:
            where = f"({where}) AND agent_id = ${idx}"
            params.append(agent_id)
            idx += 1
        params.append(limit * 4)
        return await self._load_triples(
            f"SELECT * FROM policy_triples WHERE {where} LIMIT ${idx}",
            tuple(params),
        )

    async def find_conflicting_triples(self, subject: str, predicate: str) -> list[PolicyTriple]:
        return await self._load_triples(
            """
            SELECT * FROM policy_triples
            WHERE lower(subject) = lower($1) AND lower(predicate_lemma) = lower($2)
            ORDER BY object_
            """,
            (subject, predicate),
        )

    async def is_document_parsed(self, source_url: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM kiss_documents WHERE source_url = $1 LIMIT 1", source_url
            )
        return row is not None

    async def get_coverage_stats(self) -> dict:
        async with self._pool.acquire() as conn:
            doc_count = await self._count(conn, "kiss_documents")
            triple_count = await self._count(conn, "policy_triples")
            node_count = await self._count(conn, "graph_nodes")
            edge_count = await self._count(conn, "graph_edges")
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
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO rule_refinements
                  (refinement_id, triple_id, validation_flag, llm_correction,
                   correction_type, applied_to_rule)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (refinement_id) DO NOTHING
                """,
                refinement_id,
                triple_id,
                validation_flag,
                llm_correction,
                correction_type,
                applied_to_rule,
            )

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
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [self._row_to_triple(row) for row in rows]

    def _row_to_triple(self, row: asyncpg.Record) -> PolicyTriple:
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
        self, conn: asyncpg.Connection, entity_text: str, entity_type: str | None, url: str
    ) -> str:
        node_id = hashlib.sha256(entity_text.lower().encode("utf-8")).hexdigest()
        await conn.execute(
            """
            INSERT INTO graph_nodes (node_id, entity_text, entity_type, first_seen_url)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (entity_text) DO UPDATE SET mention_count = graph_nodes.mention_count + 1
            """,
            node_id, entity_text, entity_type, url,
        )
        return node_id

    async def health_check(self) -> dict:
        try:
            async with self._pool.acquire() as conn:
                query_count = await self._count(conn, "queries")
                feedback_count = await self._count(conn, "feedback")
            return {"status": "ok", "query_count": query_count, "feedback_count": feedback_count}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def cache_stats(self) -> dict:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN fetched_at + (ttl_hours || ' hours')::interval > NOW()
                            THEN 1 ELSE 0 END) as valid,
                        SUM(CASE WHEN fetched_at + (ttl_hours || ' hours')::interval <= NOW()
                            THEN 1 ELSE 0 END) as expired,
                        COALESCE(SUM(content_length), 0) as total_bytes
                    FROM fetch_cache
                    """
                )
                if row:
                    total_bytes = row["total_bytes"] or 0
                    return {
                        "total": row["total"] or 0,
                        "valid": row["valid"] or 0,
                        "expired": row["expired"] or 0,
                        "total_bytes": total_bytes,
                        "total_mb": round(total_bytes / (1024 * 1024), 2),
                    }
            return {"total": 0, "valid": 0, "expired": 0, "total_bytes": 0, "total_mb": 0.0}
        except Exception as e:
            return {"error": str(e)}

    async def _count(self, conn: asyncpg.Connection, table_name: str) -> int:
        row = await conn.fetchrow(f"SELECT COUNT(*) FROM {table_name}")
        return int(row[0])


_db_manager: DatabaseManager | None = None


async def init_db_manager(database_url: str | None = None) -> DatabaseManager:
    """Initialize the module-level singleton. Call once at app startup."""
    global _db_manager
    _db_manager = DatabaseManager(database_url)
    await _db_manager.initialize()
    return _db_manager


def get_db_manager() -> DatabaseManager:
    """Return the initialized singleton, or an uninitialized instance if startup hasn't run."""
    return _db_manager if _db_manager is not None else DatabaseManager()
