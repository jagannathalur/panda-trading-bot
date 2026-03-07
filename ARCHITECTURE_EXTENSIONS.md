# ARCHITECTURE_EXTENSIONS.md

Documents the boundary between upstream Freqtrade and our custom platform layer.

## Layer Model

```
┌─────────────────────────────────────────────────────┐
│                 Operator / Ops Team                  │
│         (paper/real mode control, approvals)         │
├─────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────┐  │
│  │           Panda Platform Layer                │  │
│  │  ┌─────────────┐  ┌──────────────────────┐   │  │
│  │  │ mode_control│  │     promotion         │   │  │
│  │  │  (startup   │  │  (draft→full_live     │   │  │
│  │  │   guard)    │  │   state machine)      │   │  │
│  │  └─────────────┘  └──────────────────────┘   │  │
│  │  ┌─────────────┐  ┌──────────────────────┐   │  │
│  │  │ risk_layer  │  │     no_alpha          │   │  │
│  │  │  (veto      │  │  (edge gating)        │   │  │
│  │  │   engine)   │  │                       │   │  │
│  │  └─────────────┘  └──────────────────────┘   │  │
│  │  ┌─────────────┐  ┌──────────────────────┐   │  │
│  │  │  dashboard  │  │     validation        │   │  │
│  │  │ (read-only  │  │  (backtest+wf+shadow) │   │  │
│  │  │  mode view) │  │                       │   │  │
│  │  └─────────────┘  └──────────────────────┘   │  │
│  │  ┌─────────────┐  ┌──────────────────────┐   │  │
│  │  │    audit    │  │      metrics          │   │  │
│  │  │ (append-    │  │  (prometheus/grafana) │   │  │
│  │  │  only log)  │  │                       │   │  │
│  │  └─────────────┘  └──────────────────────┘   │  │
│  └───────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────┐  │
│  │              Freqtrade Core                   │  │
│  │  exchange │ execution │ strategy │ backtest   │  │
│  │  web UI (FreqUI) │ persistence │ data         │  │
│  └───────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│          Exchange (Bybit via CCXT)                   │
└─────────────────────────────────────────────────────┘
```

## Integration Points

### 1. Startup Hook
- `custom_app/mode_control/startup.py` runs BEFORE Freqtrade's worker starts.
- Validates mode, checks operator gates, writes audit log entry.
- Aborts with non-zero exit if requirements not met.

### 2. Strategy Callbacks (Freqtrade-native extension points)
- `confirm_trade_entry` — delegates to `risk_layer` + `no_alpha` gate
- `custom_stoploss` — delegates to `risk_layer`
- `custom_exit` — delegates to `risk_layer`
- These live in `custom_app/strategy_extensions/` and are mixed into strategies

### 3. Config Layering
- Freqtrade config: `configs/base.yaml` → `configs/paper.yaml` or `configs/real.yaml`
- Our extensions: `configs/risk.yaml`, `configs/promotion.yaml` (loaded by our modules)
- Custom keys namespaced under `panda_*` to avoid conflicts

### 4. Dashboard (separate service)
- Freqtrade's FreqUI runs on its own port (default 8081)
- Our dashboard runs as a separate FastAPI service (default 8080)
- Dashboard reads Freqtrade state via its REST API — no internal coupling

### 5. Metrics
- `custom_app/metrics/` exposes Prometheus metrics on a separate port
- Grafana dashboards in `configs/grafana/` consume these

## Upstream Files Modified

| File | Modification | Reason | Upgrade Risk |
|------|-------------|--------|-------------|
| (none) | — | — | — |

## Custom Files by Module

### mode_control/
| File | Purpose |
|------|---------|
| `config.py` | TradingMode enum, TradingModeConfig dataclass |
| `guard.py` | ModeGuard singleton — enforces immutability |
| `startup.py` | Startup validation — runs before worker |
| `__init__.py` | Public API |

### risk_layer/
| File | Purpose |
|------|---------|
| `engine.py` | RiskEngine — central veto logic |
| `limits.py` | RiskLimits dataclass |
| `kill_switch.py` | Kill switch + emergency flatten |
| `sizing.py` | Volatility-adjusted position sizing |
| `__init__.py` | Public API |

### promotion/
| File | Purpose |
|------|---------|
| `states.py` | PromotionState enum + transition rules |
| `artifacts.py` | PromotionArtifact — validation evidence |
| `pipeline.py` | PromotionPipeline state machine |
| `registry.py` | StrategyRegistry — tracks all strategies |
| `__init__.py` | Public API |

### no_alpha/
| File | Purpose |
|------|---------|
| `gate.py` | NoAlphaGate — blocks trades when edge is weak |
| `signals.py` | Edge metric computation |
| `__init__.py` | Public API |

### dashboard/
| File | Purpose |
|------|---------|
| `app.py` | FastAPI application |
| `api.py` | REST API endpoints (mode display = read-only) |
| `auth.py` | Authentication |
| `views/*.py` | Panel view logic |
| `components/*.py` | Reusable components |

### audit/
| File | Purpose |
|------|---------|
| `events.py` | AuditEventType enum + AuditEvent dataclass |
| `logger.py` | AuditLogger singleton — append-only |
| `storage.py` | Query and export utilities |
| `__init__.py` | Public API |

### validation/
| File | Purpose |
|------|---------|
| `orchestrator.py` | Runs backtest → walk-forward → shadow pipeline |
| `backtest.py` | Deterministic backtest runner |
| `walk_forward.py` | Walk-forward validation |
| `shadow.py` | Paper shadow mode runner |

### metrics/
| File | Purpose |
|------|---------|
| `collector.py` | MetricsCollector |
| `prometheus.py` | Prometheus exporter |
| `drift.py` | Live-vs-backtest and live-vs-paper drift |
