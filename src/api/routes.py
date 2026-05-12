from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from src.agents.orchestrator import get_orchestrator
from src.config import get_config
from src.data.db import DatabaseManager
from src.fetch.engine import get_fetch_engine
from src.models.schemas import (
    FeedbackRecord,
    OrchestratorResponseRecord,
    QueryRecord,
    WSAgentStatusUpdate,
)

router = APIRouter()

_POLLING_JOBS: dict[str, dict[str, Any]] = {}
_POLLING_JOB_TTL_SECONDS = 3600


_AGENT_CONFIG = [
    {
        "agent_id": "staffing",
        "display_name": "Staffing & Recruitment",
        "domain": "Staffing and recruitment; Student and youth programs",
    },
    {
        "agent_id": "classification",
        "display_name": "Classification & Compensation",
        "domain": "Classification; Compensation and benefits",
    },
    {
        "agent_id": "labour",
        "display_name": "Labour Relations",
        "domain": "Labour relations and workplace management",
    },
    {
        "agent_id": "learning",
        "display_name": "Learning & Performance",
        "domain": "Learning, training and development; Performance management",
    },
    {
        "agent_id": "equity",
        "display_name": "Equity, Diversity & Inclusion",
        "domain": "Diversity, equity and inclusion; Employment equity and accessibility",
    },
    {
        "agent_id": "ohs",
        "display_name": "Health, Safety & Wellness",
        "domain": "Occupational health and safety",
    },
    {
        "agent_id": "languages",
        "display_name": "Official Languages",
        "domain": "Official languages",
    },
    {
        "agent_id": "governance",
        "display_name": "Values, Ethics & HR Governance",
        "domain": "Values and ethics; Conflict of interest; HR planning; Executive services; Leave and attendance",
    },
]


# Fix 3: paths have no /api prefix — router is already mounted at /api in main.py

