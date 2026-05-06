# DND HR-Civ Policy Bot — Deterministic KISS/Sage Layer
## Feature Branch Integration Plan

**Document Type:** Feature Branch Spec — Claude Code Handoff  
**Branch Name (suggested):** `feature/deterministic-parsing`  
**Base System:** DND HR-Civ Multi-Agent Policy Advisory System (implemented, April 2026)  
**Prepared by:** Claude Opus 4.6 (planning tier)  
**Classification:** Unclassified — Pilot / Proof of Concept  
**Source Reference:** "Deterministic AI Workflow for Agents" (LinkedIn demo video)

---

## 1. Context

The base system is **fully implemented and operational**. This plan describes a self-contained feature branch that adds a deterministic pre-processing layer between the existing Web Fetch Engine and the existing Specialist Agent LLM calls. Nothing in the base system is deleted. Existing behaviour is preserved as a fallback path.

**Before reading this plan, Claude Code should:**
1. Read `CLAUDE.md` in the project root
2. Read `src/fetch/engine.py` — the integration point for document parsing
3. Read `src/agents/specialist.py` — the integration point for VALIDATE mode
4. Read `src/db/manager.py` — the schema to be extended
5. Read `src/models/schemas.py` — the Pydantic models to be extended
6. Read `config.yaml` — the config structure to be extended

Do not begin implementation until you have read those five files and understand the existing interfaces.

---

## 2. What This Branch Adds

Two new processing layers inserted into the existing request pipeline:

**Layer 1 — KISS Parser:** A rules-based tagger that classifies every token in a fetched policy document as `ENTITY`, `VERB`, `CONNECTOR`, or `PUNCTUATION`. Runs deterministically before any LLM sees the document. Also applies in a lighter form to user queries (entity/verb extraction only — see Section 5).

**Layer 2 — Sage Layer:** Takes KISS-tagged document text, extracts subject-verb-object (SVO) triples, applies policy-domain validation rules, and writes the results to a new set of SQLite tables extending the existing database. On subsequent queries, triples are retrieved from the graph instead of re-extracting from the LLM.

**Net effect on existing system behaviour:**
- Specialist agents gain a `VALIDATE` mode (graph-grounded) alongside their existing `EXTRACT` mode (current behaviour)
- `EXTRACT` mode is preserved as the fallback — the system degrades gracefully to current behaviour if the graph is empty or parsing fails
- Response schema gains a `deterministic_grounding` metadata block
- The fetch engine triggers KISS/Sage as a fire-and-forget background task after each successful fetch — does not block existing response flow

---

## 3. Why — Design Rationale

The existing system fetches live policy content and passes it to the LLM for extraction and reasoning in a single probabilistic pass. For experienced HR policy advisors who will verify citations, this creates an unacceptable risk: the same policy text on two separate queries may yield different section attributions, or in the worst case, confabulated clause numbers.

The KISS/Sage layer addresses this by:

- **Extracting policy rules deterministically** before the LLM is involved
- **Storing structured triples** in SQLite, creating a verifiable, auditable knowledge base that accumulates across sessions
- **Shifting the LLM's function** from primary extractor to validator — a narrower, cheaper, more reliable task
- **Reducing token cost** on repeated queries to the same instruments (graph hit replaces full re-extraction)
- **Building a data flywheel**: every query that hits the graph improves it via an LLM teacher loop

---

## 4. Approach to Existing Code

### What is NOT touched
- `src/agents/orchestrator.py` — routing logic unchanged
- `src/api/websocket.py` — only a new status event type added (additive)
- `src/fetch/engine.py` — one call added after successful fetch (additive)
- All existing SQLite tables — schema extension only, no modifications
- All existing Pydantic models — extension only, no modifications
- All existing tests — must still pass on this branch

### What IS modified (minimally)
| File | Nature of Change |
|------|-----------------|
| `src/fetch/engine.py` | Add one `asyncio.create_task()` call after successful fetch+clean |
| `src/agents/specialist.py` | Add VALIDATE mode path; existing EXTRACT mode path unchanged |
| `src/db/manager.py` | Add new tables to `init_db()` — existing tables untouched |
| `src/models/schemas.py` | Add new dataclasses/Pydantic models — nothing modified |
| `config.yaml` | Add `parsing:` block — existing keys untouched |
| `requirements.txt` | Add `spacy`, `networkx`, model URL |
| `static/index.html` + JS/CSS | Add Grounding badge, Validation Flags panel, `parsing` agent state |

