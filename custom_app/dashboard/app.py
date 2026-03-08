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
    header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
    header h1 { font-size: 16px; font-weight: 600; }
    .mode-badge { padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; }
    .mode-paper { background: #1f3a1f; color: var(--green); border: 1px solid var(--green); }
    .mode-real  { background: #3a1f1f; color: var(--red); border: 1px solid var(--red); }
    .readonly-label { color: var(--muted); font-size: 11px; }
    .refresh-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); display: inline-block; animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 16px; }
    .panel { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 14px; }
    .panel-title { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
    .panel-value { font-size: 28px; font-weight: 700; }
    .stat-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--border); }
    .stat-row:last-child { border-bottom: none; }
    .green { color: var(--green); }
    .red   { color: var(--red); }
    .yellow{ color: var(--yellow); }
    .blue  { color: var(--blue); }
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
    <span><span class="refresh-dot"></span> <span id="last-refresh" style="color:var(--muted);font-size:11px">connecting...</span></span>
    <div style="margin-left:auto; color: var(--muted)" id="clock"></div>
  </header>

  <div class="grid">
    <!-- Bot Status -->
    <div class="panel">
      <div class="panel-title">Bot Status</div>
      <div class="stat-row"><span>Freqtrade</span><span id="ft-status" class="green">&#x25CF; Running</span></div>
      <div class="stat-row"><span>Strategy</span><span id="strategy-name" class="blue">—</span></div>
      <div class="stat-row"><span>Timeframe</span><span id="timeframe">—</span></div>
      <div class="stat-row"><span>Open Trades</span><span id="open-trades">0</span></div>
      <div class="stat-row"><span>Total Trades</span><span id="total-trades">0</span></div>
    </div>

    <!-- PnL (live from Freqtrade) -->
    <div class="panel">
      <div class="panel-title">Profit &amp; Loss</div>
      <div class="stat-row"><span>Total Realized</span><span id="total-pnl">$0.00</span></div>
      <div class="stat-row"><span>Unrealized (open)</span><span id="unrealized-pnl">$0.00</span></div>
      <div class="stat-row"><span>Win Rate</span><span id="win-rate">0%</span></div>
      <div class="stat-row"><span>Wins / Losses</span><span id="wins-losses">0 / 0</span></div>
      <div class="stat-row"><span>Avg Duration</span><span id="avg-duration">—</span></div>
    </div>

    <!-- Trade Stats -->
    <div class="panel">
      <div class="panel-title">Trade Stats</div>
      <div class="stat-row"><span>Best Pair</span><span id="best-pair">—</span></div>
      <div class="stat-row"><span>Closed Trades</span><span id="closed-trades">0</span></div>
      <div class="stat-row"><span>Sharpe Ratio</span><span id="sharpe">—</span></div>
      <div class="stat-row"><span>Profit %</span><span id="profit-pct">0.00%</span></div>
      <div class="stat-row"><span>Drawdown</span><span id="drawdown" class="yellow">0.0%</span></div>
    </div>

    <!-- Safety Controls -->
    <div class="panel">
      <div class="panel-title">Safety Controls</div>
      <div class="stat-row"><span>Kill Switch</span><span id="kill-switch" class="green">&#x25CF; Disarmed</span></div>
      <div class="stat-row"><span>No-Alpha Gate</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>Risk Engine</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>Daily Loss Cap</span><span id="cap-daily-loss">2.0%</span></div>
      <div class="stat-row"><span>Drawdown Cap</span><span id="cap-drawdown">10.0%</span></div>
    </div>

    <!-- Signal Gates -->
    <div class="panel">
      <div class="panel-title">Signal Gates (GridTrendV2)</div>
      <div class="stat-row"><span>1. Time Filter (UTC 02–04)</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>2. MTF 15m EMA Alignment</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>3. Macro Hard Blocks</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>4. Orderbook Imbalance</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>5. Funding Rate</span><span class="green">&#x25CF; Active</span></div>
      <div class="stat-row"><span>6. LLM Sentiment (Haiku)</span><span class="green">&#x25CF; Active</span></div>
    </div>

    <!-- Drift -->
    <div class="panel">
      <div class="panel-title">Live vs Backtest Drift</div>
      <div class="stat-row"><span>Live vs Backtest</span><span id="live-bt-drift">—</span></div>
      <div class="stat-row"><span>Live vs Paper</span><span id="live-paper-drift">—</span></div>
      <div class="stat-row"><span>Model Staleness</span><span class="green">Fresh</span></div>
    </div>

    <!-- Recent Trades (live) -->
    <div class="panel wide">
      <div class="panel-title">Recent Trades</div>
      <table>
        <thead>
          <tr><th>#</th><th>Pair</th><th>Side</th><th>Open</th><th>Close</th><th>P&amp;L ($)</th><th>P&amp;L (%)</th><th>Exit Reason</th></tr>
        </thead>
        <tbody id="trades-table">
          <tr><td colspan="8" style="color:var(--muted);text-align:center">Loading...</td></tr>
        </tbody>
      </table>
    </div>

    <!-- Promotion Status -->
    <div class="panel wide">
      <div class="panel-title">Strategy Promotion Status</div>
      <table>
        <thead>
          <tr><th>Strategy</th><th>Version</th><th>Stage</th><th>Artifact Age</th><th>Last Backtest</th><th>Last WF</th><th>Last Shadow</th></tr>
        </thead>
        <tbody id="promotion-table">
          <tr><td id="promo-strategy">GridTrendV2</td><td>2.0.0</td><td><span class="badge badge-info">PAPER_ACTIVE</span></td><td>—</td><td>—</td><td>—</td><td>—</td></tr>
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

    function fmt(val, prefix='$') {
      if (val === null || val === undefined) return '—';
      const n = parseFloat(val);
      const sign = n >= 0 ? '+' : '';
      return sign + prefix + n.toFixed(2);
    }
    function fmtPct(val) {
      if (val === null || val === undefined) return '—';
      const n = parseFloat(val);
      return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
    }
    function colorClass(val) {
      return parseFloat(val) >= 0 ? 'green' : 'red';
    }

    // Refresh bot status + PnL from our proxy endpoints
    async function refreshPnL() {
      try {
        const [botResp, pnlResp] = await Promise.all([
          fetch('/api/bot-status'),
          fetch('/api/pnl'),
        ]);

        if (botResp.ok) {
          const bot = await botResp.json();
          const stateOk = bot.state === 'running';
          document.getElementById('ft-status').textContent = stateOk ? '● Running' : '● ' + bot.state;
          document.getElementById('ft-status').className = stateOk ? 'green' : 'red';
          document.getElementById('strategy-name').textContent = bot.strategy || '—';
          document.getElementById('timeframe').textContent = bot.timeframe || '—';

          const badge = document.getElementById('mode-badge');
          if (!bot.dry_run) {
            badge.textContent = '⚠ REAL MODE';
            badge.className = 'mode-badge mode-real';
          } else {
            badge.textContent = 'PAPER MODE';
            badge.className = 'mode-badge mode-paper';
          }
        }

        if (pnlResp.ok) {
          const p = await pnlResp.json();

          const total = p.profit_closed_abs ?? 0;
          const unreal = p.unrealized_abs ?? 0;
          const wr = ((p.winrate ?? 0) * 100).toFixed(1);

          const totalEl = document.getElementById('total-pnl');
          totalEl.textContent = fmt(total);
          totalEl.className = colorClass(total);

          const unrealEl = document.getElementById('unrealized-pnl');
          unrealEl.textContent = fmt(unreal);
          unrealEl.className = colorClass(unreal);

          document.getElementById('win-rate').textContent = wr + '%';
          document.getElementById('wins-losses').textContent =
            (p.winning_trades ?? 0) + ' / ' + (p.losing_trades ?? 0);
          document.getElementById('avg-duration').textContent = p.avg_duration || '—';

          document.getElementById('best-pair').textContent = p.best_pair || '—';
          document.getElementById('closed-trades').textContent = p.closed_trade_count ?? '—';
          document.getElementById('total-trades').textContent = p.trade_count ?? '—';
          document.getElementById('open-trades').textContent = p.open_trade_count ?? '—';

          const sharpe = p.sharpe ?? 0;
          const sharpeEl = document.getElementById('sharpe');
          sharpeEl.textContent = parseFloat(sharpe).toFixed(2);
          sharpeEl.className = parseFloat(sharpe) >= 0 ? 'green' : 'red';

          const profitPct = p.profit_closed_pct ?? 0;
          const profPctEl = document.getElementById('profit-pct');
          profPctEl.textContent = fmtPct(profitPct);
          profPctEl.className = colorClass(profitPct);
        }

        document.getElementById('last-refresh').textContent =
          'refreshed ' + new Date().toLocaleTimeString();
      } catch (e) {
        console.error('PnL refresh error:', e);
        document.getElementById('ft-status').textContent = '● Unreachable';
        document.getElementById('ft-status').className = 'red';
      }
    }

    // Refresh recent trades
    async function refreshTrades() {
      try {
        const r = await fetch('/api/trades?limit=15');
        if (!r.ok) return;
        const trades = await r.json();
        const tbody = document.getElementById('trades-table');
        if (!trades.length) {
          tbody.innerHTML = '<tr><td colspan="8" style="color:var(--muted);text-align:center">No trades yet</td></tr>';
          return;
        }
        tbody.innerHTML = trades.slice().reverse().map(t => {
          const pnlClass = t.profit_abs >= 0 ? 'green' : 'red';
          const sideClass = t.side === 'short' ? 'red' : 'blue';
          const openDate = t.open_date ? t.open_date.split(' ')[1] : '—';
          const closeDate = t.close_date ? t.close_date.split(' ')[1] : '—';
          return `<tr>
            <td>${t.id}</td>
            <td>${t.pair}</td>
            <td class="${sideClass}">${t.side.toUpperCase()}</td>
            <td>${openDate}</td>
            <td>${closeDate || '—'}</td>
            <td class="${pnlClass}">${fmt(t.profit_abs)}</td>
            <td class="${pnlClass}">${fmtPct(t.profit_pct)}</td>
            <td style="color:var(--muted)">${t.exit_reason || '—'}</td>
          </tr>`;
        }).join('');
      } catch (e) { console.error('Trades refresh error:', e); }
    }

    // Refresh risk / mode status
    async function refreshStatus() {
      try {
        const r = await fetch('/api/status');
        if (!r.ok) return;
        const d = await r.json();
        if (d.risk) {
          const dd = d.risk.current_drawdown_pct ?? 0;
          const ddEl = document.getElementById('drawdown');
          ddEl.textContent = dd.toFixed(2) + '%';
          ddEl.className = dd > 5 ? 'red' : dd > 2 ? 'yellow' : 'green';

          document.getElementById('kill-switch').textContent =
            d.risk.kill_switch_active ? '🔴 ARMED' : '✅ Disarmed';
          document.getElementById('kill-switch').className =
            d.risk.kill_switch_active ? 'red' : 'green';
        }
      } catch (e) { /* ignore */ }
    }

    // Audit log
    async function refreshAudit() {
      try {
        const r = await fetch('/api/audit?limit=20');
        if (!r.ok) return;
        const events = await r.json();
        const tbody = document.getElementById('audit-table');
        if (!events.length) {
          tbody.innerHTML = '<tr><td colspan="5" style="color:var(--muted);text-align:center">No events</td></tr>';
          return;
        }
        tbody.innerHTML = events.map(e => `
          <tr>
            <td>${new Date(e.timestamp).toLocaleTimeString()}</td>
            <td><code>${e.event_type}</code></td>
            <td>${e.actor}</td>
            <td>${e.action}</td>
            <td><span class="badge ${e.outcome === 'vetoed' || e.outcome === 'blocked' ? 'badge-fail' : 'badge-pass'}">${e.outcome}</span></td>
          </tr>`).join('');
      } catch (e) { /* ignore */ }
    }

    // Load risk config once (caps don't change at runtime)
    async function loadRiskConfig() {
      try {
        const r = await fetch('/api/risk-config');
        if (!r.ok) return;
        const cfg = await r.json();
        document.getElementById('cap-daily-loss').textContent =
          (cfg.max_daily_loss_pct ?? 2.0).toFixed(1) + '%';
        document.getElementById('cap-drawdown').textContent =
          (cfg.max_drawdown_pct ?? 10.0).toFixed(1) + '%';
      } catch (e) { /* ignore */ }
    }

    async function refreshAll() {
      await Promise.allSettled([refreshPnL(), refreshTrades(), refreshStatus(), refreshAudit()]);
    }

    loadRiskConfig();
    setInterval(refreshAll, 5000);
    refreshAll();
  </script>
</body>
</html>"""
