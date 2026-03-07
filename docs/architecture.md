# Architecture

## Overview

Panda Trading Bot is built as a thin extension layer on top of Freqtrade. Freqtrade handles exchange connectivity, order execution, strategy loading, backtesting, and the built-in FreqUI dashboard. Our custom layer adds governance, risk, validation, and observability.

## Component Map

```
freqtrade/         ← Upstream Freqtrade (minimal modifications)
custom_app/
  mode_control/   ← Operator-only mode lock (CRITICAL SAFETY)
  risk_layer/     ← Veto-power risk engine
  no_alpha/       ← Edge gating ("do nothing" logic)
  promotion/      ← Strategy promotion state machine
  validation/     ← Backtest + WF + shadow orchestration
  audit/          ← Append-only audit trail
  dashboard/      ← FastAPI operations dashboard
  metrics/        ← Prometheus metrics
  config/         ← Config hashing and change detection
  replay/         ← Order reconciliation
configs/           ← Layered configs (base, paper, real, risk, ...)
scripts/           ← Operational scripts
tests/             ← Test suite
docs/              ← Documentation
```

## Integration Pattern

We use Freqtrade's native extension points:
- **Strategy callbacks**: `confirm_trade_entry`, `custom_stoploss`, `custom_exit`
- **Config layering**: `--config base.yaml --config paper.yaml`
- **REST API**: Dashboard reads Freqtrade state via its public REST API
- **CLI commands**: `backtesting`, `hyperopt`, `trade` called via subprocess

We do NOT:
- Modify Freqtrade's core modules
- Intercept Freqtrade's internal Python calls
- Replace Freqtrade's persistence or exchange layers

## Mode Control Flow

```
Process Start
    │
    ▼
validate_startup_mode()          ← reads TRADING_MODE from env
    │
    ├── PAPER: dry_run=True → write audit → ModeGuard.initialize(paper)
    │
    └── REAL:  check all gates → write audit → ModeGuard.initialize(real)
                │
                ├── Gate 1: REAL_TRADING_ACKNOWLEDGED=true
                ├── Gate 2: OPERATOR_APPROVAL_TOKEN valid
                └── Gate 3: dry_run=false in config

    │
    ▼
ModeGuard (singleton, frozen)    ← IMMUTABLE for process lifetime
    │
    └── Any attempt_mode_change() → ModeViolationError (audited)
```

## Trade Intent Flow

```
Strategy signal
    │
    ▼
confirm_trade_entry callback
    │
    ├── NoAlphaGate.evaluate(metrics)    ← blocks if edge too weak
    │       │ pass
    ▼       ▼
    RiskEngine.evaluate(intent)          ← veto if any limit breached
    │       │ pass
    ▼       ▼
    Freqtrade executes order             ← exchange via CCXT
```
