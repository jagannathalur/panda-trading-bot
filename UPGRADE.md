# UPGRADE.md — Syncing with Upstream Freqtrade

## Upstream Relationship

- **Upstream repo:** https://github.com/freqtrade/freqtrade
- **Our clone:** `freqtrade/` directory
- **Clone method:** shallow clone (`--depth=1`) for initial setup

## Untouched Upstream Areas (reused as-is)

| Area | Notes |
|------|-------|
| `freqtrade/exchange/` | Exchange connectivity, CCXT, Bybit |
| `freqtrade/persistence/` | Trade persistence, database models |
| `freqtrade/data/` | Data fetching, OHLCV handling |
| `freqtrade/optimize/` | Backtesting, hyperopt engine |
| `freqtrade/rpc/api_server/` | FreqUI web server |
| `freqtrade/strategy/` | Strategy interface (base classes) |
| `freqtrade/freqai/` | FreqAI ML integration |
| `freqtrade/plugins/` | Pairlist, protections |
| `freqtrade/configuration/` | Config loading |

## Wrapped Upstream Areas (used via public API, not modified)

| Area | How We Wrap It |
|------|---------------|
| `freqtradebot.py` | Via strategy callbacks (`confirm_trade_entry`, `custom_stoploss`, etc.) |
| `worker.py` | Mode control runs at startup before worker starts |
| `enums/runmode.py` | Read-only — we consume these enums, never extend |

## Patched Upstream Areas

**Currently: NONE.** We aim to keep this list empty forever.

If a patch becomes necessary, document it here:
```
| File | Reason | Patch | Upgrade Risk |
|------|--------|-------|-------------|
| (none) | — | — | — |
```

## Custom Modules (no upstream overlap)

All live in `custom_app/` — zero overlap with Freqtrade internals.

## Upgrade Procedure

```bash
# 1. Check what changed upstream
cd freqtrade
git fetch origin
git log HEAD..origin/develop --oneline

# 2. Review changelog for breaking changes in:
#    - Strategy interface callbacks
#    - Config schema keys
#    - REST API endpoints
#    - Exchange adapter signatures

# 3. Pull upstream
git pull origin develop

# 4. Re-run full test suite
cd ..
make test

# 5. Re-run validation
make verify-mode-lock
make backtest
```

## Upgrade Risk Table

| Area | Risk | Notes |
|------|------|-------|
| `exchange/` | LOW | API is stable; we use via config |
| `strategy/` interface | MEDIUM | New callbacks may be added; check for breaking changes |
| `configuration/` | MEDIUM | Config schema changes can affect layered configs |
| `rpc/api_server/` | LOW | We don't override; we have a separate dashboard |
| `optimize/` | LOW | We call via CLI, not internal Python API |
| `persistence/` | LOW | We read via Freqtrade's public interfaces |

## Version Tracking

- **Current pinned version:** main (shallow clone at setup time)
- **Last sync date:** 2025-03
- **Bump procedure:** Update this file when syncing, re-run tests
