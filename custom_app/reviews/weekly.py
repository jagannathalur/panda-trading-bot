"""Weekly strategy review generation and operator decision tracking."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from custom_app.config.hashing import hash_multiple_configs

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REVIEW_DIR = PROJECT_ROOT / "data" / "weekly_reviews"
DEFAULT_DB_PATH = PROJECT_ROOT / "tradesv3.dryrun.sqlite"
DEFAULT_LOG_PATH = PROJECT_ROOT / "user_data" / "logs" / "paper_debug.log"
DEFAULT_ARTIFACTS_DIR = PROJECT_ROOT / "data" / "artifacts"
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "data" / "strategy_registry.json"
DEFAULT_CONFIG_PATHS = [
    PROJECT_ROOT / "configs" / "base.json",
    PROJECT_ROOT / "configs" / "futures_paper.json",
]
DEFAULT_MODEL = os.environ.get("WEEKLY_REVIEW_MODEL", "claude-sonnet-4-6")

_REVIEW_JSON_RE = re.compile(
    r"REVIEW_JSON_START\s*(\{.*?\})\s*REVIEW_JSON_END",
    re.DOTALL,
)
_FNG_RE = re.compile(r"Fear & Greed:\s*(\d+)\s*\(([^)]+)\)")


def generate_weekly_review(
    *,
    now: Optional[datetime] = None,
    review_dir: Path | str = DEFAULT_REVIEW_DIR,
    db_path: Path | str = DEFAULT_DB_PATH,
    log_path: Path | str = DEFAULT_LOG_PATH,
    strategy_id: Optional[str] = None,
) -> dict[str, Any]:
    """Collect weekly context, ask the LLM for review, and persist the result."""
    context = collect_weekly_context(
        now=now,
        db_path=db_path,
        log_path=log_path,
        strategy_id=strategy_id,
    )
    report = _call_llm_or_fallback(context)
    saved = save_weekly_review(report, review_dir=review_dir)
    _write_audit_event("review.weekly_run", "Weekly strategy review generated", {
        "review_file": str(saved),
        "recommendation": report["recommendation"],
        "strategy_id": report["strategy_id"],
        "model": report["model"],
    })
    return report


def load_latest_weekly_review(
    review_dir: Path | str = DEFAULT_REVIEW_DIR,
) -> Optional[dict[str, Any]]:
    """Return the most recent weekly review artifact, if any."""
    review_path = latest_weekly_review_path(review_dir=review_dir)
    if review_path is None:
        return None
    with review_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def latest_weekly_review_path(
    review_dir: Path | str = DEFAULT_REVIEW_DIR,
) -> Optional[Path]:
    """Locate the newest weekly review JSON file."""
    directory = Path(review_dir)
    if not directory.exists():
        return None
    candidates = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def record_weekly_review_decision(
    decision: str,
    *,
    notes: str = "",
    review_dir: Path | str = DEFAULT_REVIEW_DIR,
    decided_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Persist an operator accept/reject decision on the latest weekly review."""
    decision = decision.strip().lower()
    if decision not in {"accept", "reject"}:
        raise ValueError("decision must be 'accept' or 'reject'")

    review_path = latest_weekly_review_path(review_dir=review_dir)
    if review_path is None:
        raise FileNotFoundError("No weekly review available to update.")

    with review_path.open("r", encoding="utf-8") as handle:
        review = json.load(handle)

    review["operator_decision"] = {
        "decision": decision,
        "notes": notes.strip(),
        "decided_at": _iso(decided_at or datetime.now(timezone.utc)),
        "action": (
            "open_research_candidate"
            if decision == "accept" and review.get("recommendation") in {"research_recommended", "change_recommended"}
            else "keep_current_algo"
        ),
    }

    with review_path.open("w", encoding="utf-8") as handle:
        json.dump(review, handle, indent=2)

    _write_audit_event("review.weekly_decision", "Weekly strategy review decision recorded", {
        "review_file": str(review_path),
        "decision": decision,
        "recommendation": review.get("recommendation"),
        "notes": notes.strip(),
    })
    return review