### What is NEW (new files only)
```
src/parsing/
├── __init__.py
├── gc_entities.py          # GC terminology override list (longest-match phrase lookup)
├── kiss_parser.py          # Document KISS tagger
├── query_kiss_parser.py    # Query-only KISS parser (no graph writes)
├── sage_extractor.py       # SVO triple extractor + validation state machine
└── graph_query.py          # Knowledge graph query interface

src/data/
└── deontic_verbs.py        # Static GC policy modal verb list

tests/test_parsing/
├── __init__.py
├── test_kiss_parser.py
├── test_query_kiss_parser.py
├── test_sage_extractor.py
└── test_graph_query.py
```

---

## 5. Component Specifications

### 5.1 GC Entity List (`src/parsing/gc_entities.py`)

**Purpose:** A static override lookup applied before spaCy's POS tagger runs. GC terms of art that spaCy would miscategorize are captured here as `ENTITY`, preserving their policy meaning.

**Implementation:** Longest-match phrase lookup. Multi-word phrases are matched as units before spaCy tokenizes them, so `"bilingual imperative"` resolves as a single ENTITY, not `["bilingual", "imperative"]`.

**Required coverage — Claude Code must populate all of these from the existing `src/data/policy_registry.json`:**

| Category | Examples | Why spaCy gets it wrong |
|----------|----------|------------------------|
| Tenure types | `indeterminate`, `term`, `casual`, `acting` | Tagged as adjective or common noun |
| Classification levels | `IT-02`, `AS-04`, `PM-06`, `EX-01`, `CS-03` | Tokenized as `IT` + `-` + `02` |
| Geographic zones | `NCR`, `NCA`, `bilingual region` | Unknown proper noun; no policy link |
| Language designations | `bilingual imperative`, `bilingual non-imperative`, `BBB`, `CBC`, `CCC` | Compounds broken apart |
| Staffing mechanisms | `deployment`, `secondment`, `priority entitlement`, `advertised process`, `non-advertised process` | Multi-word nominals |
| Leave types | `sick leave`, `annual leave`, `family-related leave`, `LWOP` | Multi-word or acronym |
| Organizational actors | `deputy head`, `delegated manager`, `Treasury Board`, `PSC`, `TBS`, `ADM`, `DM`, `PCO`, `Privy Council` | Multi-word compounds, acronyms |
| Instrument shortforms | `DAOD`, `NJC directive`, `TBS directive`, `collective agreement`, `PSEA`, `PSLRA`, `CHRA`, `CLC`, `GECA` | Acronyms, shortened references |
| HR processes | `staffing action`, `lay-off`, `workforce adjustment`, `WFA`, `WFAD`, `demotion`, `grievance`, `adjudication` | Domain-specific nominals |
| All 147 instrument titles | Full titles from policy_registry.json | Would be split into individual word tokens |

**This list is the foundation of everything else. TASK-A (see Section 7) has a mandatory human operator review gate before any other task proceeds.**

---

### 5.2 Deontic Verb List (`src/data/deontic_verbs.py`)

A static dict mapping GC policy modal verbs to their deontic classification:

```python
DEONTIC_VERBS = {
    "shall":   "obligation",    # binding requirement
    "must":    "obligation",
    "will":    "obligation",    # in GC drafting, "will" = obligation in policy instruments
    "may":     "discretion",    # permissive / discretionary
    "can":     "discretion",
    "should":  "recommendation", # non-binding guidance
    "is to":   "obligation",    # common GC drafting form
    "are to":  "obligation",
    "must not":"prohibition",
    "shall not":"prohibition",
    "may not": "prohibition",
}
```

---

### 5.3 Document KISS Parser (`src/parsing/kiss_parser.py`)

**Purpose:** Tag every token in a cleaned policy document with one of four KISS categories.

**KISS category mapping:**

| KISS Category | spaCy POS tags | Examples in GC policy text |
|---------------|---------------|---------------------------|
| `ENTITY` | NOUN, PROPN, NUM, PRON + all gc_entities overrides | "employee", "Treasury Board", "Section 54(1)", "IT-02" |
| `VERB` | VERB, AUX | "shall", "must", "may", "determines", "applies" |
| `CONNECTOR` | ADP, CONJ, CCONJ, SCONJ, PART, DET, ADV, ADJ | "pursuant to", "except where", "notwithstanding", "designated" |
| `PUNCTUATION` | PUNCT, SPACE | ".", ",", ";", "—" |

**Key design constraints:**
- GC entity overrides (from `gc_entities.py`) take precedence over spaCy POS assignment
- Deontic verbs (from `deontic_verbs.py`) resolved with `is_deontic=True` and `deontic_type` populated
- Processing is synchronous and CPU-bound — caller wraps in `asyncio.to_thread()`
- Parser never modifies source text — annotation only
- spaCy model version pinned and logged with every parsed document

