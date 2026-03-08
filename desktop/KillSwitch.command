#!/bin/bash
# =============================================================
# KillSwitch.command — Emergency stop. Double-click to halt.
# Stops all trading immediately. Does NOT close open positions.
# To close positions: use Freqtrade Web UI → Force Exit All.
# =============================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load credentials from .env
ENV_FILE="$PROJECT_DIR/.env"
[[ -f "$ENV_FILE" ]] && { set -a; source "$ENV_FILE"; set +a; }

FT_USER="${FREQTRADE_API_USERNAME:-freqtrade}"
FT_PASS="${FREQTRADE_API_PASSWORD:-change-me}"
FT_URL="http://127.0.0.1:8081"

echo "=================================================="
echo "  ⚠️  PANDA BOT — EMERGENCY KILL SWITCH"
echo "=================================================="
echo ""
echo "This will STOP all new trades immediately."
echo "Existing open positions will remain open."
echo ""
read -p "Type STOP to confirm: " confirm

if [[ "$confirm" != "STOP" ]]; then
    echo "Cancelled — bot continues running."
    read -p "Press Enter to close..."
    exit 0
fi

echo ""
echo "Halting bot..."

# Stop trading via Freqtrade Web UI API
STOP_RESULT=$(curl -sf -X POST "$FT_URL/api/v1/stop" \
    -u "$FT_USER:$FT_PASS" 2>/dev/null || echo "unreachable")
echo "Freqtrade Web UI stop: $STOP_RESULT"

# Also arm our custom risk engine kill switch if dashboard is running
KILL_RESULT=$(curl -sf -X POST "http://127.0.0.1:8080/api/kill-switch" \
    -H "Content-Type: application/json" \
    -d "{\"reason\": \"Manual kill switch via desktop shortcut\", \"operator\": \"desktop\"}" \
    2>/dev/null || echo "dashboard unreachable")
echo "Risk engine kill: $KILL_RESULT"

# Hard stop: kill the OS process if API is unreachable
if [[ "$STOP_RESULT" == "unreachable" ]]; then
    echo "API unreachable — sending SIGTERM to freqtrade process..."
    pkill -SIGTERM -f "freqtrade trade" 2>/dev/null && echo "Process stopped." || echo "No process found."
fi

echo ""
echo "=================================================="
echo "  KILL SWITCH ARMED"
echo "  All new trades: HALTED"
echo "  Open positions: check Freqtrade Web UI to manage"
echo "  To restart:     LaunchPandaBot.command"
echo "=================================================="
echo ""
read -p "Press Enter to close..."
