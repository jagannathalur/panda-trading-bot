# Skill: Strategy Change Guard

Use when modifying any strategy file or strategy-related config.

## What Counts as a Material Change

Material changes require a full re-validation pipeline + fresh artifact:
- Any change to strategy Python code
- Any change to strategy parameters (grid_levels, ema_fast, etc.)
- Any change to config keys in `configs/base.yaml`, `paper.yaml`, `real.yaml`
- Any change to feature engineering
- Any change to risk limits that affect the strategy

Non-material changes (no re-validation needed):
- Documentation changes
- Logging format changes
- Dashboard changes

## Before Making a Strategy Change

1. Compute current config hash:
```python
from custom_app.config.hashing import hash_multiple_configs
current_hash = hash_multiple_configs(["configs/base.yaml", "configs/paper.yaml"])
print(f"Current config hash: {current_hash}")
```

2. Check current promotion state:
```bash
python3 -c "
from custom_app.promotion import StrategyRegistry
r = StrategyRegistry()
import json; print(json.dumps(r.all_statuses(), indent=2))
"
```

3. If strategy is in `paper_active` or higher: STOP.
   - Demote to `research` before making changes
   - Understand the impact of the change
   - Get agreement on the change

## After Making a Strategy Change

1. Update strategy version in `configs/strategy/<name>.yaml`
2. Run full validation pipeline:
```bash
make backtest
make walk-forward
# After 72h shadow:
make shadow
```
3. Generate new artifact
4. Re-promote through all stages

## Safety Logic in Strategy Callbacks

DO NOT put safety logic inside strategy callbacks. Instead:

```python
# WRONG: Safety logic in strategy
def confirm_trade_entry(self, pair, ...):
    if drawdown > 10:  # Risk logic in strategy = bad
        return False
    return True

# CORRECT: Delegate to risk engine
def confirm_trade_entry(self, pair, ...):
    from custom_app.risk_layer import RiskEngine, RiskVetoError
    try:
        RiskEngine.get_instance().evaluate(TradeIntent(pair=pair, ...))
        return True
    except RiskVetoError:
        return False
```

## Parameter Bounds

Every strategy parameter must have hard bounds defined in its config:
```yaml
bounds:
  grid_levels: [3, 10]  # min, max
  ema_fast: [10, 50]
```

Reoptimization must respect these bounds. Never expand bounds without operator approval and re-validation.
