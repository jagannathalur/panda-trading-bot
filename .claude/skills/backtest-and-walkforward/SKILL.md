# Skill: Backtest and Walk-Forward Validation

Use when running or reviewing backtesting and walk-forward validation.

## Running Validation

```bash
# Full pipeline
make backtest
make walk-forward
make shadow  # 72h minimum

# Or directly
bash scripts/run_backtest.sh
bash scripts/run_walk_forward.sh
bash scripts/run_shadow.sh
```

## Backtest Requirements

- [ ] Must be **deterministic**: same config + data = same results
- [ ] `--timerange` must be set explicitly
- [ ] Results exported to `data/backtest_*.json`
- [ ] Minimum 100 trades in backtest period
- [ ] Max drawdown < 20%
- [ ] Profit factor > 1.2

## Walk-Forward Requirements

- [ ] Minimum 5 windows
- [ ] 70% in-sample, 30% out-of-sample per window
- [ ] OOS win rate > 45%
- [ ] OOS results NOT cherry-picked

## Shadow Run Requirements

- [ ] Minimum 72 hours of continuous paper run
- [ ] Minimum 10 trades during shadow period
- [ ] Live vs paper drift < 5%
- [ ] Shadow fills compared against live prices

## Promotion Artifact

After all three stages pass, generate artifact:

```python
from custom_app.promotion.artifacts import PromotionArtifact
from custom_app.config.hashing import hash_multiple_configs

artifact = PromotionArtifact(
    strategy_id="GridTrendV1",
    version="1.0.0",
    code_commit="$(git rev-parse HEAD)",
    config_hash=hash_multiple_configs(["configs/base.yaml", "configs/paper.yaml"]),
    feature_set_version="1.0.0",
    parameter_manifest={"grid_levels": 5, ...},
    backtest_report={...},
    walk_forward_report={...},
    shadow_report={...},
    passed=True,
)
artifact.save("data/artifacts/")
```

## Red Flags

- Backtest with < 50 trades: insufficient — don't promote
- Backtest Sharpe < 0.5: probably not worth live testing
- Large OOS vs IS performance gap: likely overfitting — retrain
- Shadow drift > 10%: investigate before promoting
