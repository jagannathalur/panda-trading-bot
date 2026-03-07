"""
Dashboard application entry point.

A real operations dashboard for the Panda Trading Bot.
Panels: bot status, trading mode (READ-ONLY), PnL, risk, execution quality,
        promotion status, live vs backtest drift, audit log, incidents.

Mode display is READ-ONLY. No runtime paper/live toggle exists.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from custom_app.dashboard.api import router as api_router
from custom_app.dashboard.auth import verify_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    print("[Dashboard] Starting Panda Trading Bot Dashboard...")
    yield
    print("[Dashboard] Shutting down dashboard.")


app = FastAPI(
    title="Panda Trading Bot — Operations Dashboard",
    description="Technical operations dashboard. Trading mode is READ-ONLY.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/", response_class=HTMLResponse)
async def dashboard_home():
    """Main dashboard page."""
    return HTMLResponse(content=_render_dashboard_html())


def _render_dashboard_html() -> str:
    """Render the main dashboard HTML."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Panda Trading Bot — Operations Dashboard</title>
  <style>
    :root {
      --bg: #0d1117; --surface: #161b22; --border: #30363d;
      --text: #e6edf3; --muted: #8b949e;
      --green: #2ea043; --red: #da3633; --yellow: #d29922;
      --blue: #1f6feb; --orange: #e3b341;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }
    header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; gap: 16px; }
    header h1 { font-size: 16px; font-weight: 600; }
    .mode-badge { padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }
    .mode-paper { background: #1f3a1f; color: var(--green); border: 1px solid var(--green); }
    .mode-real  { background: #3a1f1f; color: var(--red); border: 1px solid var(--red); }
    .readonly-label { color: var(--muted); font-size: 11px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 16px; }
    .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 14px; }
    .panel-title { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
    .panel-value { font-size: 28px; font-weight: 700; }
    .panel-value.green { color: var(--green); }
    .panel-value.red { color: var(--red); }
    .panel-value.yellow { color: var(--yellow); }
    .stat-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--border); }
    .stat-row:last-child { border-bottom: none; }
    .wide { grid-column: span 2; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th { color: var(--muted); text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); font-weight: 500; }
    td { padding: 5px 8px; border-bottom: 1px solid var(--border); }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-weight: 600; }
    .badge-pass { background: #1f3a1f; color: var(--green); }
    .badge-fail { background: #3a1f1f; color: var(--red); }
    .badge-warn { background: #3a2f1f; color: var(--yellow); }
    .badge-info { background: #1f2a3a; color: var(--blue); }
  </style>
</head>
<body>
  <header>
    <h1>&#x1F43C; Panda Trading Bot</h1>
    <div id="mode-badge" class="mode-badge mode-paper">PAPER MODE</div>
    <span class="readonly-label">&#x1F512; Mode display is read-only</span>
    <div style="margin-left:auto; color: var(--muted)" id="clock"></div>
  </header>

  <div class="grid">
    <!-- Bot Status -->
    <div class="panel">
      <div class="panel-title">Bot Status</div>
      <div class="stat-row"><span>Freqtrade</span><span id="ft-status" class="green">&#x25CF; Running</span></div>
      <div class="stat-row"><span>Exchange</span><span id="ex-status" class="green">&#x25CF; Connected</span></div>
      <div class="stat-row"><span>WebSocket</span><span id="ws-status" class="green">&#x25CF; Healthy</span></div>
      <div class="stat-row"><span>API</span><span id="api-status" class="green">&#x25CF; OK</span></div>
      <div class="stat-row"><span>Strategy</span><span id="strategy-name">GridTrendV1</span></div>
    </div>

    <!-- PnL -->
    <div class="panel">
      <div class="panel-title">PnL</div>
      <div class="stat-row"><span>Daily</span><span id="daily-pnl" class="green">+$0.00</span></div>
      <div class="stat-row"><span>Weekly</span><span id="weekly-pnl" class="green">+$0.00</span></div>
      <div class="stat-row"><span>Total Realized</span><span id="total-pnl">$0.00</span></div>
      <div class="stat-row"><span>Unrealized</span><span id="unrealized-pnl">$0.00</span></div>
      <div class="stat-row"><span>Fees Paid</span><span id="fees-paid" class="red">$0.00</span></div>
    </div>

    <!-- Risk -->
    <div class="panel">
      <div class="panel-title">Risk</div>
      <div class="stat-row"><span>Drawdown</span><span id="drawdown" class="yellow">0.0%</span></div>
      <div class="stat-row"><span>Exposure</span><span id="exposure">0.0%</span></div>
      <div class="stat-row"><span>Leverage</span><span id="leverage">1.0x</span></div>
      <div class="stat-row"><span>Open Trades</span><span id="open-trades">0</span></div>
      <div class="stat-row"><span>Consec. Losses</span><span id="consec-losses">0</span></div>
    </div>

    <!-- Kill Switch -->
    <div class="panel">
      <div class="panel-title">Safety Controls</div>
      <div class="stat-row"><span>Kill Switch</span><span id="kill-switch" class="green">&#x25CF; Disarmed</span></div>
      <div class="stat-row"><span>No-Alpha Gate</span><span id="no-alpha" class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>Risk Engine</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>Daily Loss Cap</span><span>2.0%</span></div>
      <div class="stat-row"><span>Drawdown Cap</span><span>10.0%</span></div>
    </div>

    <!-- Execution Quality -->
    <div class="panel">
      <div class="panel-title">Execution Quality</div>
      <div class="stat-row"><span>Fill Ratio</span><span id="fill-ratio" class="green">100%</span></div>
      <div class="stat-row"><span>Rejection Rate</span><span id="reject-rate">0%</span></div>
      <div class="stat-row"><span>Avg Latency</span><span id="latency">0ms</span></div>
      <div class="stat-row"><span>Avg Slippage</span><span id="slippage">0.0 bps</span></div>
      <div class="stat-row"><span>Orders Today</span><span id="orders-today">0</span></div>
    </div>

    <!-- Drift -->
    <div class="panel">
      <div class="panel-title">Live vs Backtest Drift</div>
      <div class="stat-row"><span>Live vs Backtest</span><span id="live-bt-drift">0.0%</span></div>
      <div class="stat-row"><span>Live vs Paper</span><span id="live-paper-drift">0.0%</span></div>
      <div class="stat-row"><span>Challenger vs Champion</span><span id="chall-champ">0.0%</span></div>
      <div class="stat-row"><span>Model Staleness</span><span class="green">Fresh</span></div>
    </div>

    <!-- Promotion Status -->
    <div class="panel wide">
      <div class="panel-title">Strategy Promotion Status</div>
      <table>
        <thead>
          <tr><th>Strategy</th><th>Version</th><th>Stage</th><th>Artifact Age</th><th>Last Backtest</th><th>Last WF</th><th>Last Shadow</th></tr>
        </thead>
        <tbody id="promotion-table">
          <tr><td>GridTrendV1</td><td>1.0.0</td><td><span class="badge badge-info">DRAFT</span></td><td>—</td><td>—</td><td>—</td><td>—</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Audit Log -->
    <div class="panel wide">
      <div class="panel-title">Recent Audit Events</div>
      <table>
        <thead>
          <tr><th>Timestamp</th><th>Event Type</th><th>Actor</th><th>Action</th><th>Outcome</th></tr>
        </thead>
        <tbody id="audit-table">
          <tr><td colspan="5" style="color:var(--muted); text-align:center">Loading...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    // Clock
    function updateClock() {
      document.getElementById('clock').textContent = new Date().toUTCString();
    }
    setInterval(updateClock, 1000);
    updateClock();

    // Refresh dashboard data every 5 seconds
    async function refreshData() {
      try {
        const r = await fetch('/api/status');
        if (!r.ok) return;
        const d = await r.json();

        // Mode badge
        const badge = document.getElementById('mode-badge');
        if (d.trading_mode === 'real') {
          badge.textContent = '⚠ REAL MODE';
          badge.className = 'mode-badge mode-real';
        } else {
          badge.textContent = 'PAPER MODE';
          badge.className = 'mode-badge mode-paper';
        }

        // Risk
        if (d.risk) {
          document.getElementById('drawdown').textContent = d.risk.current_drawdown_pct?.toFixed(2) + '%';
          document.getElementById('exposure').textContent = d.risk.total_exposure_pct?.toFixed(1) + '%';
          document.getElementById('open-trades').textContent = d.risk.open_trade_count;
          document.getElementById('kill-switch').textContent = d.risk.kill_switch_active ? '🔴 ARMED' : '✅ Disarmed';
          document.getElementById('kill-switch').className = d.risk.kill_switch_active ? 'red' : 'green';
        }
      } catch (e) { console.error('Dashboard refresh error:', e); }

      // Audit log
      try {
        const r = await fetch('/api/audit?limit=20');
        if (r.ok) {
          const events = await r.json();
          const tbody = document.getElementById('audit-table');
          if (events.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center">No events</td></tr>';
          } else {
            tbody.innerHTML = events.map(e => `
              <tr>
                <td>${new Date(e.timestamp).toLocaleTimeString()}</td>
                <td><code>${e.event_type}</code></td>
                <td>${e.actor}</td>
                <td>${e.action}</td>
                <td><span class="badge ${e.outcome === 'vetoed' || e.outcome === 'blocked' ? 'badge-fail' : 'badge-pass'}">${e.outcome}</span></td>
              </tr>`).join('');
          }
        }
      } catch (e) { console.error('Audit refresh error:', e); }
    }

    setInterval(refreshData, 5000);
    refreshData();
  </script>
</body>
</html>"""
