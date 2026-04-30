from __future__ import annotations

import json
import logging
from pathlib import Path

import aiosqlite

from src.models.schemas import (
    AgentResponseRecord,
    FeedbackRecord,
    FetchCacheEntry,
    OrchestratorResponseRecord,
    QueryRecord,
)

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent / "data" / "hr_policy_agent.db"

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
"""


class DatabaseManager:
    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

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