**Output dataclasses (add to `src/models/schemas.py`):**

```python
@dataclass
class KISSToken:
    text: str
    lemma: str
    pos: str                # raw spaCy POS tag
    kiss_category: str      # ENTITY | VERB | CONNECTOR | PUNCTUATION
    is_deontic: bool
    deontic_type: str | None  # obligation | discretion | prohibition | recommendation | None
    char_start: int
    char_end: int
    sentence_idx: int
    token_idx: int

@dataclass
class KISSDocument:
    source_url: str
    instrument_title: str
    agent_id: str
    tokens: list[KISSToken]
    sentence_count: int
    token_count: int
    parsed_at: str          # ISO 8601 timestamp
    model_version: str      # e.g. "en_core_web_sm-3.7.1"
```

---

### 5.4 Query KISS Parser (`src/parsing/query_kiss_parser.py`)

**Purpose:** Extract the vocabulary (entities and verbs) from the user's natural language query to use as search keys against the knowledge graph. Critically different from the document parser: **never writes to the graph, never attempts SVO extraction.**

**Why a separate class:** Policy documents are formally drafted and yield reliable triples. User queries are conversational and yield unreliable triples that must never enter the graph. The separation is structural — `QueryKISSParser` has no write methods, making accidental graph contamination impossible.

**Processing pipeline:**

```
Raw query text (all sentences)
    │
    ▼
1. GC longest-match phrase lookup (gc_entities.py) — applied first
   → matched spans tagged ENTITY, masked before spaCy runs
    │
    ▼
2. spaCy POS tagger on remaining tokens
    │
    ▼
3. KISSMapper — four-category classification
    │
    ▼
4. Entity threshold check: len(entities) >= 2?
    ├─ YES → return QueryKISSResult (proceed to graph search)
    └─ NO  → return None (trigger fallback to existing EXTRACT flow)
```

**Why threshold = 2:** A single entity (e.g., `"grievance timelines?"`) cannot meaningfully narrow a graph search across 147 instruments. Two entities create an intersection that is useful. This threshold is configurable in `config.yaml`.

**Output dataclass:**

```python
@dataclass
class QueryKISSResult:
    raw_query: str
    entities: list[str]             # canonical entity strings, deduplicated
    entity_types: dict[str, str]    # entity_text → GC_ACTOR | CLASSIFICATION | TENURE_TYPE | etc.
    verbs: list[str]                # verb lemmas
    deontic_verbs: list[str]        # subset: deontic verbs found in query (usually none)
    sentence_count: int
    entity_count: int
    fallback_triggered: bool        # True if entity_count < threshold
    model_version: str
```

**Validated against the two canonical example queries:**

Query 1: `"I have an employee who has filed a grievance related to discrimination based on racial characteristics. What do I need to know?"`
→ entities: `["employee", "grievance", "discrimination", "racial characteristics"]`
→ entity_types: `{employee: GC_ACTOR, grievance: CONCEPT, discrimination: CONCEPT, racial characteristics: CONCEPT}`
→ `fallback_triggered: False`

Query 2: `"I want to hire an indeterminate IT-02, they will work in the NCR."`
→ entities: `["indeterminate", "IT-02", "NCR"]`
→ entity_types: `{indeterminate: TENURE_TYPE, IT-02: CLASSIFICATION, NCR: GEOGRAPHIC_ZONE}`
→ `fallback_triggered: False`

These two queries are acceptance criteria for TASK-F. If either fails, TASK-F is not complete.

**Fallback is silent:** When `fallback_triggered=True`, the specialist agent receives `None` as its `QueryKISSResult` and proceeds directly to its existing EXTRACT flow. No error, no user-visible message, no log warning — this is expected normal behaviour for short or informal queries.

---

### 5.5 Sage Extractor (`src/parsing/sage_extractor.py`)

**Purpose:** Take a `KISSDocument` and extract SVO triples, validate them against policy-domain rules, and write to the knowledge graph tables.

**SVO extraction logic:**
1. For each sentence, use spaCy's dependency parse to identify the root verb
2. Walk the dependency tree for: `nsubj`, `nsubjpass` (subjects), `dobj`, `attr`, `pobj` (objects)
3. Resolve multi-token entity spans using the GC entity list (e.g., "Treasury Board" as one subject, not two tokens)
4. Construct a `PolicyTriple` with subject, predicate (verb lemma + deontic info), object, and any qualifying modifier connectors (e.g., "except where", "subject to", "pursuant to")

**State machine validation rules:**

