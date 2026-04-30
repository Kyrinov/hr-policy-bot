from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.agents.orchestrator import OrchestratorAgent, get_orchestrator
from src.config import get_config
from src.data.db import DatabaseManager
from src.fetch.engine import FetchEngine, get_fetch_engine
from src.models.schemas import (
    OrchestratorResponse,
    RetrievalStatus,
    WSAgentStatusUpdate,
    WSError,
    WSResponseComplete,
    WSResponseChunk,
)

logger = logging.getLogger(__name__)

router = APIRouter()
db = DatabaseManager()


class WebSocketManager:
    """Manages WebSocket connections for real-time agent updates."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    async def connect(self, query_id: str, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self._connections[query_id] = websocket
        logger.info("WebSocket connected for query %s", query_id)

    async def disconnect(self, query_id: str) -> None:
        """Remove a WebSocket connection."""
        if query_id in self._connections:
            del self._connections[query_id]
            logger.info("WebSocket disconnected for query %s", query_id)

    async def send(self, query_id: str, message: dict[str, Any]) -> None:
        """Send a message to a specific query's WebSocket."""
        if query_id in self._connections:
            try:
                await self._connections[query_id].send_json(message)
            except Exception:
                await self.disconnect(query_id)

    async def broadcast_error(self, message: str, query_id: str | None = None) -> None:
        """Send an error to all connected clients."""
        error = WSError(query_id=query_id, message=message)
        for qid in list(self._connections.keys()):
            try:
                await self._connections[qid].send_json(error.model_dump())
            except Exception:
                await self.disconnect(qid)


_manager: WebSocketManager | None = None


def get_websocket_manager() -> WebSocketManager:
    """Return singleton WebSocket manager."""
    global _manager
    if _manager is None:
        _manager = WebSocketManager()
    return _manager


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Main WebSocket endpoint for real-time agent communication."""
    query_id = str(uuid.uuid4())

    ws_manager = get_websocket_manager()
    orchestrator = get_orchestrator()
    fetch_engine = get_fetch_engine()

    await ws_manager.connect(query_id, websocket)

    active_task: asyncio.Task | None = None

    try:
        # Send welcome message
        await ws_manager.send(
            query_id, {"type": "session_welcome", "query_id": query_id}
        )

        # Wait for query message
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "query_start":
                query_text = data.get("query_text", "")
                active_task = asyncio.create_task(
                    process_query(
                        query_id,
                        websocket,
                        query_text,
                        orchestrator,
                        fetch_engine,
                        db,
                    )
                )
                await active_task

    except WebSocketDisconnect:
        if active_task and not active_task.done():
            active_task.cancel()
            logger.info("Query %s cancelled due to client disconnect", query_id)
        await ws_manager.disconnect(query_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            await ws_manager.broadcast_error(str(e), query_id)
        except Exception:
            pass
    finally:
        if active_task and not active_task.done():
            active_task.cancel()
        await ws_manager.disconnect(query_id)


async def process_query(
    query_id: str,
    websocket: WebSocket,
    query_text: str,
    orchestrator: OrchestratorAgent,
    fetch_engine: FetchEngine,
    db_manager: DatabaseManager,
) -> None:
    """Process a user query through the agent system."""
    start_time = datetime.utcnow()

    # Send user query message
    await websocket.send_json(
        {
            "type": "user_query",
            "query_id": query_id,
            "query_text": query_text,
        }
    )

    # Save query record
    from src.models.schemas import QueryRecord

    query_record = QueryRecord(
        query_id=query_id,
        query_text=query_text,
        agents_invoked=[],
    )
    await db_manager.save_query(query_record)

    try:
        # Run orchestrator with streaming support
        response = await orchestrator.process_with_streaming(
            query_text,
            fetch_engine,
            lambda status: websocket.send_json(status.model_dump()),
        )

        processing_time = (datetime.utcnow() - start_time).total_seconds() * 1000

        # Update query record
        query_record.processing_time_ms = int(processing_time)
        query_record.agents_invoked = response.agents_consulted
        query_record.overall_confidence = response.overall_confidence
        await db_manager.save_query(query_record)

        # Save orchestrator response
        from src.models.schemas import OrchestratorResponseRecord

        or_record = OrchestratorResponseRecord(
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
        await db_manager.save_orchestrator_response(or_record)

        # Send completion message
        await websocket.send_json(
            {
                "type": "response_complete",
                "query_id": query_id,
                "orchestrator_response": response.model_dump(),
                "processing_time_ms": int(processing_time),
            }
        )

        logger.info("Query %s completed in %dms", query_id, int(processing_time))

    except Exception as e:
        logger.error("Error processing query %s: %s", query_id, e)
        try:
            await websocket.send_json(
                {
                    "type": "error",
                    "query_id": query_id,
                    "message": f"Error processing query: {str(e)}",
                }
            )
        except Exception:
            pass
