#!/usr/bin/env bash
# 0xClaw startup script
# Usage: ./scripts/start.sh [--logs]
# Requires: conda env '0xclaw' (conda create -n 0xclaw python=3.11)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Activate conda env if not already in it
if [[ "${CONDA_DEFAULT_ENV:-}" != "0xclaw" ]]; then
  echo "Activating conda env '0xclaw'..."
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate 0xclaw
fi

# Load .env if it exists
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  echo "Loading .env..."
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
else
  echo "Warning: .env not found. Copy .env.example to .env and fill in your API keys."
  echo "  cp .env.example .env"
fi

# Validate required keys
MISSING=()
[[ -z "${FLOCK_API_KEY:-}" ]] && MISSING+=("FLOCK_API_KEY")


if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo ""
  echo "WARNING: The following API keys are not set:"
  for key in "${MISSING[@]}"; do
    echo "  - $key"
  done
  echo ""
  echo "Some features may not work. Set them in .env to enable full functionality."
  echo ""
fi

# Verify integrated runtime is present
if [[ ! -d "$PROJECT_ROOT/0xclaw/runtime" ]]; then
  echo "Error: integrated runtime not found at 0xclaw/runtime"
  exit 1
fi

# Run 0xClaw
cd "$PROJECT_ROOT"
echo ""
echo "Starting 0xClaw..."
echo ""
0xclaw "$@"