| Rule | Trigger | Flag Written | Rationale |
|------|---------|-------------|-----------|
| RULE-01 | `shall` triple where subject is not a recognized GC actor | `UNANCHORED_OBLIGATION` | Obligations must bind a specific actor |
| RULE-02 | Two triples with same subject+predicate, different objects | `POTENTIAL_CONFLICT` | May indicate amendment or cross-instrument tension |
| RULE-03 | Object contains a section reference (regex) that doesn't exist in the document's section index | `DANGLING_CROSS_REFERENCE` | Catches stale internal cross-references |
| RULE-04 | Subject is `employee` + predicate is deontic `may` | `DISCRETIONARY_RIGHT` | Obligation vs. discretion is critical in HR policy |
| RULE-05 | Triple appears in instruments from two different source domains | `CROSS_INSTRUMENT_CORROBORATION` | Strengthens citation confidence |

Rules produce flags, not rejections. Every triple is written to the graph with its flags. The LLM validation pass (teacher loop) reviews flagged triples.

**Output dataclass:**

```python
@dataclass
class PolicyTriple:
    triple_id: str              # UUID
    doc_id: str                 # references kiss_documents
    source_url: str
    instrument_title: str
    agent_id: str
    section_heading: str | None
    sentence_text: str          # original sentence — human audit anchor
    subject: str
    predicate: str
    predicate_lemma: str
    is_deontic: bool
    deontic_type: str | None
    object_: str
    modifier: str | None        # qualifying connector clause
    validation_flags: list[str]
    llm_validated: bool = False
    llm_validation_note: str | None = None
```

---

### 5.6 Graph Query Engine (`src/parsing/graph_query.py`)

**Purpose:** The interface through which specialist agents query the knowledge graph. All specialist agent graph interactions go through this class — no direct SQL in agent code.

**Key methods:**

```python
async def search_triples_semantic(
    query_entities: list[str],
    query_verbs: list[str],
    agent_id: str | None = None
) -> list[PolicyTriple]
# Primary entry point. Returns triples where subject or object matches
# any query entity, optionally filtered to a specific agent's corpus.
# Scores results by: entity match count, verb match, corroboration weight.

async def query_triples_by_url(source_url: str) -> list[PolicyTriple]
# All triples from a specific instrument URL.

async def find_conflicts(subject: str, predicate: str) -> list[tuple[PolicyTriple, PolicyTriple]]
# Returns pairs of triples that triggered RULE-02 for this subject+predicate.

async def get_entity_neighborhood(entity_text: str, depth: int = 2) -> list[PolicyTriple]
# All triples within N hops of an entity node — for context expansion.

async def is_document_parsed(source_url: str) -> bool
# Check before fetching — if True and within TTL, skip fetch entirely.

async def get_coverage_stats() -> dict
# Returns graph size metrics for startup logging and admin endpoint.
```

**`search_triples_semantic` scoring logic:**

For each candidate triple, compute a match score:
- +2 for each query entity that matches the triple's subject (exact or substring)
- +1 for each query entity that matches the triple's object
- +1 for each query verb lemma that matches the triple's predicate_lemma
- +1 for `CROSS_INSTRUMENT_CORROBORATION` flag (edge weight in graph_edges)

Return triples with score > 0, sorted descending by score, up to a configurable max (default: 20).

---

## 6. Database Schema Extension

Add to `src/db/manager.py` — append to the existing `init_db()` function. **Do not modify any existing `CREATE TABLE` statements.**

```sql
-- Parsed documents registry
CREATE TABLE IF NOT EXISTS kiss_documents (
    doc_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    instrument_title TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    sentence_count INTEGER,
    token_count INTEGER,
    model_version TEXT NOT NULL,
    parsed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fetch_cache_url TEXT REFERENCES fetch_cache(url)
);

-- SVO triple store
CREATE TABLE IF NOT EXISTS policy_triples (
    triple_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES kiss_documents(doc_id),
    source_url TEXT NOT NULL,
    instrument_title TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    section_heading TEXT,
    sentence_text TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    predicate_lemma TEXT NOT NULL,
    is_deontic BOOLEAN NOT NULL DEFAULT FALSE,
    deontic_type TEXT,
    object_ TEXT NOT NULL,
    modifier TEXT,
    validation_flags TEXT,          -- JSON array of RULE-XX flag strings
    llm_validated BOOLEAN DEFAULT FALSE,
    llm_validation_note TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Graph nodes (canonical entity registry)
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,
    entity_text TEXT NOT NULL,
    entity_type TEXT,               -- GC_ACTOR | LEGISLATION | DIRECTIVE | CONCEPT | SECTION_REF
    mention_count INTEGER DEFAULT 1,
    first_seen_url TEXT,
    UNIQUE(entity_text)
);

-- Graph edges (for traversal queries)
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id TEXT PRIMARY KEY,
    subject_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
    predicate TEXT NOT NULL,
    object_node_id TEXT NOT NULL REFERENCES graph_nodes(node_id),
    triple_id TEXT NOT NULL REFERENCES policy_triples(triple_id),
    weight REAL DEFAULT 1.0         -- incremented by RULE-05 corroboration
);

-- LLM teacher loop corrections
CREATE TABLE IF NOT EXISTS rule_refinements (
    refinement_id TEXT PRIMARY KEY,
    triple_id TEXT REFERENCES policy_triples(triple_id),
    validation_flag TEXT,
    llm_correction TEXT NOT NULL,
    correction_type TEXT,           -- nuance | error | missing_entity | context_dependent
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    applied_to_rule TEXT            -- RULE-XX if a rule was updated as result
);
```

