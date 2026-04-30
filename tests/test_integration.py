"""Integration tests for the DND HR-Civ Policy Advisory System."""

import pytest
from src.models.schemas import PolicyInstrument, SpecialistResponse, RetrievalStatus


class TestPydanticModels:
    """Test Pydantic model validation."""

    def test_policy_instrument(self):
        """Test PolicyInstrument model."""
        instrument = PolicyInstrument(
            id="test-instrument",
            title="Test Instrument",
            type="Policy / Directive",
            url="https://example.com/test",
            agent_ids=["staffing", "classification"],
        )
        assert instrument.id == "test-instrument"
        assert len(instrument.agent_ids) == 2

    def test_specialist_response(self):
        """Test SpecialistResponse model."""
        response = SpecialistResponse(
            agent_id="staffing",
            findings="Test findings",
            citations=[],
            confidence="high",
            retrieval_status=RetrievalStatus(
                instruments_attempted=5,
                instruments_successfully_retrieved=5,
                instruments_failed=[],
            ),
        )
        assert response.agent_id == "staffing"
        assert response.confidence == "high"


class TestConfig:
    """Test configuration loading."""

    def test_config_loaded(self):
        """Test that configuration loads correctly."""
        from src.config import get_config

        config = get_config()
        assert config is not None
        assert hasattr(config, "model")
        assert hasattr(config, "server")


class TestDatabase:
    """Test database operations."""

    @pytest.fixture
    def db_manager(self):
        """Create database manager for tests."""
        from src.data.db import DatabaseManager

        return DatabaseManager()

    @pytest.mark.asyncio
    async def test_database_initialization(self, db_manager):
        """Test database initializes without errors."""
        await db_manager.initialize()

    @pytest.mark.asyncio
    async def test_save_and_get_query(self, db_manager):
        """Test saving and retrieving query records."""
        import uuid

        from src.models.schemas import QueryRecord
        from datetime import datetime

        query_id = str(uuid.uuid4())
        record = QueryRecord(
            query_id=query_id,
            query_text="Test query",
            agents_invoked=["staffing"],
        )

        await db_manager.save_query(record)
        retrieved = await db_manager.get_query(query_id)

        assert retrieved is not None
        assert retrieved.query_id == query_id


class TestFetchEngine:
    """Test fetch engine functionality."""

    @pytest.fixture
    def fetch_engine(self):
        """Create fetch engine for tests."""
        from src.fetch.engine import FetchEngine

        return FetchEngine()

    def test_fetch_engine_creation(self, fetch_engine):
        """Test fetch engine can be created."""
        assert fetch_engine is not None

    @pytest.mark.asyncio
    async def test_fetch_health_check(self, fetch_engine):
        """Test fetch engine health check."""
        health = await fetch_engine.health_check()
        assert health["status"] == "ok"


class TestContentExtractor:
    """Test content extraction."""

    def test_extractor_creation(self):
        """Test content extractor can be created."""
        from src.fetch.extractors import ContentExtractor

        extractor = ContentExtractor()
        assert extractor is not None

    def test_extract_text_from_html(self):
        """Test basic text extraction from HTML."""
        from src.fetch.extractors import ContentExtractor

        extractor = ContentExtractor()
        html = """
        <html>
            <body>
                <h1>Test Heading</h1>
                <p>Test paragraph content.</p>
            </body>
        </html>
        """
        result = extractor.extract("https://example.com", html)
        assert "Test Heading" in result
        assert "Test paragraph content" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
