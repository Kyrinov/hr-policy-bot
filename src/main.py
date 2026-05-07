from __future__ import annotations

import logging
from pathlib import Path

from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router as api_router
from src.api.websocket import router as websocket_router
from src.config import get_config
from src.data.db import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

config = get_config()

app = FastAPI(
    title="DND HR-Civ Policy Advisory System",
    description="Multi-agent policy advisory system for DND civilian HR",
    version="0.1.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
static_path = Path(__file__).parent.parent / "static"
if not static_path.exists():
    logger.warning("Static directory not found at %s", static_path)
    static_path = None
else:
    # Serve CSS and JS at the paths the HTML references (/css/... and /js/...)
    app.mount("/css", StaticFiles(directory=str(static_path / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(static_path / "js")), name="js")
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Routes
app.include_router(api_router, prefix="/api")
app.include_router(websocket_router)


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize database and check dependencies on startup."""
    logger.info("Starting DND HR-Civ Policy Advisory System")

    # Initialize database
    db = DatabaseManager()
    await db.initialize()
    logger.info("Database initialized")

    # Check Ollama connectivity
    try:
        from src.llm.client import get_client

        ollama_health = await get_client().health_check()
        logger.info(
            "Ollama health: status=%s configured_model=%s model_available=%s",
            ollama_health["status"],
            ollama_health["configured_model"],
            ollama_health["model_available"],
        )
    except Exception as e:
        logger.warning("Ollama connection failed: %s", e)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Clean up browser and HTTP client on shutdown."""
    from src.fetch.browser import cleanup_browser_fetcher
    from src.fetch.engine import cleanup_fetch_engine
    logger.info("Shutting down fetch resources")
    await cleanup_browser_fetcher()
    await cleanup_fetch_engine()


@app.get("/")
async def root() -> FileResponse:
    """Serve the GUI."""
    return FileResponse(str(static_path / "index.html"))


@app.get("/health")
async def health_check() -> dict:
    """System health check endpoint."""
    from src.fetch.cache import get_cache

    health = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
    }

    # Check database
    try:
        db = DatabaseManager()
        health["database"] = "ok"
    except Exception as e:
        health["database"] = f"error: {str(e)}"
        health["status"] = "degraded"

    # Check cache
    try:
        cache = get_cache()
        cache_health = await cache.health_check()
        health["cache"] = cache_health
    except Exception as e:
        health["cache"] = f"error: {str(e)}"

    return health
