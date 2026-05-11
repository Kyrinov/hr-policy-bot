# DND HR-Civ Policy Bot

This branch adds a deterministic KISS/Sage parsing layer to the existing multi-agent HR policy advisory system.

## Deterministic Parser Change

The new parsing layer runs before LLM validation and annotates fetched policy text with deterministic KISS categories:

- `ENTITY`
- `VERB`
- `CONNECTOR`
- `PUNCTUATION`

GC-specific terms of art, classification levels, language profiles, HR process terms, organizational actors, and policy instrument titles are resolved through a longest-match entity override list before POS tagging. Deontic verbs such as `must`, `shall`, `may`, and `must not` are classified into obligation, discretion, recommendation, or prohibition.

The Sage extractor converts tagged policy sentences into policy triples, validates them with deterministic rule flags, and stores the result in SQLite graph tables through `DatabaseManager`. Specialist agents can use graph results in VALIDATE mode when enough matching triples exist; otherwise they fall back to the existing live-fetch EXTRACT flow.

## Key Files

- `src/parsing/gc_entities.py`: GC entity definitions and longest-match phrase matcher.
- `src/parsing/kiss_parser.py`: deterministic document parser.
- `src/parsing/query_kiss_parser.py`: query-only entity and verb parser with no graph writes.
- `src/parsing/sage_extractor.py`: SVO triple extraction and validation flagging.
- `src/parsing/graph_query.py`: graph retrieval interface for agents.
- `src/data/deontic_verbs.py`: static GC deontic verb classifications.
- `src/data/db.py`: additive KISS/Sage graph tables and persistence methods.
- `data/manual_policy_cache/manifest.json`: static public-document cache used before live fetches.
- `scripts/ingest_public_documents.py`: local ingestion tool for manually downloaded public PDFs/HTML/text.
- `docs/PUBLIC_DOCUMENT_INGESTION.md`: demo-safe public document ingestion workflow.

## Reliability Posture

The existing system remains the fallback path. If parsing is disabled, unavailable, sparse, or fails in the background, live fetch and EXTRACT mode continue. Background parsing exceptions are logged and do not surface to users or block retrieval.

The parser treats source policy text as data, not instructions. VALIDATE mode prompts restrict citations to instruments present in retrieved deterministic triples to reduce prompt-injection and source-confusion risk.
