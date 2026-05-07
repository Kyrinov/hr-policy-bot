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
        assert config.model.specialist_name == "gemma4:e4b"
        assert config.model.orchestrator_host == "http://127.0.0.1:11436"
        assert config.model.specialist_host == "http://127.0.0.1:11435"
        assert config.model.think is False
        assert config.model.orchestrator_num_predict == 1800
        assert config.model.specialist_num_predict == 1000
        assert config.model.route_with_llm is False
        assert config.model.final_gate_enabled is True
        assert config.model.final_gate_findings_chars == 900

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

    def test_split_ollama_env_overrides(self, monkeypatch):
        """Test role-specific Ollama runtime environment overrides."""
        from src.config import get_config

        get_config.cache_clear()
        monkeypatch.setenv("OLLAMA_ORCHESTRATOR_MODEL", "orchestrator:test")
        monkeypatch.setenv("OLLAMA_SPECIALIST_MODEL", "specialist:test")
        monkeypatch.setenv("OLLAMA_ORCHESTRATOR_HOST", "http://127.0.0.1:12001")
        monkeypatch.setenv("OLLAMA_SPECIALIST_HOST", "http://127.0.0.1:12002")
        config = get_config()
        assert config.model.name == "orchestrator:test"
        assert config.model.specialist_name == "specialist:test"
        assert config.model.orchestrator_host == "http://127.0.0.1:12001"
        assert config.model.specialist_host == "http://127.0.0.1:12002"
        get_config.cache_clear()


