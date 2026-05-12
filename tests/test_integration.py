"""Integration tests for the DND HR-Civ Policy Advisory System."""

import json
from types import SimpleNamespace

import httpx
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
        assert config.model.orchestrator_auth_header is None
        assert config.model.specialist_auth_header is None
        assert config.model.think is False
        assert config.model.orchestrator_num_predict == 1800
        assert config.model.specialist_num_predict == 1000
        assert config.model.route_with_llm is False
        assert config.storage.data_dir == "data"
        assert config.storage.database_url is None

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
        monkeypatch.setenv("OLLAMA_ORCHESTRATOR_AUTH_HEADER", "Bearer orch")
        monkeypatch.setenv("OLLAMA_SPECIALIST_AUTH_HEADER", "Bearer spec")
        config = get_config()
        assert config.model.name == "orchestrator:test"
        assert config.model.specialist_name == "specialist:test"
        assert config.model.orchestrator_host == "http://127.0.0.1:12001"
        assert config.model.specialist_host == "http://127.0.0.1:12002"
        assert config.model.orchestrator_auth_header == "Bearer orch"
        assert config.model.specialist_auth_header == "Bearer spec"
        get_config.cache_clear()

    def test_render_env_overrides(self, monkeypatch):
        """Test Render-style environment overrides."""
        from src.config import get_config

        get_config.cache_clear()
        monkeypatch.setenv("PORT", "10000")
        monkeypatch.setenv("APP_DATA_DIR", "/var/data")
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
        monkeypatch.setenv("BROWSER_FETCH_ENABLED", "false")
        monkeypatch.setenv("PARSING_ENABLED", "false")
        monkeypatch.setenv("PARSING_TEACHER_LOOP_ENABLED", "false")
        config = get_config()
        assert config.server.port == 10000
        assert config.storage.data_dir == "/var/data"
        assert config.storage.database_url == "postgresql://user:pass@localhost/testdb"
        assert config.fetch.browser_fallback_enabled is False
        assert config.parsing.enabled is False
        assert config.parsing.teacher_loop_enabled is False
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
        client_kwargs = []

        class FakeAsyncClient:
            def __init__(self, host=None, **kwargs):
                hosts.append(host)
                client_kwargs.append(kwargs)

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
        monkeypatch.delenv("OLLAMA_AUTH_HEADER", raising=False)
        monkeypatch.delenv("OLLAMA_ORCHESTRATOR_AUTH_HEADER", raising=False)
        monkeypatch.delenv("OLLAMA_SPECIALIST_AUTH_HEADER", raising=False)
        monkeypatch.delenv("PARSING_ENABLED", raising=False)
        monkeypatch.delenv("PARSING_TEACHER_LOOP_ENABLED", raising=False)
        monkeypatch.setattr(llm_client.ollama, "AsyncClient", FakeAsyncClient)
        yield calls, hosts, client_kwargs
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
        calls, _hosts, _client_kwargs = fake_async_client
        assert calls[0]["model"] == "gemma4:31b"
        assert calls[0]["options"] == {
            "num_ctx": 32768,
            "temperature": 0.2,
            "top_p": 0.9,
        }
        assert calls[0]["think"] is False

    @pytest.mark.asyncio
    async def test_chat_retries_transient_transport_error(self, monkeypatch):
        """Test chat retries one transient Ollama transport failure."""
        from src.config import get_config
        import src.llm.client as llm_client
        from src.llm.client import OllamaClient

        calls = []

        class FlakyAsyncClient:
            def __init__(self, host=None, **kwargs):
                pass

            async def chat(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    raise httpx.RemoteProtocolError(
                        "Server disconnected without sending a response."
                    )
                return SimpleNamespace(message=SimpleNamespace(content="ok"))

        get_config.cache_clear()
        monkeypatch.setattr(llm_client.ollama, "AsyncClient", FlakyAsyncClient)
        monkeypatch.setattr(OllamaClient, "_CHAT_RETRY_BASE_SECONDS", 0)

        client = OllamaClient()
        response = await client.chat("system", "user")

        assert response == "ok"
        assert len(calls) == 2
        get_config.cache_clear()

    @pytest.mark.asyncio
    async def test_stream_chat_yields_message_content(self, fake_async_client):
        """Test stream_chat yields streamed content chunks."""
        from src.llm.client import OllamaClient

        client = OllamaClient()
        chunks = [chunk async for chunk in client.stream_chat("system", "user")]

        assert chunks == ["hello", " world"]
        calls, _hosts, _client_kwargs = fake_async_client
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
        calls, _hosts, _client_kwargs = fake_async_client

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
        _calls, hosts, client_kwargs = fake_async_client

        assert orchestrator is not specialist
        assert hosts == ["http://127.0.0.1:11436", "http://127.0.0.1:11435"]
        assert client_kwargs == [{"headers": None}, {"headers": None}]
        assert orchestrator._model == "gemma4:31b"
        assert specialist._model == "gemma4:e4b"
        assert orchestrator._num_predict == 1800
        assert specialist._num_predict == 1000


class TestOrchestrator:
    """Test orchestrator synthesis behavior."""

    @pytest.mark.asyncio
    async def test_orchestrator_preserves_synthesis_citation_filter(
        self, monkeypatch
    ):
        """Test final citations come from synthesis, not all specialist citations."""
        import json

        import src.agents.orchestrator as orchestrator_module
        from src.config import get_config
        from src.agents.orchestrator import OrchestratorAgent

        class FakeOllamaClient:
            async def chat(self, system_prompt, user_message, model=None):
                return json.dumps(
                    {
                        "summary": "Use the Policy on People Management.",
                        "detailed_analysis": "The relevant rule is in the staffing instrument.",
                        "policy_tensions": None,
                        "citations": [
                            {
                                "instrument_title": "Policy on People Management",
                                "instrument_type": "",
                                "url": None,
                                "relevant_section": None,
                                "sourced_from_agent": "staffing",
                            }
                        ],
                        "gaps_and_limitations": None,
                        "recommended_consultation": None,
                        "agents_consulted": ["staffing"],
                        "overall_confidence": "high",
                    }
                )

        get_config.cache_clear()
        monkeypatch.setattr(
            orchestrator_module,
            "get_orchestrator_client",
            lambda: FakeOllamaClient(),
        )

        agent = OrchestratorAgent()
        response = await agent.process(
            "What policy applies?",
            [
                {
                    "agent_id": "staffing",
                    "findings": "Relevant staffing finding.",
                    "confidence": "high",
                    "citations": [
                        {
                            "instrument_title": "Policy on People Management",
                            "instrument_type": "Policy / Directive",
                            "url": "https://example.test/people-management",
                            "relevant_section": "Section 4",
                        },
                        {
                            "instrument_title": "Unrelated Staffing Instrument",
                            "instrument_type": "Policy / Directive",
                            "url": "https://example.test/unrelated-staffing",
                            "relevant_section": "Section 1",
                        },
                    ],
                },
                {
                    "agent_id": "languages",
                    "findings": "No relevant languages finding.",
                    "confidence": "low",
                    "citations": [
                        {
                            "instrument_title": "Official Languages Act",
                            "instrument_type": "Legislation",
                            "url": "https://example.test/official-languages",
                            "relevant_section": "Section 2",
                        }
                    ],
                },
            ],
        )

        assert [c.instrument_title for c in response.citations] == [
            "Policy on People Management"
        ]
        assert response.citations[0].instrument_type == "Policy / Directive"
        assert response.citations[0].url == "https://example.test/people-management"
        assert response.citations[0].relevant_section == "Section 4"
        get_config.cache_clear()

    @pytest.mark.asyncio
    async def test_orchestrator_fills_missing_sourced_from_agent(
        self, monkeypatch
    ):
        """Test synthesis citations do not fail when sourced_from_agent is omitted."""
        import json

        import src.agents.orchestrator as orchestrator_module
        from src.config import get_config
        from src.agents.orchestrator import OrchestratorAgent

        class FakeOllamaClient:
            async def chat(self, system_prompt, user_message, model=None):
                return json.dumps(
                    {
                        "summary": "Official languages requirements apply.",
                        "detailed_analysis": "The answer relies on official languages staffing rules.",
                        "policy_tensions": None,
                        "citations": [
                            {
                                "instrument_title": "Official Languages Act",
                                "instrument_type": "Legislation",
                                "url": "https://example.test/official-languages",
                                "relevant_section": "Part IV",
                            }
                        ],
                        "gaps_and_limitations": None,
                        "recommended_consultation": None,
                        "agents_consulted": ["languages"],
                        "overall_confidence": "high",
                    }
                )

        get_config.cache_clear()
        monkeypatch.setattr(
            orchestrator_module,
            "get_orchestrator_client",
            lambda: FakeOllamaClient(),
        )

        agent = OrchestratorAgent()
        response = await agent.process(
            "Can this be bilingual imperative?",
            [
                {
                    "agent_id": "languages",
                    "findings": "Relevant official languages finding.",
                    "confidence": "high",
                    "citations": [
                        {
                            "instrument_title": "Official Languages Act",
                            "instrument_type": "Legislation",
                            "url": "https://example.test/official-languages",
                            "relevant_section": "Part IV",
                        }
                    ],
                },
            ],
        )

        assert response.summary == "Official languages requirements apply."
        assert response.citations[0].sourced_from_agent == "languages"
        get_config.cache_clear()


class TestPollingQueryApi:
    """Test HTTPS polling fallback behavior."""

    @pytest.mark.asyncio
    async def test_polling_query_job_completes(self, monkeypatch):
        """Test polling job stores status updates and final response."""
        import src.api.routes as routes
        from src.models.schemas import OrchestratorResponse, WSAgentStatusUpdate

        query_id = "polling-test-query"

        class FakeOrchestrator:
            async def process_with_streaming(
                self,
                query_text,
                fetch_engine,
                status_callback,
            ):
                await status_callback(
                    WSAgentStatusUpdate(agent_id="orchestrator", status="working")
                )
                await status_callback(
                    WSAgentStatusUpdate(agent_id="staffing", status="complete")
                )
                return OrchestratorResponse(
                    summary="Polling response",
                    detailed_analysis="Polling analysis",
                    citations=[],
                    agents_consulted=["staffing"],
                    overall_confidence="high",
                )

        class FakeDatabaseManager:
            async def save_query(self, record):
                pass

            async def save_orchestrator_response(self, record):
                pass

        monkeypatch.setattr(routes, "get_orchestrator", lambda: FakeOrchestrator())
        monkeypatch.setattr(routes, "get_fetch_engine", lambda: object())
        monkeypatch.setattr(routes, "get_db_manager", lambda: FakeDatabaseManager())

        routes._POLLING_JOBS[query_id] = {
            "query_id": query_id,
            "query_text": "test",
            "status": "queued",
            "agent_statuses": {},
            "orchestrator_response": None,
            "processing_time_ms": None,
            "error": None,
            "started_at": "now",
        }
        await routes._run_polling_query(query_id, "test")

        job = routes._POLLING_JOBS[query_id]
        assert job["status"] == "complete"
        assert job["orchestrator_response"]["summary"] == "Polling response"
        assert job["agent_statuses"]["orchestrator"]["status"] == "working"
        assert job["agent_statuses"]["staffing"]["status"] == "complete"


class TestDatabase:
    """Test database operations."""

    @pytest.fixture
    def db_manager(self):
        """Create database manager for tests. Skipped if DATABASE_URL is not set."""
        import os
        from src.data.db import DatabaseManager

        if not os.environ.get("DATABASE_URL"):
            pytest.skip("DATABASE_URL not set — skipping PostgreSQL tests")
        return DatabaseManager()

    @pytest.mark.asyncio
    async def test_database_initialization(self, db_manager):
        """Test database initializes without errors."""
        await db_manager.initialize()
        await db_manager.close()

    @pytest.mark.asyncio
    async def test_save_and_get_query(self, db_manager):
        """Test saving and retrieving query records."""
        import uuid
        from src.models.schemas import QueryRecord

        await db_manager.initialize()
        try:
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
        finally:
            await db_manager.close()

    def test_database_url_env_var_is_respected(self, monkeypatch):
        """Test DatabaseManager picks up DATABASE_URL from environment."""
        from src.config import get_config
        from src.data.db import DatabaseManager

        get_config.cache_clear()
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
        try:
            config = get_config()
            assert config.storage.database_url == "postgresql://user:pass@localhost/testdb"
            db = DatabaseManager()
            assert "localhost" in db._database_url
        finally:
            get_config.cache_clear()


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
    async def test_fetch_engine_prefers_manual_policy_cache(self, tmp_path):
        """Test manual policy cache is read before network/cache fetches."""
        from src.fetch.engine import FetchEngine
        from src.fetch.manual_cache import ManualPolicyCache

        text_path = tmp_path / "policy.txt"
        text_path.write_text("manual policy text", encoding="utf-8")
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "url": "https://example.test/policy",
                            "normalized_url": "https://example.test/policy",
                            "path": str(text_path),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        class FakeCache:
            async def get(self, url):
                raise AssertionError("database cache should not be used")

        engine = FetchEngine(
            cache=FakeCache(),
            manual_policy_cache=ManualPolicyCache(manifest_path),
        )
        content = await engine._do_fetch("https://example.test/policy")

        assert content == "manual policy text"

    @pytest.mark.asyncio
    async def test_fetch_health_check(self, fetch_engine):
        """Test fetch engine health check."""
        health = await fetch_engine.health_check()
        assert health["status"] == "ok"


class TestSpecialistRetrieval:
    """Test specialist retrieval preparation."""

    def test_select_relevant_content_prefers_query_matching_sections(self):
        """Long documents should use query-focused excerpts instead of first-page truncation."""
        from src.agents.specialist import select_relevant_content

        content = (
            "Collective Agreement\n\n"
            "Opening metadata and table of contents.\n\n"
            + ("Irrelevant classification text.\n\n" * 600)
            + "Article 28 Overtime\n\n"
            "An employee who works overtime may receive overtime compensation "
            "and a meal allowance when the agreement requirements are met.\n\n"
            + ("Other appendix text.\n\n" * 200)
        )

        excerpt = select_relevant_content(
            content=content,
            query_text="Does overtime include a meal allowance?",
            max_chars=2_000,
        )

        assert len(excerpt) <= 2_000
        assert "Collective Agreement" in excerpt
        assert "Article 28 Overtime" in excerpt
        assert "meal allowance" in excerpt

    def test_case_law_index_returns_labour_matches(self, tmp_path):
        """Compact FPSLREB index should retrieve query-matching labour examples."""
        from src.fetch.case_law import CaseLawIndex, format_case_law_context

        index_path = tmp_path / "cases.json"
        index_path.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "case_id": "fpslreb-test",
                            "title": "Example v. Deputy Head",
                            "citation": "2025 FPSLREB 1",
                            "decision_date": "2025-01-01",
                            "decision_type": "Labour Relations",
                            "subject_terms": ["Misconduct"],
                            "keywords": ["Suspension", "Discipline"],
                            "summary": "The Board considered discipline proportionality for a suspension.",
                            "disposition": "Grievance denied.",
                            "url": "https://example.test/case",
                            "agent_ids": ["labour"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        cases = CaseLawIndex(index_path).search(
            "Was the suspension discipline proportionate?",
            agent_id="labour",
        )
        context = format_case_law_context(cases)

        assert len(cases) == 1
        assert "2025 FPSLREB 1" in context
        assert "interpretive examples" in context

    def test_specialist_adds_case_law_context_only_for_labour(self, monkeypatch, tmp_path):
        """Only the labour specialist should see FPSLREB case-law context."""
        from src.agents.specialist import SpecialistAgent
        from src.fetch.case_law import CaseLawIndex

        index_path = tmp_path / "cases.json"
        index_path.write_text(
            json.dumps(
                {
                    "cases": [
                        {
                            "case_id": "fpslreb-test",
                            "title": "Example v. Deputy Head",
                            "citation": "2025 FPSLREB 1",
                            "decision_date": "2025-01-01",
                            "decision_type": "Labour Relations",
                            "subject_terms": ["Misconduct"],
                            "keywords": ["Suspension", "Discipline"],
                            "summary": "The Board considered discipline proportionality for a suspension.",
                            "disposition": "Grievance denied.",
                            "url": "https://example.test/case",
                            "agent_ids": ["labour"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        class FakeClient:
            pass

        monkeypatch.setattr(
            "src.agents.specialist.get_specialist_client",
            lambda: FakeClient(),
        )
        monkeypatch.setattr(
            "src.agents.specialist.get_case_law_index",
            lambda: CaseLawIndex(index_path),
        )

        labour = SpecialistAgent("labour", "Labour", "Labour relations")
        staffing = SpecialistAgent("staffing", "Staffing", "Staffing")

        assert "2025 FPSLREB 1" in labour._build_case_law_context("suspension discipline")
        assert staffing._build_case_law_context("suspension discipline") == ""


class TestPublicDocumentIngestion:
    """Test local public document ingestion helpers."""

    def test_ingest_cleanup_removes_page_chrome(self):
        """Cleanup should remove common Canada.ca chrome but keep policy text."""
        from scripts.ingest_public_documents import clean_text

        raw = """
        Skip to main content
        Search
        Policy Title

        Article 1
        The employee must follow the requirement.

        Page details
        Date modified:
        2026-01-01
        """

        cleaned = clean_text(raw)

        assert "Skip to main content" not in cleaned
        assert "Search" not in cleaned
        assert "Page details" not in cleaned
        assert "Policy Title" in cleaned
        assert "Article 1" in cleaned

    def test_ingest_id_inference_uses_registry_id_filename(self, tmp_path):
        """A source filename matching a registry id should infer that id."""
        from scripts.ingest_public_documents import infer_instrument_id

        source = tmp_path / "pa-group-collective-agreement.txt"
        source.write_text("source text", encoding="utf-8")
        registry = {"pa-group-collective-agreement": {"id": "pa-group-collective-agreement"}}

        instrument_id = infer_instrument_id(source, None, registry)

        assert instrument_id == "pa-group-collective-agreement"


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
