#!/usr/bin/env bash
# Run bot in paper/dry-run mode (SAFE DEFAULT)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env if present
if [ -f "$ROOT_DIR/.env" ]; then
  set -a; source "$ROOT_DIR/.env"; set +a
fi

# Enforce paper mode
export TRADING_MODE=paper
export DRY_RUN=true

echo "=== PAPER TRADING MODE — No real capital at risk ==="
echo "Starting Freqtrade in dry-run mode..."

cd "$ROOT_DIR/freqtrade"
python3 -m freqtrade trade \
  --config "$ROOT_DIR/configs/base.yaml" \
  --config "$ROOT_DIR/configs/paper.yaml" \
  --strategy "${FREQTRADE_STRATEGY:-GridTrendV1}" \
  --userdir "$ROOT_DIR/user_data" \
  --logfile "$ROOT_DIR/logs/paper.log"
