#!/bin/bash
# =============================================================
# LeaveNoteForClaude.command — Leave a message for tomorrow's
# daily monitor run. Claude reads it at 08:00 and responds in
# the daily report.
# =============================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
NOTES_FILE="$PROJECT_DIR/data/monitoring/user_notes.md"

echo ""
echo "=================================================="
echo "  Leave a note for Claude"
echo "  Claude reads this at 08:00 and responds"
echo "  in tomorrow's daily report."
echo "=================================================="
echo ""
echo "Your note (press Enter twice when done):"
echo ""

# Read multi-line input until double Enter
NOTE=""
while IFS= read -r line; do
    [[ -z "$line" && -z "$NOTE" ]] && continue
    [[ -z "$line" ]] && break
    NOTE="$NOTE$line\n"
done

if [[ -z "$NOTE" ]]; then
    echo "No note entered. Exiting."
    read -p "Press Enter to close..."
    exit 0
fi

# Append to notes file with timestamp
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M UTC')
echo "" >> "$NOTES_FILE"
echo "$TIMESTAMP: $(printf '%b' "$NOTE")" >> "$NOTES_FILE"

echo ""
echo "✓ Note saved. Claude will read it at 08:00 tomorrow."
echo ""
echo "To read previous reports:"
echo "  open $PROJECT_DIR/data/monitoring/"
echo ""
read -p "Press Enter to close..."
