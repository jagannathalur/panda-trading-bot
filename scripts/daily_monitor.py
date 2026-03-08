#!/usr/bin/env python3
"""
daily_monitor.py — Daily bot health check powered by Claude Sonnet.

Communication channels:
  Claude  → You   : Daily markdown report + macOS notification
  Claude  → Claude : claude_intent.json  (yesterday's me tells today's me what to watch)
  You     → Claude : user_notes.md       (leave a note any time — Claude reads it next morning)
  Both    ↔ System : audit.log           (every run is a MONITOR_RUN audit event)

Run schedule: every day at 08:00 via launchd (com.panda.dailymonitor)
Manual run:   python3 scripts/daily_monitor.py

Exit codes:
  0 = OK
  1 = WARNING (review recommended)
  2 = CRITICAL (immediate attention needed)
"""

from __future__ import annotations

import json
import os
import re
import sys
import subprocess
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ---------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE     = PROJECT_ROOT / ".env"
MONITOR_DIR  = PROJECT_ROOT / "data" / "monitoring"
LOG_FILE     = PROJECT_ROOT / "user_data" / "logs" / "paper.log"
AUDIT_FILE   = PROJECT_ROOT / "data" / "audit.log"
INTENT_FILE  = MONITOR_DIR / "claude_intent.json"
USER_NOTES   = MONITOR_DIR / "user_notes.md"

MONITOR_DIR.mkdir(parents=True, exist_ok=True)

# Load .env (no external dependencies)
if ENV_FILE.exists():
    for raw in ENV_FILE.read_text().splitlines():
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, _, v = raw.partition("=")
            # Strip inline comments (e.g. "168  # 7 days" → "168")
            v = v.split("#")[0].strip()
            os.environ.setdefault(k.strip(), v)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FT_USER  = os.environ.get("FREQTRADE_API_USERNAME", "freqtrade")
FT_PASS  = os.environ.get("FREQTRADE_API_PASSWORD", "change-me")
FT_BASE        = f"http://{os.environ.get('FREQTRADE_API_HOST','127.0.0.1')}:{os.environ.get('FREQTRADE_API_PORT','8081')}/api/v1"
DASHBOARD_BASE = f"http://{os.environ.get('DASHBOARD_HOST','127.0.0.1')}:{os.environ.get('DASHBOARD_PORT','8080')}"

MONITOR_MODEL = os.environ.get("MONITOR_MODEL", "claude-sonnet-4-6")
TODAY         = datetime.now(timezone.utc).strftime("%Y-%m-%d")
REPORT_FILE   = MONITOR_DIR / f"{TODAY}.md"


# ---------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------

def ft_get(path: str, params: dict | None = None) -> dict | list | None:
    try:
        r = requests.get(f"{FT_BASE}{path}", auth=(FT_USER, FT_PASS),
                         params=params or {}, timeout=5)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        # Bot is offline — expected when not running
        return None
    except Exception as exc:
        print(f"[monitor] ft_get({path}) failed: {exc}", file=sys.stderr)
        return None


