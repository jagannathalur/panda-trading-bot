#!/usr/bin/env bash
# EMERGENCY: Flatten all open positions immediately
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a; source "$ROOT_DIR/.env"; set +a
fi

echo "=== EMERGENCY FLATTEN ==="
echo "Timestamp: $(date -u)"
echo "Closing all open positions via Freqtrade API..."

python3 -c "
from custom_app.risk_layer.kill_switch import trigger_emergency_flatten
import os, json

url = os.environ.get('FREQTRADE_API_URL', 'http://127.0.0.1:8081')
username = os.environ.get('FREQTRADE_API_USERNAME', 'freqtrade')
password = os.environ.get('FREQTRADE_API_PASSWORD', '')

results = trigger_emergency_flatten(url, username, password)
print(json.dumps(results, indent=2))
"
echo "Emergency flatten completed. Check audit log for details."