def save_weekly_review(
    review: dict[str, Any],
    *,
    review_dir: Path | str = DEFAULT_REVIEW_DIR,
) -> Path:
    """Save weekly review artifact and companion markdown report."""
    directory = Path(review_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = review["generated_at"].replace(":", "").replace("-", "")
    base_name = f"{stamp}_{review['strategy_id']}"
    json_path = directory / f"{base_name}.json"
    md_path = directory / f"{base_name}.md"

    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(review, handle, indent=2)

    md_path.write_text(review["report_markdown"], encoding="utf-8")
    review["report_file"] = str(md_path)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(review, handle, indent=2)
    return json_path


def collect_weekly_context(
    *,
    now: Optional[datetime] = None,
    db_path: Path | str = DEFAULT_DB_PATH,
    log_path: Path | str = DEFAULT_LOG_PATH,
    strategy_id: Optional[str] = None,
) -> dict[str, Any]:
    """Collect weekly context for LLM review."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    period_end = now_utc
    period_start = now_utc - timedelta(days=7)
    strategy = strategy_id or os.environ.get("FREQTRADE_STRATEGY", "GridTrendV2")
    db_file = Path(db_path)
    closed_trades = _load_closed_trades(db_file, period_start, period_end)
    open_trades = _load_open_trades(db_file)
    weekly_metrics = _summarise_closed_trades(closed_trades)
    open_metrics = _summarise_open_trades(open_trades)
    log_context = _collect_log_context(Path(log_path))

    strategy_file = _find_strategy_file(strategy)
    config_paths = [p for p in DEFAULT_CONFIG_PATHS if p.exists()]
    latest_artifact = _load_latest_validation_artifact(strategy)
    promotion_status = _load_promotion_status(strategy)

    return {
        "generated_at": _iso(now_utc),
        "period_start": _iso(period_start),
        "period_end": _iso(period_end),
        "strategy_id": strategy,
        "db_path": str(db_file),
        "trading_mode": "paper",
        "portfolio_profile": "single-operator small portfolio",
        "goals": [
            "preserve capital",
            "prefer no trade over weak edge",
            "make bounded, evidence-backed changes only",
        ],
        "strategy_hash": _hash_file(strategy_file) if strategy_file else None,
        "strategy_file": str(strategy_file) if strategy_file else None,
        "config_hash": hash_multiple_configs([str(p) for p in config_paths]) if config_paths else None,
        "config_paths": [str(p) for p in config_paths],
        "latest_validation_artifact": latest_artifact,
        "promotion_status": promotion_status,
        "weekly_metrics": weekly_metrics,
        "open_metrics": open_metrics,
        "log_context": log_context,
    }


def _load_closed_trades(
    db_path: Path,
    period_start: datetime,
    period_end: datetime,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    query = """
        SELECT
            id, pair, is_open, close_profit_abs, close_profit, open_date, close_date,
            exit_reason, is_short, strategy, enter_tag
        FROM trades
        WHERE is_open = 0
          AND close_date IS NOT NULL
          AND close_date >= ?
          AND close_date < ?
        ORDER BY close_date ASC
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, (period_start.strftime("%Y-%m-%d %H:%M:%S"), period_end.strftime("%Y-%m-%d %H:%M:%S"))).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _load_open_trades(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    query = """
        SELECT id, pair, is_short, open_date, stake_amount, leverage
        FROM trades
        WHERE is_open = 1
        ORDER BY open_date DESC
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _summarise_closed_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    trade_count = len(trades)
    pnl_values = [float(t.get("close_profit_abs") or 0.0) for t in trades]
    wins = sum(1 for pnl in pnl_values if pnl > 0)
    losses = sum(1 for pnl in pnl_values if pnl < 0)
    weekly_pnl = sum(pnl_values)
    avg_pnl = weekly_pnl / trade_count if trade_count else 0.0
    avg_hold_minutes = _average_hold_minutes(trades)
    drawdown_abs = _max_drawdown_abs(pnl_values)

    pair_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "pair": "",
        "trade_count": 0,
        "pnl_abs": 0.0,
        "wins": 0,
    })
    exit_reasons = Counter()
    side_counts = Counter()

    for trade, pnl in zip(trades, pnl_values):
        pair = trade.get("pair") or "unknown"
        stats = pair_stats[pair]
        stats["pair"] = pair
        stats["trade_count"] += 1
        stats["pnl_abs"] += pnl
        stats["wins"] += 1 if pnl > 0 else 0
        exit_reasons[str(trade.get("exit_reason") or "unknown")] += 1
        side_counts["short" if trade.get("is_short") else "long"] += 1

    pair_breakdown = sorted(
        (
            {
                **stats,
                "win_rate": round(stats["wins"] / stats["trade_count"], 4) if stats["trade_count"] else 0.0,
            }
            for stats in pair_stats.values()
        ),
        key=lambda item: item["pnl_abs"],
        reverse=True,
    )

    return {
        "closed_trade_count": trade_count,
        "weekly_pnl_abs": round(weekly_pnl, 6),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / trade_count, 4) if trade_count else 0.0,
        "avg_pnl_abs": round(avg_pnl, 6),
        "avg_hold_minutes": avg_hold_minutes,
        "max_drawdown_abs": round(drawdown_abs, 6),
        "pair_breakdown": pair_breakdown[:5],
        "exit_reason_counts": dict(exit_reasons.most_common()),
        "side_counts": dict(side_counts),
    }


def _summarise_open_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "open_trade_count": len(trades),
        "open_trades": [
            {
                "pair": trade.get("pair"),
                "side": "short" if trade.get("is_short") else "long",
                "open_date": trade.get("open_date"),
                "stake_amount": trade.get("stake_amount"),
                "leverage": trade.get("leverage"),
            }
            for trade in trades[:5]
        ],
    }


def _average_hold_minutes(trades: list[dict[str, Any]]) -> float:
    durations = []
    for trade in trades:
        opened = _parse_dt(trade.get("open_date"))
        closed = _parse_dt(trade.get("close_date"))
        if opened and closed:
            durations.append((closed - opened).total_seconds() / 60.0)
    return round(sum(durations) / len(durations), 2) if durations else 0.0


def _max_drawdown_abs(pnl_values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _collect_log_context(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {
            "fear_greed": None,
            "entry_rejections": 0,
            "oi_failures": 0,
            "liquidation_failures": 0,
            "gdelet_or_geo_events": 0,
            "llm_disabled": False,
            "recent_issues": [],
        }

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-2000:]
    except Exception:
        lines = []

    entry_rejections = sum("Found no enter signals" in line for line in lines)
    oi_failures = sum("OI fetch failed" in line for line in lines)
    liquidation_failures = sum("Liquidation fetch failed" in line for line in lines)
    geo_events = sum(("GDELT" in line) or ("geopolit" in line.lower()) or ("Geo=" in line) for line in lines)
    llm_disabled = any("LLM gate disabled" in line for line in lines)

    fear_greed = None
    for line in reversed(lines):
        match = _FNG_RE.search(line)
        if match:
            fear_greed = {
                "value": int(match.group(1)),
                "label": match.group(2),
            }
            break

    recent_issues = [
        line for line in lines
        if any(token in line for token in ("WARNING", "ERROR", "OI fetch failed", "Liquidation fetch failed", "LLM gate disabled"))
    ][-10:]

    return {
        "fear_greed": fear_greed,
        "entry_rejections": entry_rejections,
        "oi_failures": oi_failures,
        "liquidation_failures": liquidation_failures,
        "gdelet_or_geo_events": geo_events,
        "llm_disabled": llm_disabled,
        "recent_issues": recent_issues,
    }


def _find_strategy_file(strategy_id: str) -> Optional[Path]:
    candidate = PROJECT_ROOT / "user_data" / "strategies" / f"{strategy_id}.py"
    return candidate if candidate.exists() else None


def _load_latest_validation_artifact(strategy_id: str) -> Optional[dict[str, Any]]:
    artifacts_dir = DEFAULT_ARTIFACTS_DIR
    if not artifacts_dir.exists():
        return None
    matches = sorted(
        artifacts_dir.glob(f"{strategy_id}_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        return None
    path = matches[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"path": str(path), "error": "unreadable"}
    return {
        "path": str(path),
        "generated_at": data.get("generated_at"),
        "passed": data.get("passed"),
        "fail_reason": data.get("fail_reason"),
        "backtest_report": bool(data.get("backtest_report")),
        "walk_forward_report": bool(data.get("walk_forward_report")),
        "shadow_report": data.get("shadow_report"),
    }


def _load_promotion_status(strategy_id: str) -> Optional[dict[str, Any]]:
    try:
        from custom_app.promotion import StrategyRegistry
        registry = StrategyRegistry(str(DEFAULT_REGISTRY_PATH))
        pipeline = registry.get(strategy_id)
        if pipeline is None:
            return None
        return pipeline.get_status()
    except Exception:
        return None


def _call_llm_or_fallback(context: dict[str, Any]) -> dict[str, Any]:
    prompt = build_weekly_review_prompt(context)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if api_key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, timeout=90.0)
            message = client.messages.create(
                model=DEFAULT_MODEL,
                max_tokens=1800,
                messages=[{"role": "user", "content": prompt}],
            )
            response = message.content[0].text.strip()
            parsed = parse_weekly_review_response(response)
            if parsed is not None:
                return _build_review_artifact(context, parsed, response, model=DEFAULT_MODEL)
        except Exception as exc:
            fallback_reason = f"LLM unavailable: {exc}"
            return _fallback_review(context, fallback_reason)

    return _fallback_review(context, "ANTHROPIC_API_KEY missing or LLM unavailable")


def build_weekly_review_prompt(context: dict[str, Any]) -> str:
    """Build the weekly review prompt for Claude."""
    compact_context = json.dumps(context, indent=2, ensure_ascii=True)
    return f"""You are reviewing a small, single-operator crypto futures paper portfolio.

Operating style:
- behave like one pragmatic quant managing a small book
- capital preservation matters more than activity
- "do nothing" is valid when edge is weak
- strategy changes must be bounded and evidence-backed
- if the problem is data quality, observability, or market regime, say that instead of forcing algo changes

Review this weekly context and decide whether to keep the current strategy, monitor it, recommend research, or recommend a bounded change.

Output format:
1. Short markdown report with these sections in order:
   - ## Weekly Recommendation
   - ## Executive Summary
   - ## What Is Working
   - ## What Is Degrading
   - ## Recommended Changes
   - ## Operator Note
2. Then include a machine-readable block:
REVIEW_JSON_START
{{
  "recommendation": "continue|monitor|research_recommended|change_recommended",
  "headline": "one sentence summary",
  "summary": "two to four sentence summary",
  "what_is_working": ["..."],
  "what_is_degrading": ["..."],
  "recommended_changes": ["..."],
  "rationale": ["..."],
  "risks": ["..."],
  "should_revalidate": true,
  "operator_action": "keep_current_algo|open_research_candidate",
  "confidence": 0.0
}}
REVIEW_JSON_END

Weekly context:
```json
{compact_context}
```"""


def parse_weekly_review_response(response: str) -> Optional[dict[str, Any]]:
    match = _REVIEW_JSON_RE.search(response)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _fallback_review(context: dict[str, Any], reason: str) -> dict[str, Any]:
    weekly = context["weekly_metrics"]
    logs = context["log_context"]

    recommendation = "continue"
    headline = "Current strategy can continue unchanged."
    summary = "Weekly activity does not show a strategy failure that warrants immediate changes."
    working = ["Paper-mode stack remains in operator-controlled mode."]
    degrading = []
    changes = ["No bounded strategy changes recommended this week."]
    rationale = []
    risks = []
    operator_action = "keep_current_algo"
    should_revalidate = False

    if weekly["closed_trade_count"] == 0:
        working.append("No forced trading behaviour was observed during a low-opportunity stretch.")
        rationale.append("Zero weekly trades can be acceptable when edge is weak.")
    if logs["fear_greed"] is not None:
        working.append(
            f"Macro sentiment is currently {logs['fear_greed']['value']} ({logs['fear_greed']['label']})."
        )

    if weekly["closed_trade_count"] >= 4 and weekly["weekly_pnl_abs"] < 0:
        recommendation = "research_recommended"
        headline = "Performance is soft enough to justify research, not live mutation."
        summary = (
            "The last week closed negative with a meaningful sample of trades. "
            "This warrants a research cycle, but not an on-the-fly production change."
        )
        changes = [
            "Run backtest and true rolling walk-forward on the current futures-paper config before editing parameters.",
            "Review pair selection and entry strictness before widening activity targets.",
        ]
        rationale.append("Negative weekly PnL with several trades is enough to justify bounded research.")
        operator_action = "open_research_candidate"
        should_revalidate = True

    if logs["oi_failures"] or logs["liquidation_failures"]:
        recommendation = "monitor" if recommendation == "continue" else recommendation
        degrading.append(
            f"Market microstructure feeds are degraded (OI failures={logs['oi_failures']}, liquidation failures={logs['liquidation_failures']})."
        )
        changes.insert(0, "Fix broken OI/liquidation data feeds before tuning the strategy itself.")
        rationale.append("Broken telemetry reduces confidence in any strategy judgement.")
        risks.append("Signal-gate observability is incomplete while Bybit OI/liquidation fetches fail.")

    if logs["llm_disabled"]:
        degrading.append("LLM review/sentiment gate is disabled because ANTHROPIC_API_KEY is missing.")
        risks.append("AI sentiment and weekly review quality will degrade until Anthropic access is configured.")

    if recommendation == "continue" and (logs["oi_failures"] or logs["liquidation_failures"]):
        summary = (
            "The strategy itself does not need a bounded change from this snapshot, "
            "but supporting data quality should be fixed before deeper optimisation work."
        )

    parsed = {
        "recommendation": recommendation,
        "headline": headline,
        "summary": summary,
        "what_is_working": working,
        "what_is_degrading": degrading or ["No material degradation detected in the weekly snapshot."],
        "recommended_changes": changes,
        "rationale": rationale or ["Fallback review used because the LLM was unavailable."],
        "risks": risks or [reason],
        "should_revalidate": should_revalidate,
        "operator_action": operator_action,
        "confidence": 0.42,
    }
    return _build_review_artifact(context, parsed, _render_fallback_markdown(parsed), model="fallback-local")


def _build_review_artifact(
    context: dict[str, Any],
    parsed: dict[str, Any],
    raw_response: str,
    *,
    model: str,
) -> dict[str, Any]:
    generated_at = context["generated_at"]
    summary = parsed.get("summary", "").strip()
    recommendation = str(parsed.get("recommendation", "monitor")).strip().lower()
    recommended_changes = [str(item).strip() for item in parsed.get("recommended_changes", []) if str(item).strip()]
    report_markdown = _strip_review_json_block(raw_response)

    operator_decision = None
    review_id = hashlib.sha256(
        f"{context['strategy_id']}:{generated_at}:{recommendation}".encode("utf-8")
    ).hexdigest()[:16]

    return {
        "review_id": review_id,
        "generated_at": generated_at,
        "period_start": context["period_start"],
        "period_end": context["period_end"],
        "strategy_id": context["strategy_id"],
        "model": model,
        "recommendation": recommendation,
        "headline": parsed.get("headline", ""),
        "summary": summary,
        "what_is_working": parsed.get("what_is_working", []),
        "what_is_degrading": parsed.get("what_is_degrading", []),
        "recommended_changes": recommended_changes,
        "rationale": parsed.get("rationale", []),
        "risks": parsed.get("risks", []),
        "should_revalidate": bool(parsed.get("should_revalidate", False)),
        "operator_action": parsed.get("operator_action", "keep_current_algo"),
        "confidence": parsed.get("confidence", 0.0),
        "operator_decision": operator_decision,
        "context": context,
        "report_markdown": report_markdown,
    }


def _strip_review_json_block(response: str) -> str:
    clean = _REVIEW_JSON_RE.sub("", response).strip()
    return clean


def _render_fallback_markdown(parsed: dict[str, Any]) -> str:
    sections = [
        f"## Weekly Recommendation\n{parsed['recommendation']}: {parsed['headline']}",
        "## Executive Summary\n" + parsed["summary"],
        "## What Is Working\n" + "\n".join(f"- {item}" for item in parsed["what_is_working"]),
        "## What Is Degrading\n" + "\n".join(f"- {item}" for item in parsed["what_is_degrading"]),
        "## Recommended Changes\n" + "\n".join(f"- {item}" for item in parsed["recommended_changes"]),
        "## Operator Note\n" + (
            "This review used fallback heuristics because the weekly Claude call was unavailable. "
            "Treat the recommendation as conservative triage rather than deep research."
        ),
    ]
    return "\n\n".join(sections)


def _write_audit_event(event_type: str, action: str, details: dict[str, Any]) -> None:
    try:
        from custom_app.audit import AuditLogger, AuditEventType

        if event_type == "review.weekly_run":
            event = AuditEventType.WEEKLY_REVIEW_RUN
        elif event_type == "review.weekly_decision":
            event = AuditEventType.WEEKLY_REVIEW_DECISION
        else:
            return

        AuditLogger.get_instance().log_event(
            event_type=event,
            actor="weekly_review",
            action=action,
            details=details,
            outcome=event_type,
        )
    except Exception:
        pass


def _hash_file(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text.replace(" ", "T"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