@router.get("/health")
async def health_check() -> dict:
    """Return system health status for all components."""
    result = {
        "status": "healthy",
        "components": {},
        "model": get_config().model.name,
        "specialist_model": get_config().model.specialist_name,
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        from src.llm.client import get_orchestrator_client, get_specialist_client

        result["components"]["ollama"] = {
            "orchestrator": await get_orchestrator_client().health_check(),
            "specialist": await get_specialist_client().health_check(),
        }
        if any(
            component["status"] != "ok"
            for component in result["components"]["ollama"].values()
        ):
            result["status"] = "degraded"
    except Exception as e:
        config = get_config()
        result["components"]["ollama"] = {
            "status": "error",
            "error": str(e),
            "orchestrator": {
                "host": config.model.orchestrator_host,
                "configured_model": config.model.name,
                "auth_configured": config.model.orchestrator_auth_header is not None,
            },
            "specialist": {
                "host": config.model.specialist_host,
                "configured_model": config.model.specialist_name,
                "auth_configured": config.model.specialist_auth_header is not None,
            },
        }
        result["status"] = "degraded"

    try:
        db = DatabaseManager()
        if db.db_path.exists():
            result["components"]["database"] = await db.health_check()
            if result["components"]["database"].get("status") != "ok":
                result["status"] = "degraded"
        else:
            result["components"]["database"] = {"status": "not_initialized"}
    except Exception as e:
        result["components"]["database"] = {"status": "error", "error": str(e)}
        result["status"] = "degraded"

    return result


@router.get("/agents")
async def list_agents() -> list[dict]:
    """Return all agent metadata."""
    return _AGENT_CONFIG


@router.get("/queries")
async def list_queries(limit: int = Query(50, ge=1, le=100)) -> list[dict]:
    """List recent queries from database."""
    from src.data.db import DatabaseManager

    db = DatabaseManager()
    try:
        queries = await db.list_queries(limit=limit)
        return [q.model_dump() for q in queries]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query/start")
async def start_query(payload: dict[str, str]) -> dict:
    """Start a query over ordinary HTTPS for networks that block WebSockets."""
    _cleanup_polling_jobs()
    query_text = payload.get("query_text", "").strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text is required")

    query_id = str(uuid.uuid4())
    _POLLING_JOBS[query_id] = {
        "query_id": query_id,
        "query_text": query_text,
        "status": "queued",
        "agent_statuses": {},
        "orchestrator_response": None,
        "processing_time_ms": None,
        "error": None,
        "started_at": datetime.utcnow().isoformat(),
    }
    asyncio.create_task(_run_polling_query(query_id, query_text))
    return {"query_id": query_id, "status": "queued"}


@router.get("/query/{query_id}/status")
async def get_query_status(query_id: str) -> dict:
    """Return status/result for an HTTPS polling query."""
    _cleanup_polling_jobs()
    job = _POLLING_JOBS.get(query_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Query job not found")
    return job


def _cleanup_polling_jobs() -> None:
    now = datetime.utcnow()
    for query_id, job in list(_POLLING_JOBS.items()):
        completed_at = job.get("completed_at")
        if not completed_at:
            continue
        try:
            completed = datetime.fromisoformat(completed_at)
        except ValueError:
            continue
        if (now - completed).total_seconds() > _POLLING_JOB_TTL_SECONDS:
            del _POLLING_JOBS[query_id]


async def _run_polling_query(query_id: str, query_text: str) -> None:
    job = _POLLING_JOBS[query_id]
    job["status"] = "running"
    start_time = datetime.utcnow()

    db = DatabaseManager()
    query_record = QueryRecord(
        query_id=query_id,
        query_text=query_text,
        agents_invoked=[],
    )
    await db.save_query(query_record)

    async def record_status(status: WSAgentStatusUpdate) -> None:
        job["agent_statuses"][status.agent_id] = status.model_dump()

    try:
        response = await get_orchestrator().process_with_streaming(
            query_text,
            get_fetch_engine(),
            record_status,
        )
        processing_time = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        query_record.processing_time_ms = processing_time
        query_record.agents_invoked = response.agents_consulted
        query_record.overall_confidence = response.overall_confidence
        await db.save_query(query_record)

        await db.save_orchestrator_response(
            OrchestratorResponseRecord(
                response_id=str(uuid.uuid4()),
                query_id=query_id,
                summary=response.summary,
                detailed_analysis=response.detailed_analysis,
                policy_tensions=response.policy_tensions,
                citations=response.citations,
                gaps_and_limitations=response.gaps_and_limitations,
                recommended_consultation=response.recommended_consultation,
                overall_confidence=response.overall_confidence,
            )
        )

        job["status"] = "complete"
        job["orchestrator_response"] = response.model_dump()
        job["processing_time_ms"] = processing_time
        job["completed_at"] = datetime.utcnow().isoformat()
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["completed_at"] = datetime.utcnow().isoformat()


@router.get("/queries/{query_id}")
async def get_query(query_id: str) -> dict:
    """Get a specific query with its responses."""
    from src.data.db import DatabaseManager

    db = DatabaseManager()
    try:
        query = await db.get_query(query_id)
        if query is None:
            raise HTTPException(status_code=404, detail="Query not found")

        agent_responses = await db.get_agent_responses(query_id)
        orchestrator_response = await db.get_orchestrator_response(query_id)
        # Fix 8: use the correct method name
        feedback = await db.get_feedback_for_query(query_id)

        result = query.model_dump()
        result["agent_responses"] = [r.model_dump() for r in agent_responses]
        if orchestrator_response:
            result["orchestrator_response"] = orchestrator_response.model_dump()
        if feedback:
            result["feedback"] = feedback.model_dump()

        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback")
async def submit_feedback(record: FeedbackRecord) -> dict:
    """Submit feedback for a query."""
    from src.data.db import DatabaseManager

    db = DatabaseManager()
    try:
        await db.save_feedback(record)
        return {"status": "ok", "feedback_id": record.feedback_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback/export")
async def export_feedback() -> JSONResponse:
    """Export all feedback records as JSON."""
    from src.data.db import DatabaseManager

    db = DatabaseManager()
    try:
        feedback_list = await db.export_feedback()
        return JSONResponse(content=feedback_list)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
