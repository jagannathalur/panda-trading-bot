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
DB_URL="sqlite:///$ROOT_DIR/tradesv3.dryrun.sqlite"

echo "=== PAPER TRADING MODE — No real capital at risk ==="
echo "Starting Freqtrade in dry-run mode..."
echo "Using trades DB: $DB_URL"

cd "$ROOT_DIR/freqtrade"
python3 -m freqtrade trade \
  --config "$ROOT_DIR/configs/base.yaml" \
  --config "$ROOT_DIR/configs/paper.yaml" \
  --db-url "$DB_URL" \
  --strategy "${FREQTRADE_STRATEGY:-GridTrendV2}" \
  --userdir "$ROOT_DIR/user_data" \
  --logfile "$ROOT_DIR/logs/paper.log"
