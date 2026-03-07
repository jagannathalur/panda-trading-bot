# Panda Trading Bot

A production-grade algorithmic trading platform built on top of [Freqtrade](https://github.com/freqtrade/freqtrade), with a strict operator-controlled governance layer, rich safety controls, and a comprehensive technical dashboard.

## What This Is

**Freqtrade provides (reused as-is):**
- Exchange connectivity (CCXT), including Bybit
- Order execution engine
- Dry-run / live mode
- Built-in backtesting and hyperopt
- Strategy loading and customization
- Built-in Web UI (FreqUI)

**This repo adds:**
- **Operator-only mode lock** — paper/real trading cannot be changed at runtime
- **Validation & promotion pipeline** — backtest → walk-forward → paper shadow before live
- **Custom risk engine** — per-trade, daily, drawdown, leverage, exposure controls with veto power
- **No-alpha gate** — explicit "do nothing" logic when expected edge is too weak
- **Bounded self-correction** — champion/challenger framework, hard parameter bounds
- **Technical dashboard** — operations-grade view of bot health, PnL, risk, execution quality
- **Full audit trail** — every critical action is logged durably

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                 Operator / Ops Team                  │
├─────────────────────────────────────────────────────┤
│              Panda Platform Layer                    │
│  mode_control │ promotion │ risk_layer │ dashboard   │
│  no_alpha     │ audit     │ validation │ metrics     │
├─────────────────────────────────────────────────────┤
│                Freqtrade Core                        │
│  exchange │ execution │ strategy │ backtest │ web UI │
├─────────────────────────────────────────────────────┤
│              Exchange (Bybit via CCXT)               │
└─────────────────────────────────────────────────────┘
```

```
├── freqtrade/          ← Upstream Freqtrade (cloned, minimal changes)
├── custom_app/         ← Our extensions
│   ├── mode_control/   ← Operator-only mode lock
│   ├── promotion/      ← Strategy promotion pipeline
│   ├── risk_layer/     ← Risk engine with veto power
│   ├── no_alpha/       ← No-alpha / do-nothing gate
│   ├── dashboard/      ← Technical operations dashboard
│   ├── validation/     ← Backtest + walk-forward + shadow orchestration
│   ├── audit/          ← Audit log
│   ├── replay/         ← Order replay and reconciliation
│   ├── config/         ← Config loading and hashing
│   └── metrics/        ← Metrics collection and export
├── configs/            ← Layered config files
├── docs/               ← Documentation
├── scripts/            ← Operational scripts
└── tests/              ← Tests
```

## Quick Start

```bash
# 1. Install
make setup

# 2. Configure
cp .env.example .env
# Edit .env — set exchange keys etc.

# 3. Run paper mode (safe default)
make run-paper

# 4. Run backtest
make backtest

# 5. Start dashboard
make dashboard

# 6. Run tests
make test
```

## Real Trading Gate

Real trading requires **ALL** of the following:
1. `DRY_RUN=false` in the active config
2. `REAL_TRADING_ACKNOWLEDGED=true` environment variable
3. `OPERATOR_APPROVAL_TOKEN` matching stored hash
4. Strategy that completed the full promotion pipeline
5. Valid, non-stale promotion artifact

## Promotion Pipeline

```
draft → research → backtest_passed → walk_forward_passed → paper_shadow → paper_active → small_live → full_live
```

Promotion eligibility does **NOT** enable real trading. Real trading requires a separate operator action.

## Key Commands

| Command | Description |
|---------|-------------|
| `make run-paper` | Start bot in paper/dry-run mode |
| `make run-real` | Start bot in live mode (requires all gates) |
| `make backtest` | Run deterministic backtest |
| `make walk-forward` | Run walk-forward validation |
| `make shadow` | Run paper shadow mode |
| `make promote` | Run promotion workflow |
| `make dashboard` | Start operations dashboard |
| `make test` | Run all tests |
| `make verify-mode-lock` | Verify mode lock is enforced |

## Safety Defaults

- Default mode: **paper/dry-run**
- Risk veto: **enabled**
- No-alpha gate: **enabled**
- Kill switch: **armed**
- Audit logging: **enabled**
- Real trading: **disabled** unless ALL gates pass