**Indexes:**
```sql
CREATE INDEX IF NOT EXISTS idx_triples_url ON policy_triples(source_url);
CREATE INDEX IF NOT EXISTS idx_triples_subject ON policy_triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON policy_triples(predicate_lemma);
CREATE INDEX IF NOT EXISTS idx_triples_agent ON policy_triples(agent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_text ON graph_nodes(entity_text);
```

---

## 7. Integration Points — Minimal Surgical Changes to Existing Code

### 7.1 `src/fetch/engine.py`

After the existing successful fetch + content extraction block, add one line:

```python
# After existing: cleaned_text = extractor.extract(html, url)
asyncio.create_task(
    sage_pipeline.process_document(url, cleaned_text, instrument_title, agent_id)
)
# Fire-and-forget. Does not await. Does not block fetch return.
```

`sage_pipeline` is a module-level singleton initialized at startup in `src/main.py`. The `process_document` coroutine runs KISS parsing + Sage extraction + graph write as a background task. If it raises, the exception is logged but does not surface to the agent or user.

### 7.2 `src/agents/specialist.py`

Before the existing LLM call, insert the graph query check:

```python
# New: attempt graph retrieval
graph_result = None
if query_kiss_result and not query_kiss_result.fallback_triggered:
    graph_result = await graph_query.search_triples_semantic(
        query_entities=query_kiss_result.entities,
        query_verbs=query_kiss_result.verbs,
        agent_id=self.agent_id
    )

if graph_result and len(graph_result) >= config.parsing.validate_mode_threshold:
    # VALIDATE mode — new path
    response = await self._llm_validate(graph_result, sub_query)
    response.grounding_mode = "validate"
else:
    # EXTRACT mode — existing path, completely unchanged
    response = await self._llm_extract(fetched_content, sub_query)
    response.grounding_mode = "extract"
```

`query_kiss_result` is passed into the specialist's `process()` method as a new optional parameter (default `None`). When `None`, the agent behaves exactly as before — zero behaviour change for any code path that doesn't pass the parameter.

### 7.3 `src/api/websocket.py`

Add one new status event type alongside the existing `working`, `done`, `error` events:

```python
# New event type — sent when KISS/Sage pipeline is running on a fetched document
{"type": "agent_status", "agent_id": "system", "status": "parsing", "detail": "Extracting policy structure..."}
```

No existing event handling modified.

### 7.4 `config.yaml`

Append to existing file:

```yaml
parsing:
  enabled: true
  spacy_model: "en_core_web_sm"
  spacy_model_version: "3.7.1"
  query_entity_threshold: 2         # min entities in query to attempt graph search
  validate_mode_threshold: 5        # min triples from graph to use VALIDATE mode
  warmup_on_startup: false
  teacher_loop_enabled: true

  validation_rules:
    RULE-01: {enabled: true}
    RULE-02: {enabled: true}
    RULE-03:
      enabled: true
      section_ref_regex: '(s\.\s*\d+(\.\d+)*|[Ss]ection\s+\d+(\.\d+)*|[Aa]rticle\s+\d+)'
    RULE-04: {enabled: true}
    RULE-05: {enabled: true}
```

### 7.5 `src/models/schemas.py`

Append the new dataclasses from Sections 5.3, 5.4, 5.5, and the `DeterministicGrounding` block:

```python
@dataclass
class DeterministicGrounding:
    graph_coverage: str             # full | partial | none
    triples_used: int
    documents_parsed_from_graph: int
    graph_hits: list[str]           # URLs served from graph
    graph_misses_fetched: list[str] # URLs that required live fetch
    validation_flags_raised: list[str]
    llm_mode: str                   # validate | extract | mixed
```

Add `deterministic_grounding: DeterministicGrounding | None = None` to the existing `OrchestratorResponse` model.

---

## 8. Modified Request Flow

