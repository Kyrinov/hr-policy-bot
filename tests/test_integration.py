"""Integration tests for the DND HR-Civ Policy Advisory System."""

from types import SimpleNamespace

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
        assert config.model.name == "gemma4:31b"

    def test_ollama_model_env_override(self, monkeypatch):
        """Test OLLAMA_MODEL overrides the configured model."""
        from src.config import get_config

        get_config.cache_clear()
        monkeypatch.setenv("OLLAMA_MODEL", "test-model:latest")
        config = get_config()
        assert config.model.name == "test-model:latest"
        get_config.cache_clear()

    def test_unrelated_model_env_var_does_not_override_model(self, monkeypatch):
        """Test unrelated model environment variables are ignored."""
        from src.config import get_config

        get_config.cache_clear()
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.setenv("MODEL_NAME", "unrelated-model")
        config = get_config()
        assert config.model.name == "gemma4:31b"
        get_config.cache_clear()


class TestOllamaClient:
    """Test Ollama client wrapper behavior."""

    @pytest.fixture
    def fake_async_client(self, monkeypatch):
        """Patch ollama.AsyncClient with a fake client."""
        from src.config import get_config
        import src.llm.client as llm_client

        calls = []

        class FakeAsyncClient:
            async def chat(self, **kwargs):
                calls.append(kwargs)
                if kwargs.get("stream"):
                    async def stream():
                        yield SimpleNamespace(
                            message=SimpleNamespace(content="hello")
                        )
                        yield SimpleNamespace(
                            message=SimpleNamespace(content=" world")
                        )

                    return stream()
                return SimpleNamespace(
                    message=SimpleNamespace(content='{"status": "ok"}')
                )

            async def list(self):
                return SimpleNamespace(
                    models=[
                        SimpleNamespace(model="gemma4:31b"),
                        SimpleNamespace(model="other-model"),
                    ]
                )

        get_config.cache_clear()
        llm_client._client = None
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.setattr(llm_client.ollama, "AsyncClient", FakeAsyncClient)
        yield calls
        llm_client._client = None
        get_config.cache_clear()

    @pytest.mark.asyncio
    async def test_chat_uses_configured_ollama_model_and_options(
        self, fake_async_client
    ):
        """Test chat calls Ollama with configured model and options."""
        from src.llm.client import OllamaClient

        client = OllamaClient()
        response = await client.chat("system", "user")

        assert response == '{"status": "ok"}'
        assert fake_async_client[0]["model"] == "gemma4:31b"
        assert fake_async_client[0]["options"] == {
            "num_ctx": 32768,
            "temperature": 0.2,
            "top_p": 0.9,
        }

    @pytest.mark.asyncio
    async def test_stream_chat_yields_message_content(self, fake_async_client):
        """Test stream_chat yields streamed content chunks."""
        from src.llm.client import OllamaClient

        client = OllamaClient()
        chunks = [chunk async for chunk in client.stream_chat("system", "user")]

        assert chunks == ["hello", " world"]
        assert fake_async_client[0]["stream"] is True

    @pytest.mark.asyncio
    async def test_chat_parsed_preserves_json_parsing_behavior(
        self, fake_async_client
    ):
        """Test chat_parsed returns parsed JSON."""
        from src.llm.client import OllamaClient

        client = OllamaClient()
        parsed = await client.chat_parsed("system", "user")

        assert parsed == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_health_check_reports_configured_model(self, fake_async_client):
        """Test health check verifies the configured Ollama model."""
        from src.llm.client import OllamaClient

        client = OllamaClient()
        health = await client.health_check()

        assert health["status"] == "ok"
        assert health["configured_model"] == "gemma4:31b"
        assert health["model_available"] is True


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
