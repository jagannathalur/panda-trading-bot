#!/usr/bin/env bash
# Run walk-forward validation (rolling backtest windows)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a; source "$ROOT_DIR/.env"; set +a
fi

STRATEGY="${FREQTRADE_STRATEGY:-GridTrendV2}"
WINDOWS="${WALK_FORWARD_WINDOWS:-5}"

echo "=== Walk-Forward Validation: $STRATEGY | $WINDOWS windows ==="

# Run rolling walk-forward via Freqtrade's lookahead-analysis or hyperopt
# This is a simplified version — extend per strategy needs
cd "$ROOT_DIR/freqtrade"
python3 -m freqtrade lookahead-analysis \
  --strategy "$STRATEGY" \
  --config "$ROOT_DIR/configs/base.yaml" \
  --config "$ROOT_DIR/configs/paper.yaml" \
  --userdir "$ROOT_DIR/user_data" \
  --timerange "${BACKTEST_TIMERANGE:-20230101-20231231}"

echo "Walk-forward complete."
