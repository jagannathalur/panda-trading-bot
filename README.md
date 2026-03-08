# Panda Trading Bot

A production-grade algorithmic crypto trading platform built on top of [Freqtrade](https://github.com/freqtrade/freqtrade), with a strict operator-controlled governance layer, AI-powered signal gates, real-time macro intelligence, and a comprehensive operations dashboard.

## What This Is

**Freqtrade provides (reused as-is):**
- Exchange connectivity (CCXT), including Bybit perpetuals
- Order execution engine
- Dry-run / live mode
- Built-in backtesting and hyperopt
- Strategy loading and customization

**Panda Platform adds:**
- **AI signal gates** — Claude Haiku LLM sentiment + macro context as final entry filter
- **Macro intelligence** — 30-second background polling of liquidations, open interest, Fear & Greed, geopolitical risk
- **Multi-timeframe EMA alignment** — 15m trend confirmation before 5m entries
- **Orderbook imbalance gate** — blocks entries into adverse order pressure (free, zero latency)
- **Side-aware liquidation cascade** — long vs short cascade handled independently
- **Operator-only mode lock** — paper/real trading cannot be changed at runtime
- **Validation & promotion pipeline** — backtest → walk-forward → paper shadow before live
- **Custom risk engine** — per-trade, daily, drawdown, leverage, exposure controls with veto power
- **No-alpha gate** — explicit "do nothing" logic when expected edge is too weak
- **Operations dashboard** — live PnL, trades, risk, bot status on port 8080
- **Full audit trail** — every critical action is logged durably

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Operator / Ops Team                            │
├─────────────────────────────────────────────────────────────────────┤
│                      Panda Platform Layer                            │
│  mode_control │ promotion  │ risk_layer  │ dashboard │ no_alpha      │
│  audit        │ validation │ metrics     │ config    │ replay        │
│                                                                      │
│  Signal Gates (GridTrendV2 — cheapest first):                        │
│  1. MTF 15m EMA alignment (CPU only, fail-open)                      │
│  2. Macro hard blocks (liq cascade, Fear&Greed, geo, OI divergence)  │
│  3. Orderbook imbalance gate (free, pre-computed)                    │
│  4. Funding rate gate (Bybit API, 5-min cache)                       │
│  5. LLM sentiment gate (Claude Haiku, 15-min cache, macro-enriched)  │
├─────────────────────────────────────────────────────────────────────┤
│  Macro Signal Collector (30s background daemon)                      │
│  Bybit: open interest │ liquidations (side-aware) │ orderbook        │
│  Alternative.me: Fear & Greed Index (6h cache)                       │
│  GDELT: geopolitical risk score (15m cache)                          │
├─────────────────────────────────────────────────────────────────────┤
│                     Freqtrade Core                                   │
│     exchange │ execution │ strategy │ backtest │ web UI              │
├─────────────────────────────────────────────────────────────────────┤
│                  Exchange (Bybit via CCXT)                           │
└─────────────────────────────────────────────────────────────────────┘
```

```
├── freqtrade/              ← Upstream Freqtrade (cloned, minimal changes)
├── custom_app/             ← Panda Platform extensions
│   ├── signals/            ← AI + macro signal gates
│   │   ├── entry_filters.py        — MTF EMA + orderbook gate (pure, testable)
│   │   ├── llm_sentiment.py        — Claude Haiku sentiment gate (15m cache)
│   │   ├── macro_collector.py      — 30s background macro polling daemon
│   │   ├── market_microstructure.py — Bybit OI, liquidations, orderbook
│   │   ├── geopolitical.py         — GDELT geopolitical risk (15m cache)
│   │   ├── funding_rate.py         — Bybit funding rate gate (5m cache)
│   │   └── news_fetcher.py         — News headline fetcher for LLM context
│   ├── mode_control/       ← Operator-only mode lock
│   ├── promotion/          ← Strategy promotion pipeline
│   ├── risk_layer/         ← Risk engine with veto power
│   ├── no_alpha/           ← No-alpha / do-nothing gate
│   ├── dashboard/          ← Operations dashboard (port 8080)
│   ├── validation/         ← Backtest + walk-forward + shadow orchestration
│   ├── audit/              ← Audit log
│   └── metrics/            ← Metrics collection and export
├── user_data/strategies/   ← Trading strategies
│   ├── GridTrendV2.py      — Active: long+short EMA crossover + 6-gate filter
│   └── GridTrendV1.py      — Archived: long-only baseline
├── configs/                ← Layered config files
├── docs/                   ← Documentation
├── scripts/                ← Operational scripts
└── tests/                  ← Tests (217 unit tests, all passing)
```

## Strategy: GridTrendV2

EMA crossover long+short strategy with a 6-gate AI filter pipeline.

**Entry signals (5m timeframe):**
- Long:  EMA9 crosses above EMA21, RSI < 65, volume above 20-period average
- Short: EMA9 crosses below EMA21, RSI > 35, volume above 20-period average

**Gate pipeline (cheapest first — LLM is last):**

| Gate | Description | Cost |
|------|-------------|------|
| MTF 15m EMA | Block entries against 15m trend | CPU only |
| Macro blocks | Liq cascade, F&G extreme, geo spike, OI divergence | Pre-computed |
| Orderbook | Block into asks domination (long) or bids domination (short) | Pre-computed |
| Funding rate | Block adverse perpetual funding | Bybit API, 5m cache |
| LLM sentiment | Claude Haiku + macro context as final filter | ~$0.0004/call, 15m cache |

**Risk controls:**
- Trailing stoploss: 1.5% trail after +2% profit, hard floor at -5%
- ATR-based position sizing: stake halved when ATR/price > 3%
- OI crowding reduction: stake halved when open interest surges > 20%
- Progressive ROI: 5% any time, 3% after 30m, 1.5% after 1h, 0.5% after 2h

**Macro signal rules:**

| Signal | Threshold | Action |
|--------|-----------|--------|
| Long liq cascade | >$5M long liq in 5 min | Block longs |
| Short liq cascade | >$5M short liq in 5 min | Block shorts |
| Extreme Fear (F&G) | F&G < 15 | Block longs |
| Extreme Greed (F&G) | F&G > 85 | Block shorts |
| Geopolitical spike | GDELT risk > 0.8 | Block both sides |
| OI declining | OI% < -5% | Block longs |
| OI surging | OI% > 20% | Block shorts (+ halve stake) |

## Quick Start

```bash
# 1. Install
make setup

# 2. Configure
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY for LLM gate

# 3. Run paper mode on Bybit futures (can_short requires futures)
freqtrade trade --config configs/futures_paper.json \
                --strategy GridTrendV2 \
                --logfile /tmp/ft.log &

# 4. Start bot (it starts in STOPPED state)
curl -X POST http://127.0.0.1:8081/api/v1/start -u freqtrade:change-me

# 5. Start operations dashboard
python3 -m uvicorn custom_app.dashboard.app:app --host 0.0.0.0 --port 8080 &

# 6. Run tests
python3 -m pytest tests/unit/ -q

# 7. View logs
tail -f /tmp/ft.log
```

## Operations Dashboard (port 8080)

The dashboard at `http://localhost:8080` shows live data refreshed every 5 seconds:

- **Bot Status** — strategy name, state, timeframe (live from Freqtrade API)
- **Profit & Loss** — total realized, unrealized, win rate, wins/losses, avg duration
- **Trade Stats** — best pair, Sharpe ratio, profit %, drawdown
- **Safety Controls** — kill switch, no-alpha gate, risk engine status
- **Signal Gates** — all 6 GridTrendV2 gates (static overview)
- **Recent Trades** — live trades table with P&L and exit reason
- **Promotion Status** — strategy lifecycle stage
- **Audit Log** — recent audit events

Trading mode display is **read-only** — no toggle exists.

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

## Data Sources (all free, no API key required for macro)

| Source | Data | Update Freq |
|--------|------|-------------|
| Bybit `/v5/market/liq-records` | Liquidations (side-aware) | Every 30s |
| Bybit `/v5/market/open-interest` | Open interest + change % | Every 30s |
| Bybit `/v5/market/orderbook` | Bid/ask imbalance | Every 30s |
| Alternative.me `/fng` | Fear & Greed Index | 6h cache (daily updates) |
| GDELT API | Geopolitical risk score | 15m cache |
| Bybit `/v5/market/funding/history` | Perpetual funding rate | 5m cache |
| News RSS | Headlines for LLM context | On-demand |
| Anthropic (Claude Haiku) | Sentiment gate | 15m cache, ~$0.0004/call |

## Key Commands

| Command | Description |
|---------|-------------|
| `make run-paper` | Start bot in paper/dry-run mode |
| `make run-real` | Start bot in live mode (requires all gates) |
| `make backtest` | Run deterministic backtest |
| `make walk-forward` | Run walk-forward validation |
| `make dashboard` | Start operations dashboard on port 8080 |
| `make test` | Run all 217 unit tests |

## Safety Defaults

- Default mode: **paper/dry-run**
- Trailing stoploss: **-5% hard floor, 1.5% trail from peak**
- Risk veto: **enabled**
- No-alpha gate: **enabled**
- Kill switch: **armed**
- Audit logging: **enabled**
- Real trading: **disabled** unless ALL gates pass
- LLM cost guard: **15-min cache per pair/side** (no runaway API costs)
- Macro polling: **fail-open** (source outage never blocks a trade on its own)
