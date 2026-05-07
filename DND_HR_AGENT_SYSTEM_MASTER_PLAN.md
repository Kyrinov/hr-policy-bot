# DND HR-Civ Multi-Agent Policy Advisory System — Master Plan

**Document Purpose:** This is the authoritative instruction set for the Claude Code (Sonnet 4.6) instance responsible for architecting and implementing this system. Read this document in full before beginning any implementation work. All architectural decisions, file structures, and task sequencing are defined here.

**Document Owner:** Human operator (AI Solutions Developer, ADM(HR-Civ), DND)
**Prepared by:** Claude Opus 4.6 (planning tier)
**Date:** April 2026
**Classification:** Unclassified — Pilot / Proof of Concept

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Agent Design — Specialist Agents](#4-agent-design--specialist-agents)
5. [Agent Design — Orchestrator Agent](#5-agent-design--orchestrator-agent)
6. [Policy Corpus and Web Fetch Strategy](#6-policy-corpus-and-web-fetch-strategy)
7. [GUI Specification](#7-gui-specification)
8. [Feedback System](#8-feedback-system)
9. [Project File Structure](#9-project-file-structure)
10. [Claude Code Responsibilities](#10-claude-code-responsibilities)
11. [OpenCode Task Specifications](#11-opencode-task-specifications)
12. [Task Sequencing and Dependencies](#12-task-sequencing-and-dependencies)
13. [Validation and Testing Protocol](#13-validation-and-testing-protocol)
14. [Future Migration Considerations](#14-future-migration-considerations)

---

## 1. Project Overview

### 1.1 Purpose

Build a multi-agent orchestration system that helps DND civilian HR advisors obtain accurate, well-referenced policy guidance on real-world HR questions. The system must synthesize responses from a complex, overlapping landscape of publicly available federal HR policy instruments — legislation, Treasury Board directives, Public Service Commission instruments, National Joint Council directives, Defence Administrative Orders and Directives (DAODs), and collective agreements.

### 1.2 Operating Context

This is a **pilot proof of concept** built on local hardware. It is not a production deployment. Its purpose is to demonstrate capability, surface architectural requirements, and enter a period of iterative tuning with HR policy specialists before any consideration of enterprise migration.

The organizational environment is the **federal public service**, specifically the Department of National Defence's civilian HR function (ADM(HR-Civ)). Language, framing, and system behaviour must reflect institutional norms: precision in policy references, epistemic humility where appropriate, and clear delineation between what the system states as policy and what it recommends as interpretation.

### 1.3 Core Design Principles

1. **Accuracy over speed.** A slower, well-referenced response is always preferable to a fast, ungrounded one.
2. **Transparency of sourcing.** Every policy claim must cite its instrument by title and provide the URL. Users must be able to verify any statement the system makes.
3. **Epistemic humility.** When policy is ambiguous, when instruments conflict, or when a question falls outside the corpus, the system must say so explicitly — not confabulate.
4. **Feedback-driven iteration.** The system's initial deployment is to HR policy specialists who will evaluate and correct its outputs. The architecture must capture, store, and surface this feedback.
5. **Separation of concerns.** Specialist agents handle domain retrieval and analysis. The orchestrator handles synthesis and user-facing communication. The GUI handles presentation and interaction. These are distinct layers.

### 1.4 Users

**Primary:** HR policy advisors within ADM(HR-Civ) — experienced professionals who know the policy landscape and can evaluate accuracy.

**Secondary (future):** HR generalists and managers seeking policy guidance on specific situations.

### 1.5 Hardware

- **Platform:** NVIDIA Jetson Orin AGX
- **VRAM:** 64GB
- **OS:** Linux (Ubuntu-based)
- **Inference:** Ollama
- **Models (local):** Gemma4:31b
- **Language:** Python

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    WEB GUI (Browser)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐ │
│  │  Chat Panel   │  │  Agent Panel  │  │ Feedback Panel│ │
│  └──────┬───────┘  └──────────────┘  └───────────────┘ │
└─────────┼───────────────────────────────────────────────┘
          │ HTTP / WebSocket
          ▼
┌─────────────────────────────────────────────────────────┐
│                 FASTAPI APPLICATION SERVER                │
│  ┌──────────────────────────────────────────────────┐   │
│  │              ORCHESTRATOR AGENT                    │   │
│  │  - Query analysis and classification               │   │
│  │  - Agent routing (which specialists to invoke)     │   │
│  │  - Response synthesis and citation assembly        │   │
│  │  - Conflict identification across policy sources   │   │
│  └──────────┬───────────────────────────┬────────────┘  │
│             │                           │                │
│  ┌──────────▼──────────┐  ┌────────────▼─────────────┐ │
│  │  SPECIALIST AGENT 1  │  │  SPECIALIST AGENT N      │ │
│  │  (e.g., Staffing)    │  │  (e.g., Official Lang.)  │ │
│  │  - Domain prompt      │  │  - Domain prompt          │ │
│  │  - Policy registry    │  │  - Policy registry        │ │
│  │  - Web fetch tools    │  │  - Web fetch tools        │ │
│  └──────────┬───────────┘  └────────────┬────────────┘ │
│             │                           │                │
│  ┌──────────▼───────────────────────────▼────────────┐  │
│  │              WEB FETCH ENGINE                       │  │
│  │  - URL retrieval from policy registry               │  │
│  │  - HTML parsing (BeautifulSoup / lxml)             │  │
│  │  - Content extraction and cleaning                  │  │
│  │  - Caching layer (SQLite)                           │  │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │              OLLAMA INFERENCE CLIENT                 │ │
│  │  - Model management                                 │ │
│  │  - Prompt construction                              │ │
│  │  - Structured output parsing                        │ │
│  └────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │              FEEDBACK & LOGGING STORE                │ │
│  │  - SQLite database                                  │ │
│  │  - Query log, agent responses, user feedback        │ │
│  │  - Export capability for analysis                    │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Request Flow

1. User submits an HR policy question via the GUI chat interface.
2. FastAPI receives the request and passes it to the **Orchestrator Agent**.
3. The Orchestrator analyzes the query to determine which policy domains are implicated (e.g., a question about bilingual staffing requirements touches Staffing, Official Languages, and potentially Classification).
4. The Orchestrator dispatches the query to the relevant **Specialist Agents** (potentially multiple, in parallel).
5. Each Specialist Agent:
   a. Consults its **policy registry** (the subset of the master policy inventory relevant to its domain).
   b. Determines which specific instruments are likely relevant to the query.
   c. Uses the **Web Fetch Engine** to retrieve current content from the authoritative URLs.
   d. Analyzes the retrieved content against the query.
   e. Returns a structured response containing: findings, specific policy references with citations, and any caveats or limitations.
6. The Orchestrator receives all specialist responses and:
   a. Synthesizes a coherent, multi-layered response.
   b. Identifies any conflicts or tensions between policy instruments.
   c. Assembles a complete citation list.
   d. Flags areas where the response may be incomplete or where professional judgment is required.
7. The GUI renders the final response with citations, agent attribution, and feedback controls.

### 2.3 Key Architectural Decisions

**Why agentic web-fetch, not RAG:**
- The policy corpus spans 147 instruments across 6 authoritative domains (laws-lois.justice.gc.ca, tbs-sct.canada.ca, canada.ca, njc-cnm.gc.ca, FPSLREB decisions, and collective agreements).
- Policies are amended periodically. A RAG corpus of hundreds of unstructured PDFs would require ongoing maintenance with no reliable change-detection mechanism.
- Authoritative GC sources are publicly accessible, well-structured, and stable in their URL patterns.
- Web-fetch ensures the system always references the current version of each instrument.
- A caching layer prevents redundant fetches and provides offline resilience.

**Why local inference:**
- This is a proof of concept. Cloud API costs are not justified at this stage.
- The Jetson Orin AGX with 64GB VRAM can run Gemma4:31b with acceptable latency for a pilot.
- Data remains entirely local — no classification concerns arise from transmitting query content to external APIs.

**Why SQLite (not PostgreSQL, not a vector DB):**
- This is a single-user or small-team pilot on a single machine.
- SQLite is zero-configuration, ships with Python, and is more than sufficient for the logging, feedback, and caching requirements.
- A vector database is unnecessary because retrieval is not embedding-based — it is URL-based from a known registry.

---

## 3. Technology Stack

### 3.1 Core Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language | Python 3.11+ | Operator preference; ecosystem maturity |
| Web framework | FastAPI | Async support, WebSocket native, lightweight |
| LLM inference | Ollama (local) | Operator's existing infrastructure |
| Models | Gemma4:31b | Fits in 64GB VRAM for pilot use |
| Web fetching | httpx (async) + BeautifulSoup4 | Async HTTP client + robust HTML parsing |
| Cache/storage | SQLite via aiosqlite | Zero-config, sufficient for pilot scale |
| Frontend | HTML/CSS/JS (single-page application) | No build toolchain required; served by FastAPI |
| Real-time comms | WebSocket (FastAPI native) | Streaming responses, live agent status |
| Process management | systemd or manual | Pilot-scale; no container orchestration needed |

### 3.2 Python Dependencies

```
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
httpx>=0.27.0
beautifulsoup4>=4.12.0
lxml>=5.2.0
aiosqlite>=0.20.0
pydantic>=2.7.0
ollama>=0.3.0
python-multipart>=0.0.9
jinja2>=3.1.0
```

### 3.3 Model Configuration

The system must support hot-swapping between models via configuration (not code changes). The Ollama client should accept a model name from a config file or environment variable.

```yaml
# config.yaml
model:
  name: "gemma4:31b"
  temperature: 0.2  # Low temperature for policy accuracy
  num_ctx: 32768  # Context window
  top_p: 0.9

server:
  host: "0.0.0.0"
  port: 8000

cache:
  ttl_hours: 168  # 7 days default cache TTL
  max_size_mb: 500

logging:
  level: "INFO"
  file: "logs/system.log"
```

---

## 4. Agent Design — Specialist Agents

### 4.1 Agent Clustering Strategy

The 147 policy instruments in the corpus are organized into 16 business functions. Some functions are closely related and share significant instrument overlap. The agent clustering consolidates these into **8 specialist agents**, each responsible for a coherent policy domain. This reduces model invocations while maintaining domain expertise.

| Agent ID | Agent Name | Business Functions Covered | Instrument Count |
|----------|-----------|---------------------------|------------------|
| `staffing` | Staffing & Recruitment Agent | Staffing and recruitment; Student and youth programs | 28 |
| `classification` | Classification & Compensation Agent | Classification; Compensation and benefits | 32 |
| `labour` | Labour Relations Agent | Labour relations and workplace management | 11 |
| `learning` | Learning & Performance Agent | Learning, training and development; Performance management | 10 |
| `equity` | Equity, Diversity & Inclusion Agent | Diversity, equity and inclusion; Employment equity and accessibility | 17 |
| `ohs` | Health, Safety & Wellness Agent | Occupational health and safety | 10 |
| `languages` | Official Languages Agent | Official languages | 10 |
| `governance` | Values, Ethics & HR Governance Agent | Values and ethics; Conflict of interest and post-employment; HR planning and reporting; Executive services; Leave and attendance | 28 |

**Note on deduplication:** 16 instruments appear in multiple business functions (e.g., the Canadian Human Rights Act appears under both Diversity, equity and inclusion and Employment equity and accessibility). The policy registry must store the canonical instrument once and map it to multiple agents via a many-to-many relationship. When an instrument is fetched, it is fetched once and the cached result is shared across agents.

### 4.2 Specialist Agent Structure

Each specialist agent is defined by:

1. **Agent ID** — Unique string identifier (e.g., `staffing`).
2. **Display name** — Human-readable name for the GUI.
3. **System prompt** — Domain-specific instructions that define the agent's expertise, scope, and behaviour. This is the primary quality lever.
4. **Policy registry** — The subset of the master policy inventory assigned to this agent, including instrument titles, types, URLs, and brief descriptions of what each instrument covers.
5. **Fetch strategy** — Rules for when and how to fetch policy content (see Section 6).

### 4.3 System Prompt Template for Specialist Agents

Each specialist agent receives a system prompt following this template. The `{variables}` are populated from configuration.

```
You are the {agent_display_name}, a specialist policy advisor within the DND HR-Civ
Multi-Agent Policy Advisory System. Your role is to provide accurate, well-referenced
guidance on HR policy questions within your domain of expertise.

DOMAIN: {domain_description}

YOUR POLICY INSTRUMENTS:
{formatted_policy_registry}

INSTRUCTIONS:
1. When presented with a query, identify which of your assigned policy instruments
   are relevant.
2. Analyze the retrieved policy content carefully. Base your response ONLY on the
   content actually retrieved from authoritative sources. Do not supplement with
   general knowledge about HR policy unless explicitly flagging it as general
   context rather than authoritative guidance.
3. For every factual policy claim, cite the specific instrument by its full title.
4. If the retrieved content does not adequately address the query, state this
   explicitly. Say "The instruments within my domain do not appear to directly
   address this aspect of the question" rather than generating an answer from
   general knowledge.
5. If you identify ambiguity or potential conflict between instruments, flag this
   explicitly with the specific provisions that appear to be in tension.
6. Structure your response as follows:
   - FINDINGS: Your analysis of the relevant policy provisions
   - CITATIONS: A list of the specific instruments and sections referenced
   - CAVEATS: Any limitations, ambiguities, or areas requiring professional judgment
   - SCOPE_FLAG: If the query touches on domains outside your expertise, name
     which other specialist agent(s) should be consulted

OUTPUT FORMAT: Respond in valid JSON with the following structure:
{
  "agent_id": "{agent_id}",
  "findings": "string — your analysis in natural language",
  "citations": [
    {
      "instrument_title": "string",
      "instrument_type": "string",
      "url": "string",
      "relevant_section": "string or null — specific section if identifiable"
    }
  ],
  "caveats": "string or null",
  "scope_flags": ["string — other agent IDs that should be consulted"],
  "confidence": "high | medium | low",
  "retrieval_status": {
    "instruments_attempted": 0,
    "instruments_successfully_retrieved": 0,
    "instruments_failed": ["list of titles that failed to fetch"]
  }
}
```

### 4.4 Complete Policy Registry

The following is the complete policy inventory organized by agent assignment. This data must be stored in a structured format (JSON or SQLite) and loaded at system initialization. Each instrument includes the fields: `title`, `type`, `url`, and `agent_ids` (list, since instruments can be assigned to multiple agents).

**CRITICAL: The policy registry JSON file must be generated from this inventory. The Claude Code instance must create this file as one of its first tasks.**

#### Agent: `staffing` — Staffing & Recruitment Agent

Business functions: Staffing and recruitment; Student and youth programs

Instruments (28 total, deduplicated):

- Public Service Employment Act (PSEA) | Legislation | https://laws-lois.justice.gc.ca/eng/acts/p-33.01/
- Public Service Employment Regulations (PSER) | Legislation | https://laws-lois.justice.gc.ca/eng/regulations/SOR-2005-334/FullText.html
- Financial Administration Act (FAA) | Legislation | https://laws-lois.justice.gc.ca/eng/acts/f-11/
- Federal Public Sector Labour Relations and Employment Board Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/P-33.35/
- Policy on People Management | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32621
- Directive on Term Employment | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32629
- Directive on Interchange Canada | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=12553
- PSC Appointment Policy | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/appointment-framework/appointment-policy.html
- Appointment Delegation and Accountability Instrument (ADAI) | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/appointment-framework/delegation-overview/appointment-delegation-accountability-instrument.html
- PSC Appointment Framework | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/appointment-framework.html
- Guide on Priority Entitlements | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/information-priority-administration/public-service-commission-guide-priority-administration.html
- Priority Administration Directive | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/information-priority-administration/priority-administration-directive.html
- PSC Guides on Assessment | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/appointment-framework/guides-tools-appointment-framework.html
- Spotlight on Area of Selection | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/appointment-framework/guides-tools-appointment-framework/spotlight-on-area-of-selection.html
- PSC Staffing Interpretation Centre | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/appointment-framework/guides-tools-appointment-framework/psc-staffing-interpretation-centre.html
- Federal Public Service Inclusive Appointment Lens | PSC Instrument | https://www.canada.ca/en/public-service-commission/services/appointment-framework/guides-tools-appointment-framework.html
- Qualification Standards | PSC Instrument | https://www.canada.ca/en/treasury-board-secretariat/services/staffing/qualification-standards/overview.html
- DAOD 5029-0, Civilian Staffing | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5029/5029-0-civilian-staffing.html
- DAOD 5029-2, Corrective Action and Revocation | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5029/5029-2-corrective-action-and-revocation.html
- DAOD 5005-2, Delegation of Authorities for Civilian HR Management | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5005/5005-2-delegation-of-authorities-for-civilian-human-resources-management.html
- NJC Isolated Posts and Government Housing Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d4/en
- NJC Relocation Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d6/en
- Federal Student Work Experience Program (FSWEP) | PSC Program | https://www.canada.ca/en/public-service-commission/jobs/services/recruitment/students/federal-student-work-program.html
- Post-Secondary Co-op/Internship Program | PSC Program | https://www.canada.ca/en/public-service-commission/jobs/services/recruitment/students/coop-internship.html
- Research Affiliate Program (RAP) | PSC Program | https://www.canada.ca/en/public-service-commission/jobs/services/recruitment/students/research-affiliate-program.html
- Student Bridging Guide | PSC Program | https://www.canada.ca/en/public-service-commission/services/appointment-framework/student-bridging.html
- Directive on Terms and Conditions of Employment for Students | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=12583
- Directive on Student Employment | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32630

#### Agent: `classification` — Classification & Compensation Agent

Business functions: Classification; Compensation and benefits

Instruments (30 total, deduplicated):

- Financial Administration Act (FAA), ss. 7 and 11.1 | Legislation | https://laws-lois.justice.gc.ca/eng/acts/f-11/
- Pay Equity Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/P-4.2/
- Public Service Superannuation Act (PSSA) | Legislation | https://laws-lois.justice.gc.ca/eng/acts/p-36/
- Government Employees Compensation Act (GECA) | Legislation | https://laws-lois.justice.gc.ca/eng/acts/g-5/
- Policy on People Management | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32621
- Directive on Organization and Classification | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32632
- Directive on Executive (EX) Group Organization and Classification | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32641
- Directive on Terms and Conditions of Employment | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=15772
- Directive on Terms and Conditions of Employment for Executives | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32625
- Directive on Terms and Conditions of Employment for Certain Excluded/Unrepresented Groups | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=15773
- Directive on Terms and Conditions of Employment for Students | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=12583
- Policy Framework for the Management of Compensation | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=12084
- Bilingualism Bonus Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d1/en
- Isolated Posts and Government Housing Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d4/en
- NJC Relocation Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d6/en
- Travel Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d10/en
- Public Service Health Care Plan (PSHCP) Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d9/en
- Commuting Assistance Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d2/en
- Foreign Service Directives | NJC Directive | https://www.njc-cnm.gc.ca/directive/fsd-dse/en
- Uniforms Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d11/en
- First Aid to the General Public | NJC Directive | https://www.njc-cnm.gc.ca/directive/d13/en
- Occupational Groups by Bargaining Agent Representation | Reference | https://www.canada.ca/en/treasury-board-secretariat/services/collective-agreements/occupational-groups/occupational-groups-bargaining-agent-representation.html
- DAOD 5025-0, Classification of Civilian Positions | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5025/5025-0-classification-of-civilian-positions.html
- The TBS Collective Agreements Index | Reference | https://www.tbs-sct.canada.ca/agreements-conventions/index-eng.aspx
- PA Group (AS, PM, CR, IS, etc.) | Collective Agreement | https://www.tbs-sct.canada.ca/agreements-conventions/view-visualiser-eng.aspx?id=15
- SV Group (GL, GS, FR, etc.) | Collective Agreement | https://www.tbs-sct.canada.ca/agreements-conventions/view-visualiser-eng.aspx?id=19
- TC Group (EG, GT, TI, etc.) | Collective Agreement | https://www.tbs-sct.canada.ca/agreements-conventions/view-visualiser-eng.aspx?id=25
- IT Group | Collective Agreement | https://www.tbs-sct.canada.ca/agreements-conventions/view-visualiser-eng.aspx?id=1
- EC Group | Collective Agreement | https://www.tbs-sct.canada.ca/agreements-conventions/view-visualiser-eng.aspx?id=4
- Public Service Dental Care Plan (PSDCP) | Collective Agreement / Plan | https://www.njc-cnm.gc.ca/s14/s84/en

#### Agent: `labour` — Labour Relations Agent

Business functions: Labour relations and workplace management

Instruments (11 total):

- Federal Public Sector Labour Relations Act (FPSLRA) | Legislation | https://laws-lois.justice.gc.ca/eng/acts/p-33.3/
- Canada Labour Code, Part II | Legislation | https://laws-lois.justice.gc.ca/eng/acts/l-2/
- Directive on Union Dues | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=21104
- Work Force Adjustment Directive (WFAD) | NJC Directive | https://www.njc-cnm.gc.ca/directive/d12/en
- DAOD 5008-0, Civilian Labour-Management Relations | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5008/5008-0-civilian-labour-management-relations.html
- DAOD 5008-1, Use of Departmental Premises for Bargaining Agent Business | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5008/5008-1-use-of-departmental-premises-and-equipment-and-electronic-networks-for-bargaining-agent-or-union-business.html
- DAOD 5008-2, Civilian Labour-Management Consultation | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5008/5008-2-civilian-labour-management-consultation.html
- DAOD 5026-0, Civilian Grievances | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5026/5026-0-civilian-grievances.html
- DAOD 5046-0, Alternative Dispute Resolution | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5046/5046-0-alternative-dispute-resolution.html
- FPSLREB Decisions Database | Reference | https://decisions.fpslreb-crtespf.gc.ca/fpslreb-crtespf/d/en/home.do
- NJC Grievance Process and Procedures | Reference | https://www.njc-cnm.gc.ca/s2/en

#### Agent: `learning` — Learning & Performance Agent

Business functions: Learning, training and development; Performance management

Instruments (10 total):

- Canada School of Public Service Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/c-10.13/
- Directive on Mandatory Training | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32628
- Treasury Board Mandatory Training Inventory | Reference | https://www.canada.ca/en/government/publicservice/workforce/learning/treasury-board-mandatory-training-inventory.html
- DAOD 5031-0, Learning and Professional Development | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5031/5031-0-learning-and-professional-development.html
- DAOD 5031-50, Civilian Learning and Professional Development | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5031/5031-50-civilian-learning-and-professional-development.html
- Directive on Performance Management | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=27146
- Directive on Performance and Talent Management for Executives | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32637
- Directive on Performance Pay Administration for Certain Senior Excluded/Unrepresented Groups | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32623
- DAOD 5006-0, Civilian Performance Planning and Review | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5006/5006-0-civilian-performance-planning-and-review.html
- DAOD 5006-1, Performance Management Program for DND Employees | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5006/5006-1-performance-management-program-for-dnd-employees.html

#### Agent: `equity` — Equity, Diversity & Inclusion Agent

Business functions: Diversity, equity and inclusion; Employment equity and accessibility

Instruments (11 total, deduplicated):

- Canadian Human Rights Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/h-6/
- Employment Equity Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/E-5.401/
- Accessible Canada Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/a-0.6/
- Directive on Employment Equity, Diversity and Inclusion | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32635
- Directive on the Duty to Accommodate | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32634
- "Nothing Without Us": Accessibility Strategy for the Public Service of Canada | Strategy | https://www.canada.ca/en/government/publicservice/wellness-inclusion-diversity-public-service/diversity-inclusion-public-service/accessibility-public-service/accessibility-strategy-public-service-toc.html
- DAOD 5015-0, Workplace Accommodation | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5015/5015-0-workplace-accommodation.html
- DAOD 5516-0, Human Rights | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5516/5516-0-human-rights.html
- DAOD 5516-1, Human Rights Complaints | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5516/5516-1-human-rights-complaints.html
- PSC Employment Equity Staffing Guides | PSC Reference | https://www.canada.ca/en/public-service-commission/services/appointment-framework/guides-tools-appointment-framework.html
- PSC Self-Declaration and Affirmation Guides | PSC Reference | https://www.canada.ca/en/public-service-commission/services/appointment-framework/guides-tools-appointment-framework.html

#### Agent: `ohs` — Health, Safety & Wellness Agent

Business functions: Occupational health and safety

Instruments (10 total):

- Canada Labour Code, Part II | Legislation | https://laws-lois.justice.gc.ca/eng/acts/l-2/
- Government Employees Compensation Act (GECA) | Legislation | https://laws-lois.justice.gc.ca/eng/acts/g-5/
- Directive on the Prevention and Resolution of Workplace Harassment and Violence | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32671
- Directive on Occupational Health Evaluations | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32636
- Directive on Employee Assistance Programs | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32635
- NJC Occupational Health and Safety Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d7/en
- DAOD 5014-0, Workplace Harassment and Violence Prevention | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5014/5014-0-workplace-harassment-and-violence-prevention.html
- DAOD 2007-0/2007-1, Safety / General Safety Program | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/2000-series/2007/2007-1-general-safety-program.html
- DAOD 5017-0, Mental Health and Wellness | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5017/5017-0-mental-health.html
- DAOD 5005-3, Employee Assistance Program | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5005/5005-3-employee-assistance-program.html

#### Agent: `languages` — Official Languages Agent

Business functions: Official languages

Instruments (10 total):

- Official Languages Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/o-3.01/
- Policy on Official Languages | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=26160
- Directive on Official Languages for People Management | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=26168
- Directive on Official Languages for Communications and Services | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=26164
- Qualification Standards in Relation to Official Languages | Reference | https://www.canada.ca/en/treasury-board-secretariat/services/staffing/qualification-standards/relation-official-languages.html
- PSC Assessment of Official Languages in the Appointment Process | PSC Reference | https://www.canada.ca/en/public-service-commission/services/appointment-framework/guides-tools-appointment-framework/assessment-official-languages-appointment-process.html
- NJC Bilingualism Bonus Directive | NJC Directive | https://www.njc-cnm.gc.ca/directive/d1/en
- DAOD 5039-0, Official Languages | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5039/5039-0-official-languages.html
- DAOD 5039-2, Official Languages in the Workplace | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5039/5039-2-official-languages-in-the-workplace.html
- DAOD 5039-3, Advancement of English and French | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5039/5039-3-advancement-of-english-and-french.html

#### Agent: `governance` — Values, Ethics & HR Governance Agent

Business functions: Values and ethics; Conflict of interest and post-employment; HR planning and reporting; Executive services; Leave and attendance

Instruments (26 total, deduplicated):

- Public Servants Disclosure Protection Act (PSDPA) | Legislation | https://laws-lois.justice.gc.ca/eng/acts/p-31.9/
- Values and Ethics Code for the Public Sector | Code | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=25049
- PSC Political Activities Program | PSC Reference | https://www.canada.ca/en/public-service-commission/services/political-activities.html
- DAOD 7023-0, Defence Ethics | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/7000-series/7023/7023-0-defence-ethics.html
- DAOD 7023-1, Defence Ethics Programme | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/7000-series/7023/7023-1-defence-ethics-programme.html
- Conflict of Interest Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/c-36.65/
- Directive on Conflict of Interest | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32627
- DAOD 7021-0, Conflict of Interest and Post-Employment | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/7000-series/7021/7021-0-conflict-of-interest-and-post-employment.html
- DAOD 7021-1, Conflict of Interest | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/7000-series/7021/7021-1-conflict-of-interest.html
- Policy on People Management | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32621
- Policy Framework for People Management | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=19134
- Directive on the Stewardship of HR Management Systems | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32802
- DAOD 5005-0, Civilian Human Resources Management | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5005/5005-0-civilian-human-resources-management.html
- DAOD 5005-1, Governance of Civilian HR Management | DND DAOD | https://www.canada.ca/en/department-national-defence/corporate/policies-standards/defence-administrative-orders-directives/5000-series/5005/5005-1-governance-of-civilian-human-resources-management.html
- PSC Staffing and Non-Partisanship Survey (SNPS) | PSC Reference | https://www.canada.ca/en/public-service-commission/services/staffing-and-non-partisanship-survey.html
- Cyclical Audit of DND Civilian Staffing | Reference | https://www.canada.ca/en/department-national-defence/corporate/reports-publications/audit-evaluation/cyclical-audit-civilian-staffing.html
- Policy on the Management of Executives | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=25583
- Directive on Terms and Conditions of Employment for Executives | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32625
- Directive on Performance and Talent Management for Executives | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32637
- Directive on Executive (EX) Group Organization and Classification | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32641
- Qualification Standard for the Executive Group | Reference | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=17800
- Directive on Leave and Special Working Arrangements | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=15774
- Directive on Terms and Conditions of Employment | Policy / Directive | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=15772
- Collective Agreements (index) | Reference | https://www.tbs-sct.canada.ca/agreements-conventions/index-eng.aspx
- NJC Disability Insurance Plan | NJC Directive | https://www.njc-cnm.gc.ca/s14/s85/en
- NJC Foreign Service Directives | NJC Directive | https://www.njc-cnm.gc.ca/directive/fsd-dse/en
- Public Service Superannuation Act | Legislation | https://laws-lois.justice.gc.ca/eng/acts/p-36/

---

## 5. Agent Design — Orchestrator Agent

### 5.1 Role

The Orchestrator is the only agent that communicates directly with the user (via the GUI). It receives the user's query, determines which specialist agents to invoke, dispatches the query, collects responses, and synthesizes a unified answer.

### 5.2 Orchestrator System Prompt

```
You are the Orchestrator Agent for the DND HR-Civ Multi-Agent Policy Advisory System.
Your role is to coordinate specialist policy agents to provide comprehensive, accurate,
and well-referenced HR policy guidance.

You manage 8 specialist agents:
- staffing: Staffing & Recruitment (incl. student programs)
- classification: Classification & Compensation (incl. collective agreements)
- labour: Labour Relations & Workplace Management
- learning: Learning, Training & Performance Management
- equity: Equity, Diversity & Inclusion (incl. accessibility)
- ohs: Health, Safety & Wellness
- languages: Official Languages
- governance: Values, Ethics, HR Governance, Executive Services & Leave

WORKFLOW:
1. ANALYZE the user's query. Identify which HR policy domains are implicated.
   Many real-world questions span multiple domains — be thorough.
2. SELECT which specialist agents to invoke. Provide a brief rationale.
3. FORMULATE a focused sub-query for each selected agent, tailored to extract
   the specific policy information needed from that domain.
4. After receiving specialist responses, SYNTHESIZE a unified answer that:
   a. Opens with a direct, natural-language answer to the user's question
   b. Integrates findings across all consulted specialists
   c. Identifies any tensions or conflicts between policy instruments
   d. Presents all citations in a consolidated reference list
   e. Notes any gaps — areas the question touches that the agents could not
      fully address
   f. Where professional judgment or management discretion is required,
      states this explicitly rather than presenting interpretation as settled policy

TONE: Professional, precise, and accessible. Write for an experienced HR advisor
who values accuracy and completeness but does not want to read a legal brief.
Use plain language. Avoid jargon unless it is the established term of art in
federal HR (in which case, use it precisely).

EPISTEMIC STANDARDS:
- Distinguish clearly between what the policy STATES, what it IMPLIES, and what
  is a matter of INTERPRETATION or DISCRETION.
- If specialist agents report low confidence or retrieval failures, disclose this
  to the user.
- Never present general HR knowledge as if it were a specific policy provision.
- When in doubt, recommend consultation with the relevant functional specialist
  (e.g., "This question may benefit from consultation with your labour relations
  advisor").

OUTPUT FORMAT for routing decision (Step 2):
{
  "selected_agents": ["agent_id_1", "agent_id_2"],
  "routing_rationale": "string — why these agents",
  "sub_queries": {
    "agent_id_1": "string — the focused sub-query",
    "agent_id_2": "string — the focused sub-query"
  }
}

OUTPUT FORMAT for final synthesis (Step 4):
{
  "summary": "string — the direct answer in natural language",
  "detailed_analysis": "string — the full multi-layered analysis",
  "policy_tensions": "string or null — any identified conflicts between instruments",
  "citations": [
    {
      "instrument_title": "string",
      "instrument_type": "string",
      "url": "string",
      "relevant_section": "string or null",
      "sourced_from_agent": "string — agent_id"
    }
  ],
  "gaps_and_limitations": "string or null",
  "recommended_consultation": "string or null",
  "agents_consulted": ["agent_id_1", "agent_id_2"],
  "overall_confidence": "high | medium | low"
}
```

### 5.3 Orchestrator Logic (Implementation Notes)

The orchestrator operates in two LLM calls:

1. **Routing call:** Takes the user query + agent registry metadata (names, descriptions, not full instrument lists). Outputs the routing decision (which agents, sub-queries).
2. **Synthesis call:** Takes the user query + all specialist agent responses. Outputs the final synthesized answer.

This two-call design means the orchestrator's context window contains the user query + specialist outputs — not the raw fetched policy content. The specialist agents handle the heavy content processing. This keeps the orchestrator's context budget manageable.

---

## 6. Policy Corpus and Web Fetch Strategy

### 6.1 Fetch Architecture

The Web Fetch Engine is a shared service used by all specialist agents. It is responsible for retrieving, parsing, and caching policy content from authoritative URLs.

### 6.2 Source Domain Characteristics

| Domain | Content Type | Parsing Strategy |
|--------|-------------|-----------------|
| laws-lois.justice.gc.ca | Legislation — well-structured HTML with section IDs | Extract by `<section>` tags; preserve section numbering |
| www.tbs-sct.canada.ca | Policy/Directive — structured HTML, consistent layout | Extract main content div; preserve heading hierarchy |
| www.canada.ca | Mixed — DAODs, PSC instruments, reference pages | Extract `.mwsgeneric-base-html` or main content area |
| www.njc-cnm.gc.ca | NJC Directives — structured HTML | Extract main content; handle bilingual page structure |
| decisions.fpslreb-crtespf.gc.ca | Decision database — search interface | Fetch search results page; extract decision summaries |
| Collective agreement pages | Structured HTML tables and sections | Extract article/section content by heading |

### 6.3 Caching Strategy

All fetched content is cached in SQLite with the following schema:

```sql
CREATE TABLE IF NOT EXISTS fetch_cache (
    url TEXT PRIMARY KEY,
    content_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ttl_hours INTEGER NOT NULL DEFAULT 168,
    status_code INTEGER,
    content_length INTEGER
);
```

**Cache behaviour:**
- Before any fetch, check the cache. If the cached entry exists and is within its TTL, use the cached content.
- If the cache is stale or missing, fetch from the source. On success, update the cache.
- If the fetch fails and a stale cache entry exists, use the stale entry and flag the retrieval as `stale_cache` in the agent's response.
- If both fetch and cache miss, report the failure to the specialist agent.
- Default TTL: 168 hours (7 days). Legislation URLs: 720 hours (30 days, since legislation changes infrequently). Collective agreement URLs: 720 hours.

### 6.4 Content Extraction

Each source domain requires a tailored extraction strategy. The fetch engine must:

1. Retrieve the raw HTML via `httpx`.
2. Parse with BeautifulSoup/lxml.
3. Extract the **main content area** (stripping navigation, headers, footers, sidebars, language-toggle elements).
4. Convert to clean text preserving heading hierarchy and paragraph structure.
5. Truncate to a configurable maximum length (default: 12,000 tokens equivalent, approximately 48,000 characters) to fit within model context windows alongside the agent prompt and other content.

Domain-specific selectors must be defined in configuration, not hard-coded. Example:

```yaml
domain_selectors:
  "laws-lois.justice.gc.ca":
    content_selector: ".lawBody, .regulation-content, main"
    remove_selectors: ["nav", "header", "footer", ".asideContainer"]
  "www.tbs-sct.canada.ca":
    content_selector: "main, .mwsgeneric-base-html"
    remove_selectors: ["nav", "header", "footer", "#wb-info", ".pagedetails"]
  "www.canada.ca":
    content_selector: "main, .mwsgeneric-base-html"
    remove_selectors: ["nav", "header", "footer", "#wb-info", ".pagedetails"]
  "www.njc-cnm.gc.ca":
    content_selector: "main, .content-area, article"
    remove_selectors: ["nav", "header", "footer"]
```

### 6.5 Fetch Concurrency and Rate Limiting

- Maximum 3 concurrent fetches to any single domain.
- Minimum 1-second delay between requests to the same domain.
- Total concurrent fetches across all domains: 10.
- Timeout per request: 30 seconds.
- These are government websites; respectful fetching is essential.

---

## 7. GUI Specification

### 7.1 Design Direction

The GUI follows the established design language used in recent DND ADM(HR-Civ) publications. The reference implementation uses:

- **Font:** EB Garamond (primary serif for headings and body), Calibri/Segoe UI (secondary sans-serif for labels, badges, metadata)
- **Colour palette:**
  - Navy: `#1B2A4A` (primary brand, header backgrounds, section accents)
  - Navy Light: `#2C3E6B` (gradients, hover states)
  - Teal: `#1A8A8A` (accent, interactive elements, agent status indicators)
  - Teal Muted: `#2AA5A5` (secondary accent)
  - Green: `#2E7D5B` (positive status, success states)
  - Off-white: `#F8F6F1` (page background)
  - Card background: `#FFFFFF`
  - Text: `#2D3340`
  - Text Light: `#6B7280` (secondary text, timestamps)
  - Border: `#E0DDD6`
  - Light Grey: `#E8E6E1`
- **Visual characteristics:** Card-based layout with subtle shadows, left-accent borders for categorization, numbered sections with teal counters, navy header gradients with subtle teal overlay, uppercase tracking labels (Calibri, 11px, letter-spacing: 3-4px), clean table styling with navy headers.
- **Tone:** Institutional professionalism — serious, clean, approachable without being casual. No playfulness, no rounded-corner-heavy modern SaaS aesthetic.

### 7.2 Layout Structure

The GUI is a single-page application with three main panels:

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER BAR (navy gradient)                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ ADM(HR-Civ) // HR Policy Advisory System               │ │
│  │ Pilot — Internal Use Only — April 2026                 │ │
│  └────────────────────────────────────────────────────────┘ │
├──────────────────────────────┬──────────────────────────────┤
│  MAIN CHAT PANEL (65%)       │  SIDEBAR (35%)               │
│                              │                              │
│  ┌────────────────────────┐  │  ┌────────────────────────┐ │
│  │ Message history         │  │  │ AGENT STATUS PANEL     │ │
│  │ (scrollable)            │  │  │                        │ │
│  │                         │  │  │ ○ Orchestrator         │ │
│  │ ┌──────────────────┐   │  │  │ ○ Staffing Agent       │ │
│  │ │ User message      │   │  │  │ ○ Classification Agent │ │
│  │ └──────────────────┘   │  │  │ ○ Labour Agent         │ │
│  │                         │  │  │ ○ Learning Agent       │ │
│  │ ┌──────────────────┐   │  │  │ ○ Equity Agent         │ │
│  │ │ System response    │   │  │  │ ○ OHS Agent            │ │
│  │ │ with citations     │   │  │  │ ○ Languages Agent      │ │
│  │ │ and agent badges   │   │  │  │ ○ Governance Agent     │ │
│  │ └──────────────────┘   │  │  │                        │ │
│  │                         │  │  │ Status indicators:     │ │
│  │                         │  │  │ ● idle  ● working     │ │
│  │                         │  │  │ ● done  ● error       │ │
│  └────────────────────────┘  │  └────────────────────────┘ │
│                              │                              │
│  ┌────────────────────────┐  │  ┌────────────────────────┐ │
│  │ Query input area        │  │  │ CITATION PANEL         │ │
│  │ [  Type your query...  ]│  │  │ (populated after       │ │
│  │ [Send]                  │  │  │  response; clickable   │ │
│  └────────────────────────┘  │  │  links to sources)     │ │
│                              │  └────────────────────────┘ │
│                              │                              │
│                              │  ┌────────────────────────┐ │
│                              │  │ FEEDBACK PANEL          │ │
│                              │  │ (appears after each     │ │
│                              │  │  response)              │ │
│                              │  │ [Accurate] [Needs Work] │ │
│                              │  │ [Comment box]           │ │
│                              │  │ [Submit Feedback]       │ │
│                              │  └────────────────────────┘ │
├──────────────────────────────┴──────────────────────────────┤
│  FOOTER                                                      │
│  ADM(HR-Civ) — Pilot System — Not for Operational Decisions  │
└─────────────────────────────────────────────────────────────┘
```

### 7.3 Chat Panel Behaviour

- Messages stream in via WebSocket. Agent responses appear progressively (token by token or chunk by chunk) to provide feedback during processing.
- User messages are displayed with a light background, right-aligned.
- System responses are displayed with a white card background, left-aligned, with:
  - An orchestrator attribution line at the top
  - Inline citation markers (superscript numbers) that correspond to the Citation Panel
  - Agent contribution badges showing which specialists were consulted (teal badges with agent names)
  - A confidence indicator (high/medium/low) displayed as a subtle badge
- A "processing" state shows which agents are currently active (animated indicators in the Agent Status Panel).

### 7.4 Agent Status Panel

Real-time display of all 9 agents (orchestrator + 8 specialists):

- **Idle** (grey dot): Agent has not been invoked for this query.
- **Working** (pulsing teal dot): Agent is currently processing (fetching or reasoning).
- **Complete** (green dot): Agent has returned its response.
- **Error** (amber dot): Agent encountered a fetch or processing error.

Status updates are pushed via WebSocket as processing occurs.

### 7.5 Citation Panel

After each response, the Citation Panel populates with:

- Numbered list of all cited instruments
- Each entry shows: instrument title, instrument type (as a small badge), and a clickable URL that opens in a new tab
- Grouped by the specialist agent that sourced them

### 7.6 Feedback Panel

Appears below the Citation Panel after each system response:

- Two quick-feedback buttons: "Accurate" (green) and "Needs Work" (amber)
- An expandable text area for detailed comments
- A "Submit Feedback" button
- After submission, displays a brief confirmation and the feedback is stored in the database

### 7.7 Responsive Behaviour

- On screens narrower than 1024px, the sidebar collapses to a tabbed interface below the chat panel.
- The chat panel always takes priority in the layout.

### 7.8 Implementation Notes

- The GUI is pure HTML/CSS/JS — no build toolchain, no npm, no React.
- FastAPI serves the static HTML file and handles WebSocket connections.
- The EB Garamond font is loaded from Google Fonts CDN (`https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,600;0,700;1,400&display=swap`).
- The fallback font stack is: `'EB Garamond', Georgia, 'Times New Roman', serif` for body/headings, and `Calibri, 'Segoe UI', sans-serif` for labels and metadata.

---

## 8. Feedback System

### 8.1 Purpose

The feedback system captures HR specialist evaluations of system outputs. This data drives iterative improvement of agent prompts, policy registry completeness, and orchestration logic.

### 8.2 Database Schema

```sql
CREATE TABLE IF NOT EXISTS queries (
    query_id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agents_invoked TEXT NOT NULL,  -- JSON array of agent IDs
    overall_confidence TEXT,  -- high/medium/low
    processing_time_ms INTEGER
);

CREATE TABLE IF NOT EXISTS agent_responses (
    response_id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL REFERENCES queries(query_id),
    agent_id TEXT NOT NULL,
    findings TEXT,
    citations TEXT,  -- JSON array
    caveats TEXT,
    confidence TEXT,
    retrieval_status TEXT,  -- JSON object
    processing_time_ms INTEGER
);

CREATE TABLE IF NOT EXISTS orchestrator_responses (
    response_id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL REFERENCES queries(query_id),
    summary TEXT NOT NULL,
    detailed_analysis TEXT,
    policy_tensions TEXT,
    citations TEXT,  -- JSON array (consolidated)
    gaps_and_limitations TEXT,
    recommended_consultation TEXT,
    overall_confidence TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL REFERENCES queries(query_id),
    rating TEXT NOT NULL,  -- 'accurate' or 'needs_work'
    comment TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fetch_cache (
    url TEXT PRIMARY KEY,
    content_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ttl_hours INTEGER NOT NULL DEFAULT 168,
    status_code INTEGER,
    content_length INTEGER
);
```

### 8.3 Export

Provide a simple endpoint (`GET /api/feedback/export`) that returns all feedback records as JSON or CSV for offline analysis.

---

## 9. Project File Structure

```
hr-policy-agent/
├── CLAUDE.md                    # Claude Code agent instructions (generated by Claude Code)
├── AGENTS.md                    # OpenCode agent context (generated by Claude Code)
├── config.yaml                  # System configuration
├── requirements.txt             # Python dependencies
├── README.md                    # Project documentation
│
├── src/
│   ├── __init__.py
│   ├── main.py                  # FastAPI application entry point
│   ├── config.py                # Configuration loader (YAML → Pydantic models)
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py              # Base agent class
│   │   ├── orchestrator.py      # Orchestrator agent
│   │   ├── specialist.py        # Specialist agent class (single class, configured per domain)
│   │   └── prompts/
│   │       ├── __init__.py
│   │       ├── orchestrator_prompt.py
│   │       └── specialist_prompts.py   # All 8 specialist system prompts
│   │
│   ├── fetch/
│   │   ├── __init__.py
│   │   ├── engine.py            # Web fetch engine (httpx + BeautifulSoup)
│   │   ├── cache.py             # SQLite cache layer
│   │   ├── extractors.py        # Domain-specific content extractors
│   │   └── selectors.yaml       # CSS selector config per domain
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py            # Ollama client wrapper
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── policy_registry.json # Complete policy inventory (generated from Excel)
│   │   └── db.py                # SQLite database manager
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py            # REST API endpoints
│   │   └── websocket.py         # WebSocket handler for streaming
│   │
│   └── models/
│       ├── __init__.py
│       └── schemas.py           # Pydantic models for all data structures
│
├── static/
│   ├── index.html               # Main GUI (single file)
│   ├── css/
│   │   └── styles.css           # GUI stylesheet
│   └── js/
│       └── app.js               # GUI application logic (WebSocket, DOM manipulation)
│
├── tests/
│   ├── __init__.py
│   ├── test_fetch.py            # Web fetch engine tests
│   ├── test_agents.py           # Agent logic tests
│   ├── test_orchestrator.py     # Orchestrator routing tests
│   └── test_api.py              # API endpoint tests
│
├── logs/
│   └── .gitkeep
│
└── data/
    └── hr_policy_agent.db       # SQLite database (created at runtime)
```

---

## 10. Claude Code Responsibilities

The Claude Code (Sonnet 4.6) instance is responsible for:

### 10.1 First Actions (Before Any Implementation)

1. Read this master plan document in full.
2. Create the project directory structure as defined in Section 9.
3. Create `CLAUDE.md` with its own operational instructions for the project.
4. Create `AGENTS.md` (or equivalent OpenCode context files) with clear instructions for the local coding model.
5. Generate `policy_registry.json` from the inventory in Section 4.4.
6. Generate `config.yaml` with the structure from Section 3.3.
7. Generate `requirements.txt` from Section 3.2.

### 10.2 Architecture and Scaffolding

1. Create all `__init__.py` files.
2. Implement `src/models/schemas.py` — all Pydantic models for the entire system.
3. Implement `src/config.py` — configuration loader.
4. Implement `src/data/db.py` — database initialization and management.

### 10.3 Task Generation for OpenCode

For each implementation task, Claude Code must create a task specification file with:

- **Task ID** (sequential, e.g., `TASK-001`)
- **Task title**
- **Input files** (which existing files the task depends on)
- **Output files** (which files the task must create or modify)
- **Detailed specification** (what the code must do, with sufficient precision that the local model can implement it without ambiguity)
- **Acceptance criteria** (specific, testable conditions that determine whether the task is complete)
- **Maximum scope** (what the task must NOT touch)

### 10.4 Validation

After each OpenCode task completion, Claude Code must:

1. Read the output files.
2. Verify against the acceptance criteria.
3. Run any applicable tests.
4. Identify defects and either fix them directly or generate a corrective task for OpenCode.

### 10.5 Implementation Tier Guidance

The following tasks should be implemented by Claude Code (Sonnet 4.6) directly, not delegated to OpenCode, because they involve complex orchestration logic:

- `src/agents/orchestrator.py`
- `src/agents/specialist.py`
- `src/api/websocket.py` (WebSocket streaming with concurrent agent execution)
- `src/fetch/engine.py` (async fetch with concurrency control and caching)

The following tasks are well-suited for OpenCode delegation:

- `src/models/schemas.py`
- `src/config.py`
- `src/data/db.py`
- `src/data/policy_registry.json`
- `src/llm/client.py`
- `src/fetch/cache.py`
- `src/fetch/extractors.py`
- `src/api/routes.py`
- `static/css/styles.css`
- `static/js/app.js`
- `static/index.html`
- `tests/*`
- `config.yaml`
- `requirements.txt`

---

## 11. OpenCode Task Specifications

The following tasks are ordered sequentially. Each task must be completed and validated before the next begins. Claude Code should generate these as individual task files in a `tasks/` directory.

### TASK-001: Project Scaffolding and Configuration

**Output files:** All directories, `__init__.py` files, `config.yaml`, `requirements.txt`, `README.md`
**Specification:** Create the complete directory structure from Section 9. Generate `config.yaml` using the template in Section 3.3. Generate `requirements.txt` from Section 3.2. Generate a README.md with project title, description, setup instructions (Python venv, pip install, Ollama model pull, uvicorn start command).
**Acceptance criteria:** All directories exist. All `__init__.py` files exist. `config.yaml` is valid YAML. `requirements.txt` lists all dependencies. `README.md` is complete and accurate.
**Max scope:** Do not implement any Python logic beyond `__init__.py` files.

### TASK-002: Pydantic Data Models

**Input files:** This master plan (Sections 4.3, 5.2, 8.2)
**Output files:** `src/models/schemas.py`
**Specification:** Implement all Pydantic v2 models for: agent configuration, policy instrument, specialist agent response, orchestrator routing decision, orchestrator synthesis response, query record, feedback record, fetch cache entry, WebSocket message types (user_query, agent_status_update, response_chunk, response_complete, error).
**Acceptance criteria:** All models validate correctly. JSON serialization/deserialization works. All fields from the system prompts in Sections 4.3 and 5.2 are represented.
**Max scope:** Do not implement any business logic. Models only.

### TASK-003: Configuration Loader

**Input files:** `config.yaml`, `src/models/schemas.py`
**Output files:** `src/config.py`
**Specification:** Implement a configuration loader that reads `config.yaml` and returns validated Pydantic configuration objects. Support environment variable overrides for sensitive values. Include a `get_config()` singleton function.
**Acceptance criteria:** Loading a valid config.yaml produces a typed configuration object. Missing required fields raise clear errors. Environment variables override YAML values.
**Max scope:** Configuration loading only.

### TASK-004: Policy Registry Generation

**Input files:** This master plan (Section 4.4)
**Output files:** `src/data/policy_registry.json`
**Specification:** Generate the complete policy registry as a JSON file. Structure: a list of instrument objects, each with: `id` (slugified title), `title`, `type`, `url`, `agent_ids` (list of agent IDs this instrument is assigned to). Instruments that appear in multiple agents must appear once with multiple agent_ids. Deduplicate by URL.
**Acceptance criteria:** JSON is valid. All 147 entries from the spreadsheet are represented (deduplicated to ~131 unique by URL). Every agent ID referenced exists in the agent list. No duplicate URLs.
**Max scope:** Data file generation only.

### TASK-005: Database Manager

**Input files:** `src/models/schemas.py`, schema from Section 8.2
**Output files:** `src/data/db.py`
**Specification:** Implement an async SQLite database manager using `aiosqlite`. Include: initialization (create tables if not exist), CRUD operations for all tables (queries, agent_responses, orchestrator_responses, feedback, fetch_cache), and a feedback export function. Use the schema from Section 8.2.
**Acceptance criteria:** Database initializes cleanly on first run. All CRUD operations work. Feedback export returns valid JSON. Concurrent access does not corrupt data.
**Max scope:** Database operations only. No API or agent logic.

### TASK-006: Ollama Client Wrapper

**Input files:** `src/config.py`, `src/models/schemas.py`
**Output files:** `src/llm/client.py`
**Specification:** Implement an async Ollama client wrapper using the `ollama` Python package. Support: chat completions with system prompts, streaming responses (yield chunks), configurable model name/temperature/context window from config, structured JSON output parsing (attempt to parse response as JSON, return raw text on failure), and health check (verify Ollama is running and model is available).
**Acceptance criteria:** Client connects to Ollama. Streaming works. JSON parsing works for valid JSON responses. Health check returns model status. Configuration is respected.
**Max scope:** LLM client only. No agent logic.

### TASK-007: Fetch Cache Layer

**Input files:** `src/data/db.py`, `src/models/schemas.py`
**Output files:** `src/fetch/cache.py`
**Specification:** Implement the fetch cache as described in Section 6.3. Functions: `get_cached(url)` returns cached content if within TTL, `set_cached(url, content, ttl_hours)` stores or updates, `get_stale(url)` returns expired cache if available, `clear_expired()` removes entries past TTL.
**Acceptance criteria:** Cache hit returns content within TTL. Cache miss returns None. Stale cache returns expired content. TTL expiry works correctly.
**Max scope:** Cache layer only.

### TASK-008: Content Extractors

**Input files:** `src/fetch/selectors.yaml` (create this file too), Section 6.4
**Output files:** `src/fetch/extractors.py`, `src/fetch/selectors.yaml`
**Specification:** Implement domain-specific content extractors using BeautifulSoup. Create `selectors.yaml` with CSS selectors per domain from Section 6.4. The extractor takes raw HTML + domain and returns clean text with preserved heading hierarchy. Include a text truncation function (configurable max characters, default 48000). Handle edge cases: empty content, connection errors, unexpected HTML structure.
**Acceptance criteria:** Extractors produce clean text from sample HTML. Navigation/header/footer elements are stripped. Heading hierarchy is preserved. Truncation works. Unknown domains fall back to extracting `<main>` or `<body>`.
**Max scope:** Content extraction only. No HTTP fetching.

### TASK-009: Web Fetch Engine

**Input files:** `src/fetch/cache.py`, `src/fetch/extractors.py`, `src/config.py`
**Output files:** `src/fetch/engine.py`
**Specification:** Implement the async web fetch engine as described in Sections 6.1-6.5. Features: async fetching with httpx, per-domain concurrency limiting (semaphore, max 3 per domain), global concurrency limit (10), minimum 1-second delay between requests to the same domain, cache integration (check before fetch, store after fetch, use stale on failure), and batch fetch support (fetch multiple URLs concurrently within limits).
**Acceptance criteria:** Fetches return clean text content. Concurrency limits are enforced. Cache is consulted and updated. Failed fetches fall back to stale cache. Rate limiting works. Timeout is respected (30s).
**Max scope:** Fetch engine only. No agent logic.

**NOTE FOR CLAUDE CODE: This task (TASK-009) should be implemented by Claude Code directly (Sonnet 4.6), not delegated to OpenCode, due to the complexity of async concurrency control.**

### TASK-010: REST API Routes

**Input files:** `src/models/schemas.py`, `src/data/db.py`
**Output files:** `src/api/routes.py`
**Specification:** Implement FastAPI REST endpoints: `POST /api/query` (submit a query — returns query_id for WebSocket tracking), `GET /api/queries` (list recent queries), `GET /api/queries/{query_id}` (get query details with response), `POST /api/feedback` (submit feedback for a query), `GET /api/feedback/export` (export all feedback as JSON), `GET /api/health` (system health — Ollama status, cache stats, DB status), and `GET /api/agents` (list all agents with their metadata).
**Acceptance criteria:** All endpoints return correct status codes. Validation errors return 422 with clear messages. Health endpoint accurately reports component status.
**Max scope:** API routing only. Query processing happens via WebSocket (TASK-013).

### TASK-011: GUI — HTML Structure

**Input files:** Section 7 (GUI Specification)
**Output files:** `static/index.html`
**Specification:** Implement the HTML structure from Section 7.2. Single-file HTML with semantic structure. Include the Google Fonts import for EB Garamond. Include placeholder elements for all panels (chat, agent status, citations, feedback). Include the CSS link and JS script tags.
**Acceptance criteria:** HTML is valid. All panels from Section 7.2 are represented. Font loads correctly. Layout matches the specification.
**Max scope:** HTML structure only. Styling in TASK-012, logic in TASK-013.

### TASK-012: GUI — Stylesheet

**Input files:** Section 7.1 (design specification), the reference HTML document provided by the operator
**Output files:** `static/css/styles.css`
**Specification:** Implement the complete stylesheet following the design language in Section 7.1. Use the exact colour palette, font stack, and visual characteristics specified. Key elements: navy gradient header, card-based message display with subtle shadows, teal accent borders, uppercase tracked labels for metadata, agent status indicators (coloured dots with appropriate states), citation panel with grouped entries, feedback panel with button styling matching the institutional tone. Responsive breakpoint at 1024px (sidebar collapses below chat panel).
**Acceptance criteria:** Visual output matches the design language described in Section 7.1 and the reference HTML document. Responsive behaviour works. All component states (idle, working, complete, error) are visually distinct. Typography matches specification.
**Max scope:** CSS only. No JavaScript.

### TASK-013: GUI — Application Logic

**Input files:** `static/index.html`, `src/models/schemas.py` (for WebSocket message types)
**Output files:** `static/js/app.js`
**Specification:** Implement the client-side JavaScript for the GUI. Features: WebSocket connection to the server, message submission (send query, display in chat), streaming response display (progressive text rendering as chunks arrive), agent status panel updates (real-time status changes for each agent), citation panel population (after response complete), feedback submission (rating + comment), error handling (connection loss, server errors), and auto-scroll behaviour in chat panel.
**Acceptance criteria:** WebSocket connects on page load. Messages send and display correctly. Streaming responses render progressively. Agent status updates in real time. Citations populate correctly with clickable links. Feedback submits and confirms. Reconnection on WebSocket drop.
**Max scope:** Client-side logic only.

**NOTE FOR CLAUDE CODE: This task should be implemented by Claude Code directly (Sonnet 4.6) due to the WebSocket coordination complexity.**

### TASK-014: Specialist Agent Implementation

**Input files:** `src/agents/base.py` (create this), `src/llm/client.py`, `src/fetch/engine.py`, `src/data/policy_registry.json`, Section 4
**Output files:** `src/agents/base.py`, `src/agents/specialist.py`, `src/agents/prompts/specialist_prompts.py`
**Specification:** Implement the specialist agent class. The base class defines the interface (process query → structured response). The specialist class is configured per domain using the system prompt template from Section 4.3 and the policy registry. For a given query, the specialist: loads its policy registry subset, determines which instruments are likely relevant (using the LLM for relevance assessment), fetches those instruments via the web fetch engine, constructs a prompt with the query + fetched content, calls the LLM, and parses the structured JSON response.
**Acceptance criteria:** Agent initializes with correct policy registry subset. Relevance assessment works. Fetch engine is called for selected instruments. LLM response is parsed correctly. Structured output matches the schema in Section 4.3. Error handling for fetch failures and LLM parsing failures.
**Max scope:** Specialist agent only. No orchestrator logic.

**NOTE FOR CLAUDE CODE: This task should be implemented by Claude Code directly (Sonnet 4.6).**

### TASK-015: Orchestrator Agent Implementation

**Input files:** `src/agents/specialist.py`, `src/llm/client.py`, Section 5
**Output files:** `src/agents/orchestrator.py`, `src/agents/prompts/orchestrator_prompt.py`
**Specification:** Implement the orchestrator agent as described in Section 5. Two-call design: (1) routing call to determine which specialists to invoke, (2) synthesis call to combine specialist responses. Support parallel specialist execution (asyncio.gather). Handle specialist errors gracefully (include in synthesis with error notes).
**Acceptance criteria:** Routing correctly identifies relevant agents for multi-domain queries. Specialists are invoked in parallel. Synthesis combines all specialist outputs coherently. Citations are deduplicated and consolidated. Error handling works.
**Max scope:** Orchestrator only.

**NOTE FOR CLAUDE CODE: This task should be implemented by Claude Code directly (Sonnet 4.6).**

### TASK-016: WebSocket Handler

**Input files:** `src/agents/orchestrator.py`, `src/api/routes.py`, `src/models/schemas.py`
**Output files:** `src/api/websocket.py`
**Specification:** Implement the WebSocket handler that connects the GUI to the agent system. On receiving a query: create a query record, send status updates as agents are invoked/complete, stream the orchestrator's synthesis response, send the final citation list, and enable the feedback panel.
**Acceptance criteria:** Full request lifecycle works end-to-end via WebSocket. Status updates arrive in real time. Response streams correctly. Citation data arrives after response. Error states are communicated to the client.
**Max scope:** WebSocket coordination only.

**NOTE FOR CLAUDE CODE: This task should be implemented by Claude Code directly (Sonnet 4.6).**

### TASK-017: FastAPI Application Entry Point

**Input files:** All src/ modules
**Output files:** `src/main.py`
**Specification:** Wire everything together. FastAPI app with: static file serving (mount `static/` directory), REST API routes, WebSocket endpoint, database initialization on startup, configuration loading, and Ollama health check on startup.
**Acceptance criteria:** `uvicorn src.main:app` starts the server. Static files serve correctly. API endpoints work. WebSocket connects. Database initializes.
**Max scope:** Wiring only. No new business logic.

### TASK-018: Integration Testing

**Input files:** All src/ modules
**Output files:** `tests/` directory with comprehensive tests
**Specification:** Write integration tests covering: fetch engine with cache (mock HTTP), specialist agent with mock LLM responses, orchestrator routing logic, API endpoints, and WebSocket message flow.
**Acceptance criteria:** Tests pass. Coverage includes happy path and error scenarios.
**Max scope:** Tests only.

---

## 12. Task Sequencing and Dependencies

```
TASK-001 (scaffolding)
    ├── TASK-002 (Pydantic models)
    │   ├── TASK-003 (config loader)
    │   ├── TASK-004 (policy registry JSON)
    │   ├── TASK-005 (database manager)
    │   │   └── TASK-007 (fetch cache)
    │   │       └── TASK-008 (content extractors)
    │   │           └── TASK-009 (fetch engine) [CLAUDE CODE]
    │   ├── TASK-006 (Ollama client)
    │   └── TASK-010 (API routes)
    │
    ├── TASK-011 (HTML structure)
    │   └── TASK-012 (CSS stylesheet)
    │       └── TASK-013 (JS app logic) [CLAUDE CODE]
    │
    ├── TASK-014 (specialist agent) [CLAUDE CODE]
    │   └── TASK-015 (orchestrator agent) [CLAUDE CODE]
    │       └── TASK-016 (WebSocket handler) [CLAUDE CODE]
    │           └── TASK-017 (main.py entry point)
    │               └── TASK-018 (integration tests)
```

Tasks marked `[CLAUDE CODE]` should be implemented by Claude Code (Sonnet 4.6) directly. All others are suitable for OpenCode delegation with the local model.

---

## 13. Validation and Testing Protocol

### 13.1 Per-Task Validation (Claude Code)

After each OpenCode task:
1. Read all output files.
2. Check against acceptance criteria.
3. Run `python -m py_compile` on all Python files to verify syntax.
4. Run any applicable tests.
5. If defects found: generate a corrective task or fix directly.

### 13.2 Integration Validation

After TASK-017:
1. Start the server: `uvicorn src.main:app --host 0.0.0.0 --port 8000`
2. Verify GUI loads at `http://localhost:8000`
3. Verify Ollama health check passes
4. Submit a test query: "What are the requirements for staffing a bilingual position at DND?"
5. Verify: orchestrator routes to staffing + languages agents, both agents fetch relevant instruments, response includes citations from both domains, GUI displays the full response with status updates and citations.

### 13.3 Policy Quality Validation (Human Operator)

The human operator will evaluate system responses against known policy scenarios:
- Single-domain queries (straightforward policy lookups)
- Multi-domain queries (questions that span multiple policy areas)
- Ambiguous queries (where policy is unclear or instruments conflict)
- Out-of-scope queries (questions the system should decline to answer authoritatively)

---

## 14. Future Migration Considerations

This section is informational. It does not affect the current implementation but documents architectural decisions that facilitate future enterprise migration.

### 14.1 Migration Path to Defence365 / M365

When this system is migrated to the enterprise environment:

- **Specialist agents** → Copilot Studio custom engine agents, each grounded on a SharePoint document library containing the relevant policy instruments.
- **Orchestrator** → A primary Copilot Studio agent with topic routing, or a Power Automate orchestration flow.
- **Web fetch** → Replaced by SharePoint knowledge source grounding (live connection) and/or web grounding if enabled for public GC sources.
- **GUI** → Teams deployment channel and/or SharePoint embedded web part.
- **Feedback** → SharePoint list or Dataverse table.
- **Identity** → Entra Agent ID (when GA) for audit and governance.

### 14.2 Design Decisions That Support Migration

- Agent specialization boundaries align with SharePoint library boundaries.
- System prompts are externalized (not hard-coded) — portable to Copilot Studio system instructions.
- Structured JSON output schema maps to Power Automate flow inputs.
- The feedback data structure maps directly to a SharePoint list schema.

---

## Document End

This master plan is complete. Claude Code should begin with Section 10.1 (First Actions) and proceed through the task sequence defined in Section 12.
