#!/usr/bin/env bash
# Run bot in REAL trading mode — requires all operator gates
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a; source "$ROOT_DIR/.env"; set +a
fi

# Verify all gates before starting
bash "$SCRIPT_DIR/verify_mode_lock.sh" || exit 1

echo ""
echo "=== REAL TRADING MODE — REAL CAPITAL AT RISK ==="
echo "All operator gates passed. Starting Freqtrade in live mode..."
echo ""

cd "$ROOT_DIR/freqtrade"
python3 -m freqtrade trade \
  --config "$ROOT_DIR/configs/base.yaml" \
  --config "$ROOT_DIR/configs/real.yaml" \
  --strategy "${FREQTRADE_STRATEGY:-GridTrendV1}" \
  --userdir "$ROOT_DIR/user_data" \
  --logfile "$ROOT_DIR/logs/real.log"
