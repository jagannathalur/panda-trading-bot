#!/bin/bash
# =============================================================
# LaunchPandaBot.command — Double-click to start everything.
# Starts: Freqtrade bot (futures paper) + custom dashboard
# Opens:  FreqUI (8081) + Ops Dashboard (8080) in browser
# =============================================================

set -euo pipefail

# Resolve project root (parent of desktop/)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=================================================="
echo "  Panda Trading Bot — Launch"
echo "=================================================="
echo "Project: $PROJECT_DIR"
echo ""

# Load .env
ENV_FILE="$PROJECT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    echo "Run: cp .env.example .env && scripts/setup_secrets.sh"
    read -p "Press Enter to close..."
    exit 1
fi
set -a; source "$ENV_FILE"; set +a

# Kill any existing bot instances cleanly
echo "Stopping any existing bot processes..."
pkill -f "freqtrade trade" 2>/dev/null || true
pkill -f "uvicorn custom_app.dashboard" 2>/dev/null || true
lsof -ti:8081 | xargs kill -9 2>/dev/null || true
lsof -ti:8080 | xargs kill -9 2>/dev/null || true
sleep 2

cd "$PROJECT_DIR"

# Pick strategy and config based on TRADING_MODE env
STRATEGY="${FREQTRADE_STRATEGY:-GridTrendV2}"
if [[ "${TRADING_MODE:-paper}" == "real" ]]; then
    CONFIG_FLAGS="--config configs/base.json --config configs/real.json"
    echo "⚠️  REAL TRADING MODE — using real capital"
else
    CONFIG_FLAGS="--config configs/base.json --config configs/futures_paper.json"
    echo "Paper mode — simulated capital only"
fi

# Open Terminal tabs via AppleScript
osascript <<EOF
tell application "Terminal"
    activate

    -- Tab 1: Freqtrade bot
    set botTab to do script "cd '$PROJECT_DIR' && source .env && \\
        export PYTHONPATH='$PROJECT_DIR' && \\
        echo '--- Freqtrade Bot ($STRATEGY) ---' && \\
        freqtrade trade $CONFIG_FLAGS --strategy $STRATEGY --userdir user_data --logfile user_data/logs/paper.log; \\
        echo 'Bot exited — press Enter to close'; read"

    -- Tab 2: Custom ops dashboard
    tell application "System Events" to keystroke "t" using command down
    delay 0.3
    do script "cd '$PROJECT_DIR' && source .env && \\
        echo '--- Panda Ops Dashboard (port 8080) ---' && \\
        uvicorn custom_app.dashboard.app:app --host 0.0.0.0 --port 8080 --reload; \\
        echo 'Dashboard exited — press Enter to close'; read" in front window

    -- Tab 3: Live log
    tell application "System Events" to keystroke "t" using command down
    delay 0.3
    do script "cd '$PROJECT_DIR' && \\
        echo '--- Live Bot Log ---' && \\
        sleep 5 && tail -f user_data/logs/paper.log" in front window
end tell
EOF

# Wait for bot API to be ready
echo ""
echo "Waiting for bot to start..."
for i in $(seq 1 20); do
    if curl -sf "http://127.0.0.1:8081/api/v1/ping" -u "${FREQTRADE_API_USERNAME:-freqtrade}:${FREQTRADE_API_PASSWORD:-change-me}" > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Start trading
curl -sf -X POST "http://127.0.0.1:8081/api/v1/start" \
    -u "${FREQTRADE_API_USERNAME:-freqtrade}:${FREQTRADE_API_PASSWORD:-change-me}" \
    > /dev/null 2>&1 && echo "Bot started." || echo "Warning: Could not auto-start bot — start manually in FreqUI"

# Open dashboards in browser
sleep 2
open "http://127.0.0.1:8081/ui/" 2>/dev/null || true
open "http://127.0.0.1:8080" 2>/dev/null || true

echo ""
echo "=================================================="
echo "  LAUNCHED"
echo "  FreqUI:         http://127.0.0.1:8081/ui/"
echo "  Ops Dashboard:  http://127.0.0.1:8080"
echo "  Login:          freqtrade / change-me"
echo "=================================================="
echo ""
read -p "Press Enter to close this window..."
