#!/usr/bin/env bash
# Verify 0xClaw setup and API key connectivity
# Requires: conda env '0xclaw'
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Activate conda env if not already in it
if [[ "${CONDA_DEFAULT_ENV:-}" != "0xclaw" ]]; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate 0xclaw
fi

# Load .env
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a; source "$PROJECT_ROOT/.env"; set +a
fi

echo "=== 0xClaw Setup Verification ==="
echo ""

# Check integrated runtime import
echo -n "integrated runtime import... "
if python -c "import sys; from pathlib import Path; root=Path('$PROJECT_ROOT'); sys.path.insert(0, str(root / '0xclaw')); import runtime; print('OK v' + runtime.__version__)" 2>/dev/null; then
  :
else
  echo "FAIL — ensure 0xclaw/runtime exists and dependencies are installed"
fi

# Check workspace files
echo ""
echo "Workspace files:"
for f in SOUL.md AGENTS.md HEARTBEAT.md memory/MEMORY.md; do
  if [[ -f "$PROJECT_ROOT/workspace/$f" ]]; then
    echo "  ✓ workspace/$f"
  else
    echo "  ✗ workspace/$f MISSING"
  fi
done

echo ""
echo "Skills:"
for skill in hackathon-research idea planner coder tester doc; do
  if [[ -f "$PROJECT_ROOT/workspace/skills/$skill/SKILL.md" ]]; then
    echo "  ✓ skills/$skill/SKILL.md"
  else
    echo "  ✗ skills/$skill/SKILL.md MISSING"
  fi
done

# Check API keys
echo ""
echo "API Keys:"
check_key() {
  local name=$1
  local value=${2:-}
  if [[ -n "$value" ]]; then
    echo "  ✓ $name (${value:0:8}...)"
  else
    echo "  ✗ $name NOT SET"
  fi
}
check_key "FLOCK_API_KEY"   "${FLOCK_API_KEY:-}"
check_key "ZAI_API_KEY"     "${ZAI_API_KEY:-}"

# Test Z.ai connectivity
echo ""
echo "API Connectivity:"
if [[ -n "${ZAI_API_KEY:-}" ]]; then
  echo -n "  Z.ai GLM-4.7... "
  RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "https://api.z.ai/api/paas/v4/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $ZAI_API_KEY" \
    -d '{"model":"glm-4.7","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' \
    --max-time 10 2>/dev/null || echo "000")
  if [[ "$RESPONSE" == "200" ]]; then
    echo "✓ reachable (200)"
  else
    echo "✗ HTTP $RESPONSE"
  fi
else
  echo "  Zhipu GLM-5... skipped (no key)"
fi

# Test FLock connectivity
if [[ -n "${FLOCK_API_KEY:-}" ]]; then
  echo -n "  FLock.io... "
  RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "https://api.flock.io/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "x-litellm-api-key: $FLOCK_API_KEY" \
    -d '{"model":"qwen3-30b-a3b-instruct-2507","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' \
    --max-time 10 2>/dev/null || echo "000")
  if [[ "$RESPONSE" == "200" ]]; then
    echo "✓ reachable (200)"
  else
    echo "✗ HTTP $RESPONSE"
  fi
else
  echo "  FLock.io... skipped (no key)"
fi

echo ""
echo "=== Verification Complete ==="
echo "Run './scripts/start.sh' to launch 0xClaw"