def collect_bot_data() -> dict:
    config      = ft_get("/show_config") or {}
    profit      = ft_get("/profit") or {}
    status      = ft_get("/status") or []
    trades      = ft_get("/trades", {"limit": 50}) or {}
    balance     = ft_get("/balance") or {}
    performance = ft_get("/performance") or []
    logs        = ft_get("/logs", {"limit": 60}) or {}

    bot_online = bool(config)

    # Extract USDT balance
    currencies = balance.get("currencies", []) or []
    usdt_bal = next(
        (c.get("free", 0) + c.get("used", 0) for c in currencies if c.get("currency") == "USDT"),
        balance.get("total", 0),
    )

    # Extract log errors
    log_entries = logs.get("logs", []) or []
    errors = [
        e[3] for e in log_entries
        if isinstance(e, list) and len(e) > 3 and "ERROR" in str(e[2])
    ][-8:]

    return {
        "bot_online":     bot_online,
        "state":          config.get("state", "unknown"),
        "strategy":       config.get("strategy", "unknown"),
        "trading_mode":   config.get("trading_mode", "unknown"),
        "dry_run":        config.get("dry_run", True),
        "exchange":       config.get("exchange", "unknown"),
        "balance_usdt":   usdt_bal,
        "open_trades":    len(status) if isinstance(status, list) else 0,
        "open_positions": [
            {"pair": t.get("pair"),
             "side": "short" if t.get("is_short") else "long",
             "profit_pct": round(t.get("profit_pct", 0), 3),
             "open_date": t.get("open_date")}
            for t in (status if isinstance(status, list) else [])
        ][:5],
        "profit": {
            "total_usdt":      profit.get("profit_all_coin", 0),
            "total_pct":       profit.get("profit_all_percent", 0),
            "win_rate":        profit.get("winrate", 0),
            "winning_trades":  profit.get("winning_trades", 0),
            "losing_trades":   profit.get("losing_trades", 0),
            "profit_factor":   profit.get("profit_factor", 0),
            "max_drawdown":    profit.get("max_drawdown", 0),
            "trade_count":     profit.get("trade_count", 0),
            "best_pair":       profit.get("best_pair", "N/A"),
            "worst_pair":      profit.get("worst_pair", "N/A"),
            "avg_duration":    profit.get("avg_duration", "N/A"),
        },
        "recent_trades": [
            {"pair":        t.get("pair"),
             "side":        "short" if t.get("is_short") else "long",
             "profit_pct":  round(t.get("profit_pct", 0), 3),
             "exit_reason": t.get("sell_reason") or t.get("exit_reason"),
             "open_date":   t.get("open_date"),
             "close_date":  t.get("close_date")}
            for t in (trades.get("trades", []) if isinstance(trades, dict) else [])[:10]
        ],
        "pair_performance": (performance[:6] if isinstance(performance, list) else []),
        "log_errors":      errors,
    }


def collect_risk_state() -> dict:
    try:
        r = requests.get(f"{DASHBOARD_BASE}/api/status", timeout=3)
        return r.json()
    except Exception:
        return {}


def collect_audit_tail() -> list[str]:
    try:
        lines = AUDIT_FILE.read_text().splitlines() if AUDIT_FILE.exists() else []
        return lines[-20:]
    except Exception:
        return []


def collect_log_highlights() -> list[str]:
    """Last 80 lines filtered to errors, state changes, vetoes."""
    keywords = ("ERROR", "WARNING", "CRITICAL", "RUNNING", "STOPPED",
                "Kill", "veto", "blocked", "LLM", "sentiment", "FundingRate")
    try:
        lines = LOG_FILE.read_text().splitlines() if LOG_FILE.exists() else []
        return [l for l in lines[-120:] if any(k in l for k in keywords)][-25:]
    except Exception:
        return []


# ---------------------------------------------------------------
# Claude ↔ Claude: intent handoff
# ---------------------------------------------------------------

def load_yesterday_intent() -> dict:
    """Read what the previous Claude run committed to watching."""
    if not INTENT_FILE.exists():
        return {}
    try:
        return json.loads(INTENT_FILE.read_text())
    except Exception:
        return {}


def save_intent(intent: dict) -> None:
    """Persist today's Claude intent for tomorrow's run."""
    intent["saved_at"] = datetime.now(timezone.utc).isoformat()
    INTENT_FILE.write_text(json.dumps(intent, indent=2))


# ---------------------------------------------------------------
# You → Claude: user notes
# ---------------------------------------------------------------

def _sanitise_note_line(line: str) -> str:
    """
    Strip non-printable characters and limit line length.
    Guards against accidental prompt injection from the notes file.
    """
    # Keep printable ASCII + common unicode; strip control characters
    cleaned = "".join(ch for ch in line if ch >= " " or ch == "\t")
    return cleaned[:500]  # Hard cap per line


def read_user_notes() -> str:
    """Read user_notes.md, return the substantive content (sanitised)."""
    if not USER_NOTES.exists():
        return ""
    try:
        text = USER_NOTES.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    # Strip header/template comments
    lines = [
        _sanitise_note_line(l)
        for l in text.splitlines()
        if not l.startswith("#")
        and not l.startswith("<!--")
        and not l.startswith("-->")
        and l.strip() != "---"
        and l.strip()
    ]
    return "\n".join(lines).strip()[:4000]  # Cap total notes at 4 KB


def archive_user_notes(notes: str) -> None:
    """Append processed notes to archive and clear the inbox."""
    if not notes:
        return
    archive = MONITOR_DIR / "user_notes_archive.md"
    with archive.open("a") as f:
        f.write(f"\n## Processed on {TODAY}\n{notes}\n")
    # Reset the inbox (keep the header/instructions)
    header = USER_NOTES.read_text().split("---")[0] + "---\n\n"
    USER_NOTES.write_text(header)