```
User Query
    │
    ▼
[NEW] QueryKISSParser
    → entity + verb extraction, GC phrase lookup first
    → returns QueryKISSResult or None (if < 2 entities)
    │
    ▼
Orchestrator routing call (UNCHANGED)
    + QueryKISSResult passed through to specialist sub-query context
    │
    ▼ (per specialist agent, in parallel — UNCHANGED)
    │
    ├─ QueryKISSResult is None or fallback_triggered=True
    │       → [EXISTING EXTRACT FLOW — unchanged]
    │
    └─ QueryKISSResult has entities
            │
            ▼
        [NEW] graph_query.search_triples_semantic()
            │
            ├─ >= validate_mode_threshold triples returned
            │       → [NEW] VALIDATE mode LLM call
            │           → teacher loop: write corrections to rule_refinements
            │
            └─ < threshold triples (graph miss or sparse)
                    │
                    ▼
                [EXISTING] Web Fetch Engine (unchanged)
                    │
                    ▼
                [EXISTING] Content extraction (unchanged)
                    │
                    ▼
                [NEW fire-and-forget] KISS Parser → Sage Extractor → graph write
                    │
                    ▼
                [EXISTING] EXTRACT mode LLM call (unchanged)
    │
    ▼
Orchestrator synthesis call (UNCHANGED)
    + DeterministicGrounding metadata appended to response
    │
    ▼
Response to user
```

---

## 9. VALIDATE Mode — LLM Prompt Addition

This is the only new LLM prompt in the system. It is added to `src/agents/prompts/specialist_prompts.py` as a new template alongside the existing extraction prompt — the existing prompt is not modified.

```
DETERMINISTIC GROUNDING INSTRUCTIONS
You are operating in VALIDATE mode. The policy rules below were extracted
deterministically from the source instrument using a rules-based parser.

Your task is NOT to extract rules from scratch. Your task is to:
1. Confirm each extracted rule accurately represents the source
2. Note any qualifying conditions or exceptions not captured in the triple
3. Correct any deontic misclassification (obligation / discretion / prohibition)
4. Identify cross-references to other instruments that the parser missed

Source: {instrument_title}
URL: {source_url}

EXTRACTED RULES:
{formatted_triples}

Respond using the same structured JSON output format as always.
Citations must reference the instrument above only.
Do not introduce instruments not present in the extracted rules.
```

---

## 10. Graph Warm-Up

On first deployment, the graph is empty and all queries will be graph misses (falling back to existing EXTRACT flow). To accelerate graph population, add an admin endpoint:

```
POST /api/admin/warmup
```

Triggers a background task that iterates all instruments in the existing `policy_registry.json`, fetches each (using the existing fetch engine with its existing rate limits), and runs KISS/Sage on each. Estimated time: ~7–10 minutes for all 147 instruments.

```
GET /api/admin/warmup/status
```

Returns progress: `{total: 147, completed: 43, failed: 2, running: true}`.

After warm-up, the majority of queries to common instruments (TBS directives, CLC, OLA) will be graph hits and specialist agents will operate predominantly in VALIDATE mode.

---

## 11. GUI Changes (`static/`)

Additive only. Three additions:

1. **Grounding badge per citation** in the Citation Panel: `[Graph]` (served from knowledge graph) vs `[Live]` (freshly fetched). Teal for Graph, grey for Live.

2. **Validation Flags section** — collapsible, appears below citations only when flags were raised. Plain-English descriptions (e.g., "Potential conflict detected: two instruments state different rules for the same subject and action. Review citations [2] and [4].").

3. **`parsing` agent state** in the Agent Status Panel — blue pulsing dot, label "Parsing structure". Appears transiently when KISS/Sage is running on a newly fetched document in the background.

---

## 12. New Dependencies

Add to `requirements.txt`:

```
spacy>=3.7.0
networkx>=3.3
en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1.tar.gz
```

spaCy model must be the exact version specified. Pin it. The version string is logged with every parsed document for auditability.

---

## 13. Task Sequence

All tasks in this branch. No dependency on unimplemented base system work — the base system is complete.

