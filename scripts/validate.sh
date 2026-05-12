#!/usr/bin/env bash
# Validation loop for the DND HR-Civ Policy Advisory System.
# Run after any code change before declaring a task complete.
# Exit codes: 0 = all checks passed, non-zero = one or more failures.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILURES=0
LAYER=""

pass() { echo -e "  ${GREEN}PASS${NC} $1"; }
fail() { echo -e "  ${RED}FAIL${NC} $1"; FAILURES=$((FAILURES + 1)); }
warn() { echo -e "  ${YELLOW}WARN${NC} $1"; }
header() { LAYER="$1"; echo -e "\n[L${2}] ${1}"; }

# ── Layer 0: Syntax ──────────────────────────────────────────────────────────
header "Syntax" 0
PY_FILES=$(find src tests scripts -name "*.py" 2>/dev/null)
SYNTAX_ERRORS=0
for f in $PY_FILES; do
    if ! python3 -m py_compile "$f" 2>/dev/null; then
        fail "Syntax error: $f"
        SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
    fi
done
if [ "$SYNTAX_ERRORS" -eq 0 ]; then
    pass "All Python files compile cleanly"
fi

# ── Layer 1: Architecture boundaries ────────────────────────────────────────
header "Architecture boundaries" 1

# Rule: agents must not use httpx directly (must go through src/fetch/engine.py)
# llm/client.py is allowed to use httpx — it IS the HTTP layer for Ollama.
if grep -rn "import httpx\|httpx\.get\|httpx\.post\|httpx\.AsyncClient" src/agents/ src/api/ 2>/dev/null | grep -v "^Binary"; then
    fail "Direct httpx usage in agents/api — route through src/fetch/engine.py"
else
    pass "No httpx bypass in agents/api"
fi

# Rule: no raw aiosqlite.connect outside src/data/db.py
SQLITE_VIOLATIONS=$(grep -rn "aiosqlite\.connect" src/ --include="*.py" | grep -v "src/data/db.py" || true)
if [ -n "$SQLITE_VIOLATIONS" ]; then
    fail "Direct aiosqlite.connect outside db.py:\n$SQLITE_VIOLATIONS"
else
    pass "No SQLite bypass outside db.py"
fi

# Rule: no raw ollama client calls outside src/llm/client.py
OLLAMA_VIOLATIONS=$(grep -rn "import ollama\|ollama\.chat\|ollama\.generate" src/ --include="*.py" | grep -v "src/llm/client.py" || true)
if [ -n "$OLLAMA_VIOLATIONS" ]; then
    fail "Direct ollama usage outside llm/client.py:\n$OLLAMA_VIOLATIONS"
else
    pass "No ollama bypass outside llm/client.py"
fi

# Rule: config.yaml must be loaded via get_config(), not opened raw.
# (Other YAML files such as selectors.yaml are fine to load directly.)
YAML_VIOLATIONS=$(grep -rn "open.*config\.yaml\|yaml.*load.*config" src/ --include="*.py" | grep -v "src/config.py" || true)
if [ -n "$YAML_VIOLATIONS" ]; then
    fail "Direct config.yaml read outside src/config.py:\n$YAML_VIOLATIONS"
else
    pass "No config.yaml bypass outside config.py"
fi

# ── Layer 2: Policy registry integrity ──────────────────────────────────────
header "Policy registry integrity" 2
REGISTRY="src/data/policy_registry.json"
VALID_AGENT_IDS="staffing classification labour learning equity ohs languages governance"

python3 - <<'PYEOF'
import json, sys

registry_path = "src/data/policy_registry.json"
valid_agents = {"staffing","classification","labour","learning","equity","ohs","languages","governance"}
errors = []

try:
    with open(registry_path) as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    print(f"FAIL: Registry is not valid JSON: {e}")
    sys.exit(1)

instruments = data if isinstance(data, list) else data.get("instruments", [])
for i, inst in enumerate(instruments):
    for field in ("id","title","type","url","agent_ids"):
        if field not in inst:
            errors.append(f"  instrument[{i}] missing field '{field}'")
    if "url" in inst and not inst["url"].startswith("http"):
        errors.append(f"  instrument[{i}] ({inst.get('id','?')}): url does not start with http")
    for aid in inst.get("agent_ids", []):
        if aid not in valid_agents:
            errors.append(f"  instrument[{i}] ({inst.get('id','?')}): unknown agent_id '{aid}'")

if errors:
    for e in errors:
        print(f"FAIL: {e}")
    sys.exit(1)
else:
    print(f"PASS: Registry valid — {len(instruments)} instruments, all agent_ids known")
PYEOF
[ $? -ne 0 ] && FAILURES=$((FAILURES + 1))

# ── Layer 3: Schema imports ──────────────────────────────────────────────────
header "Schema imports" 3
if python3 -c "from src.models.schemas import PolicyInstrument, SpecialistResponse, OrchestratorResponse, QueryRecord, RetrievalStatus" 2>&1; then
    pass "All canonical schema classes import cleanly"
else
    fail "Schema import failed"
    FAILURES=$((FAILURES + 1))
fi

# ── Layer 4: Unit and integration tests ─────────────────────────────────────
header "Test suite" 4
if python3 -m pytest tests/ -q --tb=short 2>&1; then
    pass "All tests passed"
else
    fail "Test suite failures — see output above"
    FAILURES=$((FAILURES + 1))
fi

# ── Layer 5: Epistemic-humility spot-check (agent prompt audit) ──────────────
header "Agent prompt integrity" 5
PROMPT_FILES=$(find src/agents/prompts -name "*.py" ! -name "__init__.py" 2>/dev/null)
HUMILITY_MISSING=0
for f in $PROMPT_FILES; do
    if ! grep -qi "do not\|must not\|cannot\|if.*not.*found\|unable to\|insufficient\|no.*information\|explicit" "$f" 2>/dev/null; then
        warn "$f: no epistemic-humility language detected — review prompt"
        HUMILITY_MISSING=$((HUMILITY_MISSING + 1))
    fi
done
if [ "$HUMILITY_MISSING" -eq 0 ]; then
    pass "All agent prompts contain epistemic-humility language"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
if [ "$FAILURES" -eq 0 ]; then
    echo -e "${GREEN}All validation layers passed.${NC}"
    exit 0
else
    echo -e "${RED}${FAILURES} validation layer(s) failed. Do not commit until resolved.${NC}"
    exit 1
fi
