from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from src.models.schemas import (
    FeedbackRecord,
    WSAgentStatusUpdate,
    WSError,
)

router = APIRouter()


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
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Fix 2: use AsyncClient, not module-level sync ollama.list()
    try:
        import ollama

        client = ollama.AsyncClient()
        models = await client.list()
        result["components"]["ollama"] = {
            "status": "ok",
            "models": [m.model for m in models.models],
        }
    except Exception as e:
        result["components"]["ollama"] = {"status": "error", "error": str(e)}
        result["status"] = "degraded"

    try:
        import aiosqlite
        from pathlib import Path

        db_path = Path(__file__).parent.parent.parent / "data" / "hr_policy_agent.db"
        if db_path.exists():
            async with aiosqlite.connect(db_path) as db:
                async with db.execute("SELECT COUNT(*) FROM queries") as cursor:
                    row = await cursor.fetchone()
                    query_count = row[0] if row else 0
                async with db.execute("SELECT COUNT(*) FROM feedback") as cursor:
                    row = await cursor.fetchone()
                    feedback_count = row[0] if row else 0
            result["components"]["database"] = {
                "status": "ok",
                "query_count": query_count,
                "feedback_count": feedback_count,
            }
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
