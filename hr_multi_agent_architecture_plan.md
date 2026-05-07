# Technical Specification: Heterogeneous Multi-Agent Refactor (Ollama/Gemma 4)

## 1. System Overview
**Hardware Environment:** ARM Ampere (Linux)
**Architecture Pattern:** "Swap and Swarm" (Phase-based Tiered Execution)

The objective is to optimize the inference pipeline by separating high-level strategic reasoning from data-intensive research tasks. This architecture minimizes memory bus contention and avoids the overhead issues associated with complex batching engines by using explicit model swapping and parallelized small-model streams.

> [!NOTE]
> **Developer Note:** This plan assumes an existing codebase for query routing, deterministic parsing, and external library fetching. The focus is strictly on refactoring the **LLM Orchestration Layer** and **Model Lifecycle Management**.

---

## 2. Model Tier Definitions

### Tier 1: The Orchestrator & Synthesizer
* **Model:** `gemma4:31b` (Dense)
* **Role:** * **Phase 1:** Intent classification and functional area delegation.
    * **Phase 3:** Final synthesis of multiple JSON research payloads into natural language.
* **Constraint:** Requires the high reasoning stability of the dense 31B model to prevent policy drift.

### Tier 2: The Research Sub-Agents
* **Model:** `gemma4:e4b` (Dense)
* **Role:** * **Phase 2:** High-speed parallel reading of policy documents and structured JSON extraction.
* **Context Window Cap:** **32,768 tokens**. 
* **Rationale:** Capping the context at 32k ensures that multiple parallel KV caches can fit into RAM simultaneously on the Ampere hardware without triggering OOM (Out-of-Memory) throttles.

---

## 3. The "Swap and Swarm" Execution Workflow

The implementation must strictly manage the model lifecycle to ensure only one model tier is resident in memory at a time.

### Phase 1: Strategic Delegation (Orchestrator)
1.  **Load:** `gemma4:31b`.
2.  **Process:** Analyze user HR query.
3.  **Output:** JSON/List of functional specialties and specific research tasks.
4.  **Lifecycle:** Use `keep_alive: 0` in the API request to force immediate unloading of the 31B weights upon completion.

### Phase 2: Parallel Swarm (Sub-Agents)
1.  **Load:** `gemma4:e4b`.
2.  **Concurrency:** Fire $N$ sub-agent requests as **asynchronous parallel calls** (e.g., using `asyncio.gather` in Python).
3.  **API Parameters:**
    * `model`: `gemma4:e4b`
    * `num_ctx`: `32768`
    * `format`: `json`
    * `options`: `{"num_predict": -1, "temperature": 0}` (for deterministic extraction)
4.  **Lifecycle:** Use `keep_alive: 0` on the final sub-agent call to clear memory for the return of the Orchestrator.

### Phase 3: Final Synthesis (Orchestrator)
1.  **Reload:** `gemma4:31b`.
2.  **Input:** Original query + validated JSON payloads from sub-agents.
3.  **Process:** Synthesize findings into a structured HR response.
4.  **Lifecycle:** Final output to user.

---

## 4. Infrastructure & Environment Setup
The following environment variables must be configured on the host to support this architecture:

* `OLLAMA_MAX_LOADED_MODELS=1`: Prevents memory fragmentation by ensuring Tier 1 and Tier 2 do not overlap.
* `OLLAMA_NUM_PARALLEL=8`: Enables concurrent processing of multiple E4B streams.

---

## 5. Implementation Guidelines for Refactoring
* **Statelessness:** Ensure sub-agent calls do not maintain history/conversation buffers. This allows the system to utilize **Atomic Prefix Caching** for shared policy snippets.
* **Parallelization:** Refactor sequential loops into asynchronous tasks. The "Research Phase" total time should ideally equal `Max(Time of longest sub-agent task) + Swap Penalty`.
* **Context Management:** If an HR document exceeds the 32k limit, the sub-agent should prioritize extracting relevant segments or flag the task for high-precision processing.
* **Verification:** Maintain the existing **Deterministic Parser** between Phase 2 and Phase 3 to validate JSON structure before synthesis.
