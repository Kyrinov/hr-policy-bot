# HR Policy Advisory System — User Guide

**DND ADM(HR-Civ) — Pilot System — Internal Use Only**
**April 2026 | Not for Operational Decisions**

---

## Contents

1. [What This System Does](#1-what-this-system-does)
2. [What This System Is Not](#2-what-this-system-is-not)
3. [Setup and Installation](#3-setup-and-installation)
4. [Starting the System](#4-starting-the-system)
5. [Using the Interface](#5-using-the-interface)
6. [Understanding the Agent System](#6-understanding-the-agent-system)
7. [Reading Citations](#7-reading-citations)
8. [Submitting Feedback](#8-submitting-feedback)
9. [Asking Good Questions](#9-asking-good-questions)
10. [Known Limitations](#10-known-limitations)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What This System Does

The HR Policy Advisory System helps DND civilian HR advisors find policy guidance on real-world HR questions. When you submit a question, the system:

1. Analyses your question to identify which HR policy domains are involved.
2. Dispatches the question to one or more specialist agents, each responsible for a specific domain (staffing, classification, labour relations, etc.).
3. Each specialist retrieves the current text of relevant policy instruments directly from authoritative Government of Canada sources (legislation, TBS directives, PSC instruments, NJC directives, DAODs, and collective agreements).
4. Each specialist analyses the retrieved content against your question and produces a structured response with findings and citations.
5. An orchestrator agent synthesizes all specialist responses into a single coherent answer and assembles a consolidated citation list.
6. The final response is streamed to your screen in real time.

Every factual claim in the response is grounded in content actually retrieved from authoritative sources during your session. The URLs in the citation panel link directly to those sources so you can verify any statement the system makes.

---

## 2. What This System Is Not

**Read this section before using the system.**

- **Not legal advice.** The system synthesizes policy instruments as written. It does not provide legal interpretation, and its outputs should not be treated as authoritative rulings.
- **Not a replacement for professional judgment.** HR policy often requires discretion, contextual knowledge, and experience. The system provides a starting point for analysis, not a final answer.
- **Not infallible.** The system can misread policy provisions, miss relevant instruments, or fail to surface a conflict between instruments. Always verify important claims against the source documents linked in the citation panel.
- **Not approved for operational decisions.** This is a pilot proof-of-concept. Responses must be reviewed by a qualified HR advisor before being acted upon.
- **Not connected to classified or internal DND systems.** The system retrieves content only from publicly available Government of Canada websites.

---

## 3. Setup and Installation

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11 or later | Check with `python3 --version` |
| Ollama | Must be running locally. Download from ollama.com |
| Qwen3.5:35b model | Pull with `ollama pull qwen3.5:35b` |
| ~40 GB free VRAM | System is sized for the Jetson Orin AGX (64 GB) |
| Internet access | Required to fetch policy content from GC websites |

### Installation

```bash
# Clone or navigate to the project directory
cd /home/charles/HR_policy_bot_proto

# Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Open `config.yaml` to review or adjust settings:

```yaml
model:
  name: "qwen3.5:35b"   # Model name as it appears in Ollama
  temperature: 0.2       # Lower = more conservative, policy-appropriate responses
  num_ctx: 32768         # Context window size
  top_p: 0.9

server:
  host: "0.0.0.0"
  port: 8000             # Change this if port 8000 is already in use

cache:
  ttl_hours: 168         # How long fetched policy content is cached (7 days)
  max_size_mb: 500
```

To switch models without editing code, change the `model.name` value in `config.yaml` to any model you have available in Ollama (e.g., `gemma4:26b`).

---

## 4. Starting the System

### Step 1 — Ensure Ollama is running

```bash
ollama serve
```

If Ollama is already running as a service, skip this step. Verify the model is available:

```bash
ollama list
```

You should see `qwen3.5:35b` in the list. If not:

```bash
ollama pull qwen3.5:35b
```

### Step 2 — Start the application

```bash
# From the project directory, with the virtual environment active
source .venv/bin/activate
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

You will see startup output similar to:

```
INFO: Starting DND HR-Civ Policy Advisory System
INFO: Database initialized
INFO: Ollama connected, available models: ['qwen3.5:35b']
INFO: Uvicorn running on http://0.0.0.0:8000
```

If the Ollama connection warning appears but the server still starts, the system will attempt to connect on the first query. This is not fatal.

### Step 3 — Open the interface

Open a browser and navigate to:

```
http://localhost:8000
```

If accessing from another machine on the same network, replace `localhost` with the server's IP address.

### Keeping the system running (optional)

To run the server in the background and keep it alive across SSH sessions, use the provided watcher script from a separate terminal:

```bash
# Start the server in a tmux session
tmux new-session -s hrpolicy
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

---

## 5. Using the Interface

### Layout overview

```
┌─────────────────────────────────────────────────────────────┐
│  HEADER: ADM(HR-Civ) // HR Policy Advisory System           │
├──────────────────────────────┬──────────────────────────────┤
│                              │  Agent Status                 │
│   Chat history               │  (real-time indicators)       │
│   (scrollable)               │                               │
│                              │  Policy Citations             │
│                              │  (populated after response)   │
│   Query input box            │                               │
│   [Send Query]               │  Feedback                     │
│                              │  (appears after response)     │
└──────────────────────────────┴──────────────────────────────┘
│  FOOTER: Not for Operational Decisions                       │
└─────────────────────────────────────────────────────────────┘
```

On screens narrower than 1024 px, the sidebar moves below the chat panel.

### Submitting a question

1. Type your question in the text area at the bottom of the chat panel.
2. Press **Send Query** or hit **Enter** (Shift+Enter adds a new line without submitting).
3. The system begins processing immediately. You will see agent status indicators update in the sidebar as each specialist is invoked.

### While the system is processing

- The **Agent Status panel** (top right) shows which agents are active. Teal pulsing dots indicate an agent is currently working.
- The response text will begin appearing in the chat as the orchestrator streams its synthesis. This may take 30–120 seconds depending on how many agents are invoked and how much policy content is retrieved.
- Do not submit a new question while processing is underway. The input is disabled until the current response is complete.

### After the response appears

- The full response is displayed in the chat panel, organized as a summary followed by a detailed analysis.
- Agent badges show which specialists contributed to the response.
- A confidence indicator (high / medium / low) reflects the system's self-assessed certainty.
- The **Citation Panel** (middle right) is populated with all referenced instruments, grouped by the specialist that sourced them.
- The **Feedback Panel** (bottom right) appears, allowing you to rate the response.

---

## 6. Understanding the Agent System

### The nine agents

| Agent | Domain |
|-------|--------|
| **Orchestrator** | Coordinates all other agents. Routes your query, collects responses, and writes the final synthesized answer. You never interact with it directly. |
| **Staffing & Recruitment** | Public Service Employment Act, PSC appointment framework, priority entitlements, student programs, DAODs on civilian staffing. |
| **Classification & Compensation** | Classification directives, collective agreements (PA, SV, TC, IT, EC groups), compensation policy, benefits (PSHCP, PSDCP, superannuation), NJC directives on pay and benefits. |
| **Labour Relations** | Federal Public Sector Labour Relations Act, grievance procedures, workforce adjustment, bargaining agent relations, FPSLREB decisions. |
| **Learning & Performance** | Mandatory training directives, Canada School of Public Service, performance management (including EX group), DAODs on civilian learning. |
| **Equity, Diversity & Inclusion** | Canadian Human Rights Act, Employment Equity Act, Accessible Canada Act, duty to accommodate, DAODs on human rights and accommodation. |
| **Health, Safety & Wellness** | Canada Labour Code (Part II), harassment and violence prevention, OHS directive, mental health, employee assistance programs. |
| **Official Languages** | Official Languages Act, TBS policy and directives on official languages, bilingualism bonus, DAODs on official languages at DND. |
| **Values, Ethics & Governance** | Values and Ethics Code, conflict of interest, disclosure protection, leave directives, executive management policy, HR governance DAODs. |

### Agent status indicators

| Indicator | Meaning |
|-----------|---------|
| Grey dot | Agent was not invoked for this query |
| Pulsing teal dot | Agent is currently fetching policy content or generating its response |
| Green dot | Agent completed successfully |
| Amber dot | Agent encountered an error (fetch failure or parsing problem); the orchestrator will note this in the response |

### Why some agents are not invoked

The orchestrator performs a routing step before dispatching to specialists. It selects only agents whose domain is genuinely relevant to your question. A question about overtime pay, for example, would invoke the Classification & Compensation agent and possibly the Governance agent (for leave provisions), but not the Official Languages or OHS agents. This keeps responses focused and processing time manageable.

If you believe a relevant domain was missed, try rephrasing your question to make the cross-domain aspect explicit (see [Section 9](#9-asking-good-questions)).

---

## 7. Reading Citations

The Citation Panel appears after each response and lists all policy instruments referenced by the specialist agents, grouped by agent.

### Citation entry format

Each citation shows:
- **Instrument title** — the full official name of the policy instrument, as a clickable link
- **Instrument type** — one of: Legislation, Policy / Directive, PSC Instrument, NJC Directive, DND DAOD, Collective Agreement, Reference, Strategy, Code
- **Relevant section** — where identified, the specific section or article that was cited

Clicking the instrument title opens the authoritative source in a new tab. This is the same page the agent retrieved content from during your session.

### Citation types explained

| Type | What it means |
|------|---------------|
| **Legislation** | An Act of Parliament (e.g., the Public Service Employment Act). Highest in the hierarchy; cannot be overridden by policy. |
| **Policy / Directive** | Treasury Board policy instruments. Binding on departments. |
| **PSC Instrument** | Public Service Commission appointment policies, guides, and tools. Binding for staffing within the public service. |
| **NJC Directive** | National Joint Council directives. Negotiated between bargaining agents and the employer; incorporated by reference into collective agreements. |
| **DND DAOD** | Defence Administrative Orders and Directives. DND-specific application of federal policy. |
| **Collective Agreement** | The negotiated agreement for a specific occupational group. Provisions prevail over directives where the CA provides a greater benefit. |
| **Reference / Strategy** | Non-binding guidance, inventories, or strategic documents. Informative but not enforceable. |

### When citations are absent or sparse

If the response contains few or no citations, this usually means:
- The fetch engine could not retrieve content from the relevant URLs during your session (network issue or site unavailability). The response will note retrieval failures.
- The query fell outside the scope of the corpus and the agents appropriately declined to answer from general knowledge.

In either case, the confidence indicator will reflect this uncertainty.

---

## 8. Submitting Feedback

After each response, a feedback panel appears in the lower right sidebar. Your feedback is stored in the local database and used to evaluate and improve the system.

### How to submit feedback

1. Click **✓ Accurate** if the response correctly identified and applied the relevant policy provisions, or **⚠ Needs Work** if there were errors, omissions, or misapplications.
2. Optionally, type a comment in the text area explaining what was correct or incorrect. Be as specific as possible — citing the instrument and provision that was mishandled is most useful.
3. Click **Submit Feedback** or press **Enter** in the comment box.

A confirmation message will appear once feedback is saved.

### What makes good feedback

- **Specific** — "The response missed that DAOD 5029-2 requires written notice before corrective action" is more useful than "incomplete."
- **Referenced** — Cite the instrument and section that was handled incorrectly.
- **Balanced** — Note what was right as well as what was wrong. This helps distinguish systematic gaps from one-off retrieval failures.

### Exporting feedback for analysis

Feedback can be exported by an administrator via the API:

```
GET http://localhost:8000/api/feedback/export
```

This returns a JSON array of all feedback records, suitable for offline analysis.

---

## 9. Asking Good Questions

### Questions the system handles well

- Questions with a clear HR policy dimension that maps to one or more of the eight domains.
- Questions that reference a specific situation (position type, employee group, circumstance) rather than abstract queries.
- Multi-domain questions, as long as the domain connections are explicit in the question.

**Examples:**

> What are the bilingualism requirements for staffing an AS-04 position at a bilingual imperative BBB/BBB level in the NCR?

> An indeterminate employee has been on medical leave for six months. What are the employer's obligations under the duty to accommodate, and at what point does workforce adjustment become relevant?

> What process must management follow before reclassifying a PM-03 position to IS-03?

### Questions the system handles less well

- **Highly contextual questions** requiring knowledge of specific collective agreement articles without specifying the group. Specify the occupational group (e.g., "PA group employee" or "AS-04").
- **Questions about pay rates or specific dollar amounts.** The system can identify the applicable directive but does not calculate amounts.
- **Questions about internal DND administrative processes** not covered by a DAOD (e.g., specific HR system workflows).
- **Questions requiring FPSLREB or court decision interpretation.** The system can retrieve the decisions database but cannot reliably summarize case law.
- **Out-of-scope questions.** If your question is not about civilian HR policy (e.g., it concerns military members, procurement, or security clearances), the system will say so rather than confabulate an answer.

### Tips for better results

| Tip | Example |
|-----|---------|
| **Specify the employee group** | "...for a PM-06 EX-minus-1 position..." |
| **Name the relevant context** | "...in the context of a workforce adjustment situation..." |
| **Ask about one scenario at a time** | Split complex multi-part situations into separate questions |
| **Name the domain if you know it** | "From a labour relations perspective, what are..." |
| **Be explicit about cross-domain questions** | "This involves both official languages requirements and staffing — what do both sets of rules say?" |

---

## 10. Known Limitations

### Policy corpus coverage

The system covers 117 deduplicated instruments across eight HR policy domains. Instruments not in the registry will not be retrieved or cited. Gaps include:

- Most departmental operational procedures (HR system guides, forms, templates)
- Treasury Board Secretariat interpretive guidance letters and Q&As
- Informal OCHRO guidance and FAQ documents
- FPSLREB and Federal Court decisions (the database is accessible but not comprehensively indexed)
- Some newer instruments published after the registry was last updated

### Retrieval limitations

- Policy content is fetched from public GC websites during your session. If a website is unavailable or slow, the agent will fall back to its cache (up to 7 days old for most instruments, 30 days for legislation and collective agreements). If no cache exists, that instrument will be marked as failed and the response will note the gap.
- Each specialist fetches up to 5 instruments per query to keep processing time and context window usage manageable. For agents with many instruments (e.g., Classification & Compensation has 30), not all instruments will be fetched for every query. The agent selects the most likely relevant ones; if your question requires a specific instrument that was not fetched, try asking a more targeted question that names the instrument explicitly.
- The system does not read PDFs. Some collective agreements and older DAODs are only available as PDFs; these will fail to retrieve content even if the URL is valid.

### Response quality

- The model (Qwen3.5:35b) produces policy analysis that is generally coherent and well-cited, but it can:
  - Misattribute a provision to the wrong section of an instrument
  - Conflate similar provisions across different instruments
  - Miss a conflict or exception that a trained HR advisor would recognize
  - Occasionally produce JSON parsing errors that result in a lower-quality fallback response
- Confidence indicators (high / medium / low) are the model's self-assessment and are not independently verified. Treat all responses as medium confidence until reviewed by a specialist.

### Concurrency

This system is designed for single-user or small-group pilot use. It has not been load-tested for concurrent sessions.

---

## 11. Troubleshooting

### The page does not load

- Confirm the server is running: you should see `Uvicorn running on http://0.0.0.0:8000` in the terminal.
- Check the port is not blocked by a firewall: `sudo ufw status` (if UFW is enabled, allow port 8000).
- Try `http://127.0.0.1:8000` instead of `localhost`.

### "Ollama connection failed" warning at startup

- Run `ollama serve` to start the Ollama server.
- Verify the model is available: `ollama list`. If `qwen3.5:35b` is not listed, run `ollama pull qwen3.5:35b`.
- Verify Ollama is listening: `curl http://localhost:11434/api/tags` should return a JSON response.

### The response takes very long or never arrives

- The first response after startup is slower as the model is loaded into VRAM. Subsequent responses are faster.
- If the system has stalled mid-response, use the OpenCode watcher script to detect and recover from stalls automatically (see `scripts/opencode_watcher.py`).
- Check the server terminal for error messages. A Python traceback indicates an application error.
- If no response arrives after 3 minutes, refresh the page and resubmit your question. The WebSocket will reconnect automatically.

### Agent status shows all errors (amber dots)

- This usually indicates a network issue preventing the fetch engine from reaching GC websites.
- Check your internet connection.
- Check if the GC websites are reachable: `curl -I https://www.tbs-sct.canada.ca` should return a 200 or 301 status.
- If you are behind a proxy, ensure the proxy settings are configured in your environment (`HTTP_PROXY`, `HTTPS_PROXY` environment variables).

### Response confidence is consistently "low"

- Low confidence often means the agents could not retrieve policy content (retrieval failures noted in the response), or the query is genuinely outside the corpus.
- Check the server logs for `WARNING: Fetch failed` messages.
- Try a question on a well-covered domain (e.g., "What is the process for staffing a term position?") to verify baseline functionality.

### Feedback does not submit

- Check the browser console (F12 → Console) for error messages.
- Verify the server is still running.
- Ensure you have selected either "Accurate" or "Needs Work" before clicking Submit.

### Database errors at startup

- The database is created automatically at `data/hr_policy_agent.db` on first run. Ensure the `data/` directory exists and is writable.
- If the database is corrupted, delete `data/hr_policy_agent.db` and restart the server. You will lose stored query history and feedback.

---

## Appendix A — API Endpoints

For administrators and developers:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the GUI |
| `GET` | `/api/health` | System health status (Ollama, database) |
| `GET` | `/api/agents` | List all agents with metadata |
| `GET` | `/api/queries` | Recent query history (`?limit=50`) |
| `GET` | `/api/queries/{query_id}` | Full record for one query including agent responses |
| `POST` | `/api/feedback` | Submit feedback programmatically |
| `GET` | `/api/feedback/export` | Export all feedback as JSON |
| `WS` | `/ws` | WebSocket endpoint for real-time query processing |

---

## Appendix B — Policy Domains and Instrument Counts

| Agent | Domain | Instruments |
|-------|--------|-------------|
| Staffing & Recruitment | Staffing and recruitment; Student and youth programs | 27 |
| Classification & Compensation | Classification; Compensation and benefits | 30 |
| Labour Relations | Labour relations and workplace management | 11 |
| Learning & Performance | Learning, training and development; Performance management | 10 |
| Equity, Diversity & Inclusion | Diversity, equity and inclusion; Employment equity and accessibility | 10 |
| Health, Safety & Wellness | Occupational health and safety | 10 |
| Official Languages | Official languages | 10 |
| Values, Ethics & HR Governance | Values and ethics; Conflict of interest; HR governance; Executive services; Leave | 27 |

Some instruments appear in multiple domains (e.g., the Financial Administration Act is relevant to both Staffing and Classification). The registry stores each instrument once and maps it to all relevant agents. Total unique instruments: 117.

---

*This document covers system version 0.1.0 (April 2026 pilot).*
*For questions about this system, contact the AI Solutions Developer, ADM(HR-Civ).*
