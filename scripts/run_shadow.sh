#!/usr/bin/env bash
# Run paper shadow mode — minimum 72h required
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a; source "$ROOT_DIR/.env"; set +a
fi

MIN_HOURS="${SHADOW_MIN_DURATION_HOURS:-72}"
echo "=== Shadow Run — Minimum ${MIN_HOURS}h required ==="
echo "Running paper shadow alongside live prices..."
echo "Start time: $(date -u)"

# Shadow = paper run in parallel with live strategy
# Records paper fills vs live prices for comparison
export TRADING_MODE=paper
bash "$SCRIPT_DIR/run_paper.sh"
