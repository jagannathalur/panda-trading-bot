#!/usr/bin/env bash
# Promote strategy through the validation pipeline
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a; source "$ROOT_DIR/.env"; set +a
fi

STRATEGY="${1:-${FREQTRADE_STRATEGY:-GridTrendV2}}"
TARGET_STATE="${2:-backtest_passed}"

echo "=== Strategy Promotion: $STRATEGY -> $TARGET_STATE ==="
echo ""
echo "IMPORTANT: Promotion does NOT enable real trading."
echo "Real trading requires separate operator action via mode_control."
echo ""

# Run the promotion workflow
python3 -c "
from custom_app.promotion import StrategyRegistry, PromotionState
import sys

registry = StrategyRegistry('$ROOT_DIR/data/strategy_registry.json')
pipeline = registry.register('$STRATEGY')
print(f'Current state: {pipeline.current_state}')

target = PromotionState('$TARGET_STATE')
try:
    pipeline.advance(target, notes='Promoted via promote_strategy.sh')
    print(f'Promoted to: {pipeline.current_state}')
    registry._save()
except ValueError as e:
    print(f'ERROR: {e}')
    sys.exit(1)
"