```
TASK-A: GC Entity List + Deontic Verb List
    New files: src/parsing/gc_entities.py, src/data/deontic_verbs.py
    Input: existing src/data/policy_registry.json (read all instrument titles,
           acronyms, organizational names)
    Spec: Longest-match phrase lookup. Must cover all categories in Section 5.1.
          Classification level patterns via regex (IT-\d\d, AS-\d\d, etc.)
    ⚠️  GATE: Human operator reviews gc_entities.py before TASK-B proceeds.
          Canonical test: "indeterminate IT-02 in the NCR" → 3 entities.
    Assignee: OpenCode (mechanical extraction) + human review

TASK-B: Document KISS Parser
    New file: src/parsing/kiss_parser.py
    Input: src/parsing/gc_entities.py, src/data/deontic_verbs.py
    Spec: Section 5.3. Determinism test: 10 runs of same input → identical output.
    Assignee: Claude Code

TASK-C: Sage Extractor
    New file: src/parsing/sage_extractor.py
    Input: src/parsing/kiss_parser.py
    Spec: Section 5.5. All 5 validation rules. Writes to SQLite.
    Assignee: Claude Code

TASK-D: Database Schema Extension
    Modified file: src/db/manager.py
    Spec: Section 6. Append new tables + indexes to init_db(). No existing
          table modifications. Run existing DB tests to confirm no regression.
    Assignee: OpenCode

TASK-E: Graph Query Engine
    New file: src/parsing/graph_query.py
    Input: src/parsing/sage_extractor.py, src/db/manager.py
    Spec: Section 5.6. search_triples_semantic scoring logic as specified.
    Assignee: Claude Code

TASK-F: Query KISS Parser
    New file: src/parsing/query_kiss_parser.py
    Input: src/parsing/gc_entities.py, src/parsing/kiss_parser.py
    Spec: Section 5.4. No write methods. Fallback at < 2 entities.
    Acceptance: Both canonical example queries must pass (Section 5.4).
    Assignee: Claude Code
    Note: Can run in parallel with TASK-C/D/E after TASK-A and TASK-B complete.

TASK-G: Pydantic Model Extensions
    Modified file: src/models/schemas.py
    Spec: Append KISSToken, KISSDocument, QueryKISSResult, PolicyTriple,
          DeterministicGrounding. Add optional deterministic_grounding field
          to existing OrchestratorResponse. No existing models modified.
    Assignee: OpenCode

TASK-H: Fetch Engine Integration
    Modified file: src/fetch/engine.py
    Spec: Section 7.1. One asyncio.create_task() call added after successful
          fetch+clean. Existing code paths completely unchanged.
    Assignee: Claude Code (surgical change — read existing code carefully first)

TASK-I: Specialist Agent VALIDATE Mode
    Modified file: src/agents/specialist.py
    Spec: Section 7.2. Add optional query_kiss_result parameter (default None).
          When None: zero behaviour change. When present and not fallback:
          attempt graph search, enter VALIDATE mode if threshold met.
          VALIDATE mode prompt: Section 9.
          Teacher loop: write corrections to rule_refinements after VALIDATE call.
    Assignee: Claude Code (read existing specialist.py in full before touching)

TASK-J: WebSocket + Config + GUI
    Modified files: src/api/websocket.py, config.yaml, static/
    Spec: Sections 7.3, 7.4, 11. Additive only.
    Assignee: OpenCode

TASK-K: Warm-Up Endpoint
    Modified file: src/api/routes.py (or new src/api/admin.py)
    Spec: Section 10. POST /api/admin/warmup + GET /api/admin/warmup/status.
    Assignee: OpenCode

TASK-L: Tests
    New directory: tests/test_parsing/
    Spec: Section 14. All tests must pass. Existing tests must still pass.
    Assignee: Claude Code

TASK-M: Integration Validation
    No new code. Human operator runs end-to-end validation (Section 15).
```

**Dependency graph:**
```
TASK-A (GC entities) ──► TASK-B (KISS parser) ──► TASK-C (Sage)  ──► TASK-H (fetch integration)
         │                        │                      │                        │
         │                        └──────────────────────┼──► TASK-F (Query KISS) │
         │                                               │                        │
         │                                          TASK-D (DB) ──► TASK-E (graph query)
         │                                                                        │
         └── TASK-G (schemas) ──────────────────────────────────────────────────►│
                                                                                  │
                                                                             TASK-I (specialist)
                                                                                  │
                                                                    TASK-J + TASK-K (wiring)
                                                                                  │
                                                                             TASK-L (tests)
                                                                                  │
                                                                             TASK-M (validation)
```

---

## 14. Tests

All tests in `tests/test_parsing/`. All existing tests in `tests/` must continue to pass.

**test_kiss_parser.py**
- `test_determinism()` — same policy text 10x → identical token output
- `test_gc_entity_override()` — "Treasury Board", "Deputy Head", "DAOD 5031-0" → ENTITY
- `test_deontic_detection()` — "shall", "must", "may", "shall not" → correct deontic_type
- `test_multiword_entity_span()` — "bilingual imperative" → single ENTITY token, not two
- `test_tbs_directive_sample()` — real TBS directive snippet → token counts and categories plausible

