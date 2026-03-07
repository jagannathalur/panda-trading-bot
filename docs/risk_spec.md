# Risk Specification

## Risk Engine Design

The risk engine has VETO POWER over all trading intents. It runs BEFORE any order reaches Freqtrade's execution path.

**Design principles:**
- Fail closed: any error in a risk check = veto
- Veto is final within a trade lifecycle
- All vetoes are audited
- Kill switch halts ALL new trades immediately

## Risk Checks (in order)

| Check | Veto Condition | Default Limit |
|-------|---------------|---------------|
| Kill switch | Armed | N/A |
| Daily loss cap | daily_loss_pct ≥ max | 2.0% |
| Drawdown cap | drawdown ≥ max | 10.0% |
| Kill switch drawdown | drawdown ≥ kill threshold | 15.0% |
| Open trade cap | open_trades ≥ max | 5 |
| Position size | size_pct > max | 10.0% |
| Total exposure | new_exposure_pct > max | 50.0% |
| Leverage | leverage > max | 3.0x |
| Consecutive losses | count ≥ pause_count | 3 |

## Kill Switch

The kill switch is a hard stop. When armed:
- All new trades are immediately halted
- Existing trades continue until exit conditions
- Emergency flatten can close all positions
- Kill switch can only be disarmed by operator restart

Auto-arm conditions:
- Drawdown ≥ kill_switch_drawdown_pct (15% default)

## Emergency Flatten

Emergency flatten calls Freqtrade's REST API to force-exit all open positions. It does NOT wait for limit fills — it uses market orders where possible.

## Position Sizing

Base position sizing comes from Freqtrade config (`stake_amount`). The risk layer can further constrain via:
1. `max_position_size_pct` — hard cap as % of equity
2. `volatility_adjusted_size()` — scale down in high-volatility regimes
3. `kelly_fraction()` — Kelly-based sizing from historical win rate

## No-Alpha Gate (separate from risk)

The no-alpha gate is conceptually distinct from risk management:
- Risk engine: "is this trade safe?"
- No-alpha gate: "is there actually edge here?"

Both must pass for a trade to proceed.
