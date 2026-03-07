#!/bin/bash
# =============================================================
# run_daily_monitor.sh — Cron wrapper for daily_monitor.py
# Called every morning at 08:00 by launchd/cron.
# =============================================================

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment
ENV_FILE="$PROJECT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
fi

# Ensure monitoring log dir exists
mkdir -p "$PROJECT_DIR/data/monitoring"

# Run the Python monitor
LOG="$PROJECT_DIR/data/monitoring/cron.log"
echo "" >> "$LOG"
echo "=== $(date -u '+%Y-%m-%d %H:%M UTC') ===" >> "$LOG"

python3 "$SCRIPT_DIR/daily_monitor.py" 2>&1 | tee -a "$LOG"
EXIT_CODE=${PIPESTATUS[0]}

# If CRITICAL (exit 2), also send a more aggressive macOS alert
if [[ "$EXIT_CODE" -eq 2 ]]; then
    osascript -e 'display dialog "🚨 CRITICAL: Panda Bot needs immediate attention!\n\nCheck ~/Desktop or data/monitoring/ for today'\''s report." buttons {"Open Reports Folder", "OK"} default button "Open Reports Folder"' \
    && open "$PROJECT_DIR/data/monitoring/" || true
fi

exit "$EXIT_CODE"
