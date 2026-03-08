#!/usr/bin/env bash
# Run deterministic backtest
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a; source "$ROOT_DIR/.env"; set +a
fi

STRATEGY="${FREQTRADE_STRATEGY:-GridTrendV2}"
TIMERANGE="${BACKTEST_TIMERANGE:-20230101-20231231}"

echo "=== Running Backtest: $STRATEGY | $TIMERANGE ==="

cd "$ROOT_DIR/freqtrade"
python3 -m freqtrade backtesting \
  --strategy "$STRATEGY" \
  --timerange "$TIMERANGE" \
  --config "$ROOT_DIR/configs/base.yaml" \
  --config "$ROOT_DIR/configs/paper.yaml" \
  --userdir "$ROOT_DIR/user_data" \
  --export trades \
  --export-filename "$ROOT_DIR/data/backtest_${STRATEGY}_$(date +%Y%m%d).json"

echo "Backtest complete. Results in data/backtest_*.json"