class TestOllamaClient:
    """Test Ollama client wrapper behavior."""

    @pytest.fixture
    def fake_async_client(self, monkeypatch):
        """Patch ollama.AsyncClient with a fake client."""
        from src.config import get_config
        import src.llm.client as llm_client

        calls = []
        hosts = []

        class FakeAsyncClient:
            def __init__(self, host=None):
                hosts.append(host)

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
                        SimpleNamespace(model="gemma4:e4b"),
                        SimpleNamespace(model="other-model"),
                    ]
                )

            async def generate(self, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(response="")

        get_config.cache_clear()
        llm_client._orchestrator_client = None
        llm_client._specialist_client = None
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_ORCHESTRATOR_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_SPECIALIST_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_ORCHESTRATOR_HOST", raising=False)
        monkeypatch.delenv("OLLAMA_SPECIALIST_HOST", raising=False)
        monkeypatch.setattr(llm_client.ollama, "AsyncClient", FakeAsyncClient)
        yield calls, hosts
        llm_client._orchestrator_client = None
        llm_client._specialist_client = None
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
        calls, _hosts = fake_async_client
        assert calls[0]["model"] == "gemma4:31b"
        assert calls[0]["options"] == {
            "num_ctx": 32768,
            "temperature": 0.2,
            "top_p": 0.9,
        }
        assert calls[0]["think"] is False

    @pytest.mark.asyncio
    async def test_stream_chat_yields_message_content(self, fake_async_client):
        """Test stream_chat yields streamed content chunks."""
        from src.llm.client import OllamaClient

        client = OllamaClient()
        chunks = [chunk async for chunk in client.stream_chat("system", "user")]

        assert chunks == ["hello", " world"]
        calls, _hosts = fake_async_client
        assert calls[0]["stream"] is True
        assert calls[0]["think"] is False

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
        assert health["host"] == "default"
        assert health["model_available"] is True

    @pytest.mark.asyncio
    async def test_unload_uses_keep_alive_zero(self, fake_async_client):
        """Test unload asks Ollama to release the configured model."""
        from src.llm.client import OllamaClient

        client = OllamaClient()
        await client.unload()
        calls, _hosts = fake_async_client

        assert calls[0] == {
            "model": "gemma4:31b",
            "prompt": "",
            "keep_alive": 0,
        }

    def test_role_clients_use_separate_hosts_and_models(self, fake_async_client):
        """Test role-specific client factories separate orchestrator and specialists."""
        from src.llm.client import get_orchestrator_client, get_specialist_client

        orchestrator = get_orchestrator_client()
        specialist = get_specialist_client()
        _calls, hosts = fake_async_client

        assert orchestrator is not specialist
        assert hosts == ["http://127.0.0.1:11436", "http://127.0.0.1:11435"]
        assert orchestrator._model == "gemma4:31b"
        assert specialist._model == "gemma4:e4b"
        assert orchestrator._num_predict == 1800
        assert specialist._num_predict == 1000


class TestOrchestratorEvidenceGate:
    """Test final evidence gating and citation pruning."""

    @pytest.fixture
    def orchestrator(self):
        from src.agents.orchestrator import OrchestratorAgent

        return OrchestratorAgent()

    @pytest.fixture
    def specialist_responses(self):
        return [
            {
                "agent_id": "staffing",
                "findings": "Staffing finding",
                "citations": [
                    {
                        "instrument_title": "Staffing Policy",
                        "instrument_type": "Policy / Directive",
                        "url": "https://example.com/staffing",
                        "relevant_section": "1",
                    }
                ],
                "confidence": "high",
                "retrieval_status": {
                    "instruments_attempted": 1,
                    "instruments_successfully_retrieved": 1,
                    "instruments_failed": [],
                },
            },
            {
                "agent_id": "learning",
                "findings": "Learning not relevant",
                "citations": [
                    {
                        "instrument_title": "Learning Policy",
                        "instrument_type": "Policy / Directive",
                        "url": "https://example.com/learning",
                        "relevant_section": "2",
                    }
                ],
                "confidence": "low",
                "retrieval_status": {
                    "instruments_attempted": 1,
                    "instruments_successfully_retrieved": 1,
                    "instruments_failed": [],
                },
            },
        ]

    def test_filtered_citations_excludes_unused_agents(
        self, orchestrator, specialist_responses
    ):
        final_citations = [
            {
                "instrument_title": "Staffing Policy",
                "instrument_type": "Policy / Directive",
                "url": "https://example.com/staffing",
                "relevant_section": "1",
                "sourced_from_agent": "staffing",
            },
            {
                "instrument_title": "Learning Policy",
                "instrument_type": "Policy / Directive",
                "url": "https://example.com/learning",
                "relevant_section": "2",
                "sourced_from_agent": "learning",
            },
        ]

        citations = orchestrator._filtered_citations(
            final_citations, specialist_responses, {"staffing"}
        )

        assert [c.sourced_from_agent for c in citations] == ["staffing"]
        assert citations[0].instrument_title == "Staffing Policy"

    def test_filtered_citations_falls_back_to_used_agent_sources(
        self, orchestrator, specialist_responses
    ):
        citations = orchestrator._filtered_citations(
            [], specialist_responses, {"staffing"}
        )

        assert [c.sourced_from_agent for c in citations] == ["staffing"]
        assert citations[0].instrument_title == "Staffing Policy"

    @pytest.mark.asyncio
    async def test_final_gate_selects_valid_agents(
        self, orchestrator, specialist_responses
    ):
        class FakeClient:
            async def chat(self, **kwargs):
                return '{"selected_agents": ["staffing"], "excluded_agents": ["learning"], "rationale": {"staffing": "relevant", "learning": "not relevant"}}'

        orchestrator._llm_client = FakeClient()

        gated = await orchestrator._gate_final_responses(
            "Can I staff this position?", specialist_responses
        )

        assert [response["agent_id"] for response in gated] == ["staffing"]

    @pytest.mark.asyncio
    async def test_final_gate_failure_uses_all_specialists(
        self, orchestrator, specialist_responses
    ):
        class FakeClient:
            async def chat(self, **kwargs):
                return "not json"

        orchestrator._llm_client = FakeClient()

        gated = await orchestrator._gate_final_responses(
            "Can I staff this position?", specialist_responses
        )

        assert gated == specialist_responses


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
