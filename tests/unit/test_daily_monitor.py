"""
Tests for scripts/daily_monitor.py

All external calls (Anthropic API, Freqtrade API) are mocked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path so we can import the script
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.append(str(_PROJECT_ROOT))

import scripts.daily_monitor as dm


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _make_profit(**overrides) -> dict:
    base = {
        "total_usdt": 12.5,
        "total_pct": 1.25,
        "win_rate": 0.58,
        "winning_trades": 29,
        "losing_trades": 21,
        "profit_factor": 1.35,
        "max_drawdown": 0.045,
        "trade_count": 50,
        "best_pair": "BTC/USDT",
        "worst_pair": "SOL/USDT",
        "avg_duration": "4:23:00",
    }
    base.update(overrides)
    return base


def _make_data(**overrides) -> dict:
    base = {
        "bot_online": True,
        "state": "running",
        "strategy": "GridTrendV2",
        "trading_mode": "futures",
        "dry_run": True,
        "exchange": "bybit",
        "balance_usdt": 10100.0,
        "open_trades": 2,
        "open_positions": [],
        "profit": _make_profit(),
        "recent_trades": [],
        "pair_performance": [],
        "log_errors": [],
    }
    base.update(overrides)
    return base


# ──────────────────────────────────────────────────────────────
# parse_status_and_decision
# ──────────────────────────────────────────────────────────────

class TestParseStatusAndDecision:

    def test_ok_status(self):
        response = "## Status: ✅ OK\n## Strategy Decision: KEEP\n"
        status, decision, exit_code = dm.parse_status_and_decision(response)
        assert status == "✅ OK"
        assert decision == "KEEP"
        assert exit_code == 0

    def test_warning_status(self):
        response = "## Status: ⚠️ WARNING\n## Strategy Decision: ADJUST\n"
        status, decision, exit_code = dm.parse_status_and_decision(response)
        assert status == "⚠️ WARNING"
        assert exit_code == 1

    def test_critical_status(self):
        response = "## Status: 🚨 CRITICAL\n## Strategy Decision: REPLACE\n"
        status, decision, exit_code = dm.parse_status_and_decision(response)
        assert status == "🚨 CRITICAL"
        assert exit_code == 2

    def test_decision_keep(self):
        _, decision, _ = dm.parse_status_and_decision("## Strategy Decision: KEEP\n")
        assert decision == "KEEP"

    def test_decision_adjust(self):
        _, decision, _ = dm.parse_status_and_decision("## Strategy Decision: ADJUST the params\n")
        assert decision == "ADJUST"

    def test_decision_replace(self):
        _, decision, _ = dm.parse_status_and_decision("## Strategy Decision: REPLACE with X\n")
        assert decision == "REPLACE"


# ──────────────────────────────────────────────────────────────
# parse_intent
# ──────────────────────────────────────────────────────────────

class TestParseIntent:

    def _response_with_handoff(self, payload: dict) -> str:
        blob = json.dumps(payload)
        return f"Some report text\nHANDOFF_JSON_START\n{blob}\nHANDOFF_JSON_END\n"

    def test_extracts_valid_handoff_json(self):
        payload = {
            "date": "2026-03-08",
            "status": "OK",
            "strategy_decision": "KEEP",
            "watching_tomorrow": ["Win rate"],
            "predictions": ["Rate stays above 50%"],
            "open_concerns": [],
            "internal_note": "Keep watching BTC",
            "user_notes_processed": {"had_notes": False},
        }
        response = self._response_with_handoff(payload)
        intent = dm.parse_intent(response, "✅ OK", "KEEP")
        assert intent["strategy_decision"] == "KEEP"
        assert intent["watching_tomorrow"] == ["Win rate"]

    def test_falls_back_on_malformed_json(self):
        response = "## Status: ✅ OK\nHANDOFF_JSON_START\n{broken json\nHANDOFF_JSON_END\n"
        intent = dm.parse_intent(response, "✅ OK", "KEEP")
        assert intent["strategy_decision"] == "KEEP"
        assert "internal_note" in intent

    def test_falls_back_when_no_handoff_block(self):
        response = "## Status: ✅ OK\n## Strategy Decision: KEEP\n"
        intent = dm.parse_intent(response, "✅ OK", "KEEP")
        assert intent["strategy_decision"] == "KEEP"


# ──────────────────────────────────────────────────────────────
# extract_note_to_user
# ──────────────────────────────────────────────────────────────

class TestExtractNoteToUser:

    def test_extracts_note_section(self):
        response = (
            "## Status: ✅ OK\n\n"
            "## Note to You\n"
            "The bot is running well. Win rate is 58%.\n\n"
            "## What I'm Watching Tomorrow\n"
            "- Win rate\n"
        )
        note = dm.extract_note_to_user(response)
        assert "Win rate is 58%" in note

    def test_returns_empty_when_section_missing(self):
        response = "## Status: ✅ OK\n"
        note = dm.extract_note_to_user(response)
        assert note == ""

    def test_truncates_long_note(self):
        long_text = "X" * 1000
        response = f"## Note to You\n{long_text}\n## What I'm Watching\n"
        note = dm.extract_note_to_user(response)
        assert len(note) <= 250


# ──────────────────────────────────────────────────────────────
# sanitise_note_line (user notes injection protection)
# ──────────────────────────────────────────────────────────────

class TestSanitiseNoteLine:

    def test_strips_control_characters(self):
        result = dm._sanitise_note_line("Hello\x00World\x1f!")
        assert "\x00" not in result
        assert "\x1f" not in result
        assert "Hello" in result

    def test_truncates_to_500_chars(self):
        long_line = "A" * 600
        result = dm._sanitise_note_line(long_line)
        assert len(result) == 500

    def test_preserves_normal_text(self):
        result = dm._sanitise_note_line("Please check the win rate tomorrow.")
        assert result == "Please check the win rate tomorrow."


# ──────────────────────────────────────────────────────────────
# read_user_notes
# ──────────────────────────────────────────────────────────────

class TestReadUserNotes:

    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dm, "USER_NOTES", tmp_path / "missing.md")
        assert dm.read_user_notes() == ""

    def test_strips_header_comments(self, tmp_path, monkeypatch):
        notes_file = tmp_path / "user_notes.md"
        notes_file.write_text(
            "# Notes to Claude\n"
            "<!-- example -->\n"
            "---\n"
            "2026-03-08: Please watch SOL.\n"
        )
        monkeypatch.setattr(dm, "USER_NOTES", notes_file)
        result = dm.read_user_notes()
        assert "Please watch SOL" in result
        assert "# Notes" not in result

    def test_caps_total_at_4kb(self, tmp_path, monkeypatch):
        notes_file = tmp_path / "user_notes.md"
        # Write 10 KB of notes
        notes_file.write_text("A" * 10_000)
        monkeypatch.setattr(dm, "USER_NOTES", notes_file)
        result = dm.read_user_notes()
        assert len(result) <= 4001  # 4000 chars + newline buffer


# ──────────────────────────────────────────────────────────────
# build_prompt
# ──────────────────────────────────────────────────────────────

class TestBuildPrompt:

    def test_includes_strategy_in_prompt(self):
        data = _make_data()
        prompt = dm.build_prompt(data, [], [], {}, [], {}, "")
        assert "GridTrendV2" in prompt

    def test_includes_user_notes_when_present(self):
        data = _make_data()
        prompt = dm.build_prompt(data, [], [], {}, [], {}, "Please watch SOL.")
        assert "Please watch SOL" in prompt

    def test_no_notes_block_when_empty(self):
        data = _make_data()
        prompt = dm.build_prompt(data, [], [], {}, [], {}, "")
        assert "No new messages" in prompt

    def test_includes_yesterday_intent(self):
        data = _make_data()
        yesterday = {
            "date": "2026-03-07",
            "strategy_decision": "KEEP",
            "watching_tomorrow": ["Win rate"],
            "predictions": ["Rate stays above 50%"],
            "open_concerns": [],
            "internal_note": "Watch BTC",
        }
        prompt = dm.build_prompt(data, [], [], {}, [], yesterday, "")
        assert "Watch BTC" in prompt

    def test_includes_mode_label(self):
        data = _make_data(dry_run=True)
        prompt = dm.build_prompt(data, [], [], {}, [], {}, "")
        assert "PAPER" in prompt or "dry-run" in prompt

    def test_real_money_mode_labelled(self):
        data = _make_data(dry_run=False)
        prompt = dm.build_prompt(data, [], [], {}, [], {}, "")
        assert "REAL MONEY" in prompt


# ──────────────────────────────────────────────────────────────
# intent persistence (load/save)
# ──────────────────────────────────────────────────────────────

class TestIntentPersistence:

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        intent_file = tmp_path / "claude_intent.json"
        monkeypatch.setattr(dm, "INTENT_FILE", intent_file)

        payload = {
            "date": "2026-03-08",
            "status": "OK",
            "strategy_decision": "KEEP",
            "watching_tomorrow": ["Win rate"],
        }
        dm.save_intent(payload)
        loaded = dm.load_yesterday_intent()

        assert loaded["strategy_decision"] == "KEEP"
        assert "saved_at" in loaded  # timestamp added by save_intent

    def test_load_returns_empty_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dm, "INTENT_FILE", tmp_path / "missing.json")
        assert dm.load_yesterday_intent() == {}

    def test_load_returns_empty_on_corrupt_file(self, tmp_path, monkeypatch):
        intent_file = tmp_path / "corrupt.json"
        intent_file.write_text("{broken json")
        monkeypatch.setattr(dm, "INTENT_FILE", intent_file)
        assert dm.load_yesterday_intent() == {}


# ──────────────────────────────────────────────────────────────
# write_audit_event
# ──────────────────────────────────────────────────────────────

class TestWriteAuditEvent:

    def test_writes_json_line_to_audit_file(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit.log"
        monkeypatch.setattr(dm, "AUDIT_FILE", audit_file)

        dm.write_audit_event("monitor.run", "Test action", {"key": "value"})

        lines = audit_file.read_text().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["event_type"] == "monitor.run"
        assert event["action"] == "Test action"
        assert event["details"]["key"] == "value"

    def test_appends_multiple_events(self, tmp_path, monkeypatch):
        audit_file = tmp_path / "audit.log"
        monkeypatch.setattr(dm, "AUDIT_FILE", audit_file)

        dm.write_audit_event("monitor.run", "First", {})
        dm.write_audit_event("monitor.run", "Second", {})

        lines = audit_file.read_text().strip().splitlines()
        assert len(lines) == 2