**test_query_kiss_parser.py**
- `test_grievance_discrimination_query()` — canonical query 1 → 4 entities, `fallback_triggered=False`
- `test_indeterminate_it02_ncr_query()` — canonical query 2 → `["indeterminate", "IT-02", "NCR"]`, `fallback_triggered=False`
- `test_short_query_fallback()` — `"can I do this?"` → `fallback_triggered=True`
- `test_single_entity_fallback()` — `"grievance timelines?"` → `fallback_triggered=True`
- `test_multi_sentence_query()` — entities from all sentences returned, not just first
- `test_longest_match_phrase()` — `"bilingual imperative position"` → `["bilingual imperative", "position"]`
- `test_classification_level_regex()` — `"IT-02"`, `"AS-04"`, `"EX-01"` each → single ENTITY
- `test_determinism()` — same query 10x → identical output
- `test_no_write_methods()` — assert class has no write/insert/save/commit methods

**test_sage_extractor.py**
- `test_svo_extraction()` — sample sentence → correct subject/predicate/object
- `test_rule_01_unanchored_obligation()` — floating "shall" → `UNANCHORED_OBLIGATION` flag
- `test_rule_02_conflict_detection()` — two triples same subject+predicate, different objects → `POTENTIAL_CONFLICT`
- `test_rule_04_discretionary_right()` — "employee may request" → `DISCRETIONARY_RIGHT`
- `test_rule_05_corroboration()` — same triple from two source domains → `CROSS_INSTRUMENT_CORROBORATION`
- `test_triple_persistence()` — write to SQLite, read back, assert equality
- `test_no_graph_write_from_query()` — confirm Sage is never instantiated by QueryKISSParser

**test_graph_query.py**
- `test_search_triples_semantic()` — seeded graph, multi-entity query → correct triples returned
- `test_scoring_order()` — higher-match triples ranked above lower-match
- `test_find_conflicts()` — seeded RULE-02 conflict → both triples returned as pair
- `test_is_document_parsed()` — returns True after insert, False before
- `test_coverage_stats()` — returns valid dict with expected keys

---

## 15. Integration Validation (TASK-M — Human Operator)

After all tasks complete and branch tests pass:

1. Start server: `uvicorn src.main:app --host 0.0.0.0 --port 8000`
2. Confirm existing test query still works: `"What are the requirements for staffing a bilingual position at DND?"` — response should be identical to pre-branch baseline
3. Run warm-up: `POST /api/admin/warmup`, wait for completion
4. Submit canonical query 1: `"I have an employee who has filed a grievance related to discrimination based on racial characteristics. What do I need to know?"` — verify `deterministic_grounding.graph_coverage` is `partial` or `full`; verify at least one citation shows `[Graph]` badge
5. Submit canonical query 2: `"I want to hire an indeterminate IT-02, they will work in the NCR."` — verify `IT-02`, `NCR`, `indeterminate` appear in extracted entities in response metadata; verify staffing + languages agents consulted
6. Submit a short query: `"can I do this?"` — verify system responds normally (EXTRACT fallback), no errors, no grounding metadata anomalies
7. Check `rule_refinements` table has at least one entry (LLM teacher loop firing)

**Success criteria:**
- Queries 4 and 5 show `llm_mode: validate` or `mixed` in `deterministic_grounding`
- Query 6 shows `llm_mode: extract` and `graph_coverage: none`
- No regression on query 2 (existing test case)
- All existing tests still pass on this branch

---

## 16. Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| GC phrase lookup incomplete — "indeterminate", classification levels, NCR missed | High on first build | TASK-A has mandatory human review gate; canonical test cases in TASK-F acceptance criteria catch gaps |
| SVO extraction poor quality on complex policy sentences with multiple subordinate clauses | Medium | `validate_mode_threshold = 5` — LLM falls back to EXTRACT if graph is sparse; teacher loop improves over time |
| Query KISS Parser inadvertently writes to graph | Very low | Structural: `QueryKISSParser` has no write methods; enforced by `test_no_write_methods()` |
| Branch introduces regression in existing behaviour | Low | All existing tests required to pass; VALIDATE mode only activates when explicitly triggered by a non-None `query_kiss_result`; default parameter is `None` |
| spaCy model version drift breaks determinism | Low | Version pinned in requirements.txt and config; logged in `kiss_documents` for every parsed document |
| Warm-up overwhelms GC source servers | Low | Uses existing fetch engine with its existing rate limits |

---

## Document End

**Branch starting point:** Current `main` (fully implemented base system)  
**Branch name:** `feature/deterministic-parsing`  
**First action for Claude Code:** Read `CLAUDE.md`, then read the five files listed in Section 1 before touching anything.
