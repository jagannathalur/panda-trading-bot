# Skill: Dashboard Builder

Use when adding or modifying dashboard panels.

## CRITICAL: Never Add Mode Toggle

The dashboard MUST NOT contain a runtime paper/live toggle.

Mode is displayed as a READ-ONLY badge. If you find yourself adding:
- A toggle switch for mode
- A button that calls a mode-change API
- A form with a `mode` parameter

STOP. These are forbidden. Mode can only be changed by operator restart.

## Adding a New Panel

### Backend (api.py)
```python
@router.get("/new-metric")
async def get_new_metric() -> dict:
    """Get new metric. All data is read-only."""
    return {"value": ..., "timestamp": _now_iso()}
```

### Frontend (app.py HTML)
```html
<div class="panel">
  <div class="panel-title">New Metric</div>
  <div class="stat-row">
    <span>Label</span>
    <span id="new-metric-value">Loading...</span>
  </div>
</div>
```

```javascript
// In refreshData()
const r = await fetch('/api/new-metric');
const d = await r.json();
document.getElementById('new-metric-value').textContent = d.value;
```

## Panel Design Guidelines

- Dark theme: `var(--bg)`, `var(--surface)`, `var(--border)`
- Green for positive/healthy: `var(--green)`
- Red for negative/critical: `var(--red)`
- Yellow for warning: `var(--yellow)`
- All data is read-only — no forms except search/filter
- Refresh every 5-10 seconds for live data

## Required Panels (already built)

- Bot status (Freqtrade, exchange, WebSocket, API)
- Trading mode (READ-ONLY badge)
- PnL (daily, weekly, total, unrealized, fees)
- Risk (drawdown, exposure, leverage, open trades, losses)
- Safety controls (kill switch, no-alpha, risk engine)
- Execution quality (fill ratio, rejection rate, latency, slippage)
- Live vs backtest drift
- Promotion status table
- Audit log events table

## Grafana Dashboards

For time-series data and alerting, use Grafana:
- Dashboards: `configs/grafana/dashboards/`
- Datasources: `configs/grafana/datasources/`
- Alerts: `configs/grafana/alerts/`

All Grafana panels consume Prometheus metrics from `custom_app/metrics/collector.py`.