# ---------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------

def write_audit_event(event_type: str, action: str, details: dict,
                      outcome: str = "recorded") -> None:
    """Write a MONITOR_RUN event directly to the audit log (JSON-Lines)."""
    event = {
        "event_id":   str(uuid.uuid4()),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "actor":      f"daily_monitor/{MONITOR_MODEL}",
        "action":     action,
        "details":    details,
        "outcome":    outcome,
    }
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_FILE.open("a") as f:
            f.write(json.dumps(event) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception as exc:
        print(f"[audit] write failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------
# Claude prompt
# ---------------------------------------------------------------

def build_prompt(data: dict, audit: list[str], logs: list[str],
                 risk: dict, history: list[str],
                 yesterday: dict, user_notes: str) -> str:

    p = data["profit"]
    mode = "PAPER/dry-run" if data["dry_run"] else "⚠️ REAL MONEY"
    today_str = datetime.now(timezone.utc).strftime("%A %B %d, %Y")

    # Yesterday's handoff block
    if yesterday:
        yesterday_block = f"""
## YESTERDAY'S CLAUDE INTENT (written by previous run — check if predictions held)
Date: {yesterday.get('date', 'unknown')}
My decision was: {yesterday.get('strategy_decision', 'unknown')}
I said I'd watch for: {json.dumps(yesterday.get('watching_tomorrow', []), indent=2)}
My predictions were: {json.dumps(yesterday.get('predictions', []), indent=2)}
My open concerns were: {json.dumps(yesterday.get('open_concerns', []), indent=2)}
Internal note to myself: {yesterday.get('internal_note', 'none')}

→ Based on today's data, state clearly which predictions came true, which didn't, and why.
"""
    else:
        yesterday_block = "\n## YESTERDAY'S CLAUDE INTENT\nFirst run — no previous intent.\n"

    # User notes block
    if user_notes:
        notes_block = f"""
## MESSAGE FROM THE OPERATOR (user_notes.md — read and acknowledge)
{user_notes}
→ Respond directly to each point in your "Note to You" section.
"""
    else:
        notes_block = "\n## MESSAGE FROM THE OPERATOR\nNo new messages.\n"

    return f"""You are the strategy overseer for panda-trading-bot, running on {data['exchange']} ({data['trading_mode']}, {mode}).
Today is {today_str}.

Your outputs serve two audiences:
1. The operator (human) — they read the report and your "Note to You"
2. Tomorrow's Claude — reads your HANDOFF JSON to continue where you left off

{yesterday_block}
{notes_block}

---
## TODAY'S BOT DATA

Bot online: {data['bot_online']} | State: {data['state']} | Strategy: {data['strategy']}
Paper wallet: {data['balance_usdt']:.2f} USDT | Open trades: {data['open_trades']}

### All-Time Performance
Total P&L: {p['total_usdt']:.4f} USDT ({p['total_pct']:.2f}%)
Win rate: {p['win_rate']:.1%} | Profit factor: {p['profit_factor']:.2f}
Wins: {p['winning_trades']} | Losses: {p['losing_trades']} | Total trades: {p['trade_count']}
Max drawdown: {p['max_drawdown']:.2%} | Avg duration: {p['avg_duration']}
Best pair: {p['best_pair']} | Worst pair: {p['worst_pair']}

### Open Positions
{json.dumps(data['open_positions'], indent=2) or 'None'}

### Recent Closed Trades (last 10)
{json.dumps(data['recent_trades'], indent=2) or 'No closed trades yet.'}

### Pair Performance
{json.dumps(data['pair_performance'], indent=2) or 'No data yet.'}

### Risk Engine State
{json.dumps(risk, indent=2) or 'Dashboard unavailable.'}

### Bot Log Highlights (errors, state changes, LLM decisions)
{chr(10).join(logs) or 'No highlights.'}

### Recent Audit Events
{chr(10).join(audit) or 'No audit entries.'}

### Previous 7 Reports (trend context)
{chr(10).join(history) or 'No history.'}

---

Write your response in this exact format (sections in order):

## Status: [✅ OK | ⚠️ WARNING | 🚨 CRITICAL]

## Performance Assessment
[3-5 sentences. Compare to benchmarks: >50% win rate, profit factor >1.2, drawdown <12%.
If <10 trades, note that sample is too small to judge — focus on behaviour instead.
If yesterday's predictions: state clearly what came true and what didn't.]

## Strategy Decision: [KEEP | ADJUST | REPLACE]
[Clear reasoning. KEEP: say why it's fine. ADJUST: give exact parameter values.
REPLACE: name the alternative approach and explain why the current one is failing.]

## Parameter Changes (if any)
[Exact values, e.g. "ema_fast: 9 → 7". Or "No changes — keep current params."]

## Anomalies & Risks
[Bullet list. Be specific: pair name, error message, pattern. "None detected" if clean.]

## Note to You
[Direct plain-English message to the operator. Acknowledge any user notes above.
Explain what happened today in plain language, what you're watching, and what they
might want to do (or not do). This is the main human-facing message. 3-8 sentences.]

## What I'm Watching Tomorrow
- [Specific metric + threshold, e.g. "Win rate — flag if drops below 45%"]
- [Another specific item]
- [Max 5 items]

## My Predictions for Tomorrow
- [What you expect to happen based on current trajectory]
- [Max 3 predictions — be falsifiable so tomorrow's Claude can verify]

---
HANDOFF_JSON_START
{{
  "date": "{TODAY}",
  "status": "<OK|WARNING|CRITICAL>",
  "strategy_decision": "<KEEP|ADJUST|REPLACE>",
  "watching_tomorrow": ["<item1>", "<item2>"],
  "predictions": ["<pred1>", "<pred2>"],
  "open_concerns": ["<concern or none>"],
  "internal_note": "<private note to tomorrow's Claude — max 2 sentences>",
  "user_notes_processed": {{"had_notes": true}}
}}
HANDOFF_JSON_END
"""


def collect_report_history(n: int = 7) -> list[str]:
    summaries = []
    for i in range(1, n + 1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        path = MONITOR_DIR / f"{day}.md"
        if path.exists():
            lines = [l for l in path.read_text().splitlines()[:10] if l.strip()]
            summaries.append(f"[{day}] " + " | ".join(lines[:4]))
    return summaries


# ---------------------------------------------------------------
# Parse Claude's response
# ---------------------------------------------------------------

def parse_intent(response: str, status: str, decision: str) -> dict:
    """Extract the structured HANDOFF JSON from Claude's response."""
    match = re.search(
        r"HANDOFF_JSON_START\s*(\{.*?\})\s*HANDOFF_JSON_END",
        response,
        re.DOTALL,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Fallback: build minimal intent from parsed fields
    watching = []
    for line in response.splitlines():
        if line.strip().startswith("- ") and "Watching" in response:
            watching.append(line.strip()[2:])

    return {
        "date":               TODAY,
        "status":             status.replace("✅ ", "").replace("⚠️ ", "").replace("🚨 ", ""),
        "strategy_decision":  decision,
        "watching_tomorrow":  watching[:5],
        "predictions":        [],
        "open_concerns":      [],
        "internal_note":      "Handoff JSON parse failed — check report for details.",
        "user_notes_processed": {"had_notes": False},
    }


def parse_status_and_decision(response: str) -> tuple[str, str, int]:
    status = "✅ OK"
    exit_code = 0
    if "🚨 CRITICAL" in response:
        status, exit_code = "🚨 CRITICAL", 2
    elif "⚠️ WARNING" in response:
        status, exit_code = "⚠️ WARNING", 1

    decision = "KEEP"
    for line in response.splitlines():
        if "Strategy Decision:" in line:
            if "REPLACE" in line:
                decision = "REPLACE"
            elif "ADJUST" in line:
                decision = "ADJUST"
            break

    return status, decision, exit_code


def extract_note_to_user(response: str) -> str:
    """Pull out the 'Note to You' section for the notification."""
    lines = response.splitlines()
    capturing, note_lines = False, []
    for line in lines:
        if "## Note to You" in line:
            capturing = True
            continue
        if capturing:
            if line.startswith("## ") or line.startswith("HANDOFF_JSON"):
                break
            note_lines.append(line)
    return " ".join(l.strip() for l in note_lines if l.strip())[:250]


# ---------------------------------------------------------------
# Save report (strips HANDOFF block before saving for readability)
# ---------------------------------------------------------------

def save_report(response: str, data: dict) -> Path:
    # Remove the raw HANDOFF JSON from user-facing report
    clean = re.sub(
        r"\n*---\nHANDOFF_JSON_START.*?HANDOFF_JSON_END\n*",
        "",
        response,
        flags=re.DOTALL,
    ).strip()

    report = (
        f"# Panda Bot Daily Monitor — {TODAY}\n"
        f"_Claude {MONITOR_MODEL} · {datetime.now(timezone.utc).strftime('%H:%M UTC')}_\n\n"
        f"---\n\n"
        f"{clean}\n\n"
        f"---\n"
        f"<details><summary>Raw Performance Data</summary>\n\n"
        f"```json\n{json.dumps(data['profit'], indent=2)}\n```\n\n"
        f"</details>\n"
    )
    REPORT_FILE.write_text(report)
    return REPORT_FILE


# ---------------------------------------------------------------
# Notification
# ---------------------------------------------------------------

def notify_macos(status: str, decision: str, note: str, report_path: Path) -> None:
    short_note = note[:80] + "…" if len(note) > 80 else note
    try:
        script = (
            f'display notification "{short_note}" '
            f'with title "Panda Bot — {status}" '
            f'subtitle "Strategy: {decision}" '
            f'sound name "Default"'
        )
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception:
        pass

    if "CRITICAL" in status:
        try:
            subprocess.run(["open", str(report_path)], check=False, timeout=5)
        except Exception:
            pass


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------

def main() -> int:
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set — run: bash scripts/setup_secrets.sh")
        return 2

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Collecting data...")
    data      = collect_bot_data()
    audit     = collect_audit_tail()
    logs      = collect_log_highlights()
    risk      = collect_risk_state()
    history   = collect_report_history()
    yesterday = load_yesterday_intent()
    notes     = read_user_notes()

    had_notes = bool(notes)
    if had_notes:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] User notes found — including in prompt.")
        write_audit_event(
            "monitor.user_note_read",
            "User notes read and included in daily prompt",
            {"preview": notes[:200]},
        )

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Calling Claude {MONITOR_MODEL}...")
    prompt = build_prompt(data, audit, logs, risk, history, yesterday, notes)

    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=60.0)
        message = client.messages.create(
            model=MONITOR_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        response = message.content[0].text.strip()
    except Exception as exc:
        safe = re.sub(r"sk-[a-zA-Z0-9\-_]{10,}", "[REDACTED]", str(exc))
        print(f"ERROR: Claude API failed: {safe}")
        return 2

    status, decision, exit_code = parse_status_and_decision(response)
    note_to_user = extract_note_to_user(response)
    intent = parse_intent(response, status, decision)
    intent["user_notes_processed"] = {"had_notes": had_notes}

    # Persist
    report_path = save_report(response, data)
    save_intent(intent)
    if had_notes:
        archive_user_notes(notes)

    # Audit trail
    write_audit_event(
        "monitor.run",
        f"Daily monitor completed: {status} | {decision}",
        {
            "status":          status,
            "strategy_decision": decision,
            "trade_count":     data["profit"]["trade_count"],
            "win_rate":        data["profit"]["win_rate"],
            "profit_factor":   data["profit"]["profit_factor"],
            "max_drawdown":    data["profit"]["max_drawdown"],
            "note_to_user":    note_to_user,
            "watching_tomorrow": intent.get("watching_tomorrow", []),
            "user_notes_read": had_notes,
            "report_file":     str(report_path),
            "model":           MONITOR_MODEL,
        },
        outcome=status,
    )
    write_audit_event(
        "monitor.strategy_decision",
        f"Strategy decision: {decision}",
        {"decision": decision, "reasoning_preview": response[:300]},
        outcome=decision,
    )

    # Print summary to stdout (goes to launchd log)
    print(f"\n{'='*60}")
    print(f"  {status}  |  Strategy: {decision}")
    print(f"  Trades: {data['profit']['trade_count']} | Win rate: {data['profit']['win_rate']:.1%}")
    print(f"  Watching tomorrow: {intent.get('watching_tomorrow', [])}")
    print(f"  Report: {report_path}")
    print(f"{'='*60}\n")

    notify_macos(status, decision, note_to_user, report_path)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
