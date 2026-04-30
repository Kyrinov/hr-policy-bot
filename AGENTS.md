# OpenCode Agent Context
# DND HR-Civ Multi-Agent Policy Advisory System

## Your Role

You are a local coding model implementing specific, well-scoped tasks for this project. Each task you receive will have:
- A clear **Input files** list (read these first)
- A clear **Output files** list (write exactly these)
- A detailed **Specification** (follow it precisely)
- **Acceptance criteria** (your output must satisfy all of them)
- A **Max scope** constraint (do not implement anything beyond this)

## Critical Rules

1. **Read input files before writing anything.** Understand the existing code structure, imports, and patterns before adding new code.
2. **Write only the output files specified.** Do not create additional files or modify files outside the task scope.
3. **Follow the specification exactly.** If something is unclear, implement the most conservative interpretation.
4. **Do not add features.** No extra error handling, no additional validation, no convenience wrappers beyond what is specified.
5. **Use Python 3.11+ features.** Type hints everywhere. Pydantic v2 for models. `async`/`await` for I/O.
6. **No hard-coded values.** Configuration comes from `config.yaml` via `src/config.py`. Use the `get_config()` function.
7. **No direct SQLite connections.** All database operations go through `src/data/db.py`.
8. **No direct httpx calls from agents.** All web fetching goes through `src/fetch/engine.py`.

## Code Style

- **Imports**: standard library first, then third-party, then local. One blank line between groups.
- **Type hints**: always. Use `Optional[X]` for nullable fields. Use `list[X]` not `List[X]`.
- **Async**: all I/O functions must be `async def`. Use `asyncio.gather()` for parallel operations.
- **Error handling**: catch specific exceptions. Log errors with context. Never silently swallow exceptions.
- **String formatting**: f-strings. No % formatting, no `.format()`.
- **No comments** on obvious code. Comments only where logic is non-obvious.

## Project Structure

```
src/
├── main.py              # FastAPI app entry point (TASK-017)
├── config.py            # Config loader — get_config() singleton (TASK-003)
├── agents/
│   ├── base.py          # Base agent interface (TASK-014)
│   ├── orchestrator.py  # Orchestrator agent (TASK-015)
│   ├── specialist.py    # Specialist agent (TASK-014)
│   └── prompts/
│       ├── orchestrator_prompt.py
│       └── specialist_prompts.py
├── fetch/
│   ├── engine.py        # Web fetch engine (TASK-009)
│   ├── cache.py         # SQLite cache layer (TASK-007)
│   ├── extractors.py    # HTML content extractors (TASK-008)
│   └── selectors.yaml   # CSS selectors per domain (TASK-008)
├── llm/
│   └── client.py        # Ollama client wrapper (TASK-006)
├── data/
│   ├── policy_registry.json  # Canonical instrument list (generated)
│   └── db.py            # Database manager (TASK-005)
├── api/
│   ├── routes.py        # REST endpoints (TASK-010)
│   └── websocket.py     # WebSocket handler (TASK-016)
└── models/
    └── schemas.py       # All Pydantic models (TASK-002)
```

## Policy Registry Format

`src/data/policy_registry.json` contains a list of instruments. Each instrument has:
```json
{
  "id": "slugified-title",
  "title": "Full instrument title",
  "type": "Legislation | Policy / Directive | PSC Instrument | NJC Directive | DND DAOD | ...",
  "url": "https://...",
  "agent_ids": ["agent1", "agent2"]
}
```

Agent IDs: `staffing`, `classification`, `labour`, `learning`, `equity`, `ohs`, `languages`, `governance`

## Pydantic Models (schemas.py)

All models are in `src/models/schemas.py`. Import them as:
```python
from src.models.schemas import QueryRecord, AgentResponse, OrchestratorResponse, ...
```

## Configuration

```python
from src.config import get_config

config = get_config()
model_name = config.model.name  # str
cache_ttl = config.cache.ttl_hours  # int
```

## Database Access

```python
from src.data.db import DatabaseManager

db = DatabaseManager()
await db.initialize()
await db.save_query(query_record)
```

## LLM Access

```python
from src.llm.client import OllamaClient

client = OllamaClient()
response = await client.chat(system_prompt, user_message)
# Streaming:
async for chunk in client.stream_chat(system_prompt, user_message):
    ...
```

## Fetch Engine Access

```python
from src.fetch.engine import FetchEngine

engine = FetchEngine()
content = await engine.fetch(url)
results = await engine.fetch_batch(urls)
```
