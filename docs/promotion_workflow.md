# Strategy Promotion Workflow

## States

```
draft → research → backtest_passed → walk_forward_passed → paper_shadow → paper_active → small_live → full_live
         ↓              ↓                    ↓                  ↓               ↓
       failed         failed               failed             failed          failed
                                                                                 ↓
                                                                            deprecated
```

## Promotion Rules

1. **No state skipping** — must pass through every stage
2. **Artifact required** — from `backtest_passed` onward, a valid artifact is required
3. **Artifact freshness** — artifacts older than 7 days (configurable) are rejected
4. **Operator approval** — `small_live` and `full_live` require operator token
5. **Decoupled from trading mode** — promotion to `full_live` does NOT enable real trading

## Running the Pipeline

```bash
# Step 1: Backtest
make backtest

# Step 2: Walk-forward
make walk-forward

# Step 3: Paper shadow (runs for 72h minimum)
make shadow

# Step 4: Promote to backtest_passed
bash scripts/promote_strategy.sh GridTrendV1 backtest_passed

# Step 5: Continue promotion...
bash scripts/promote_strategy.sh GridTrendV1 walk_forward_passed
bash scripts/promote_strategy.sh GridTrendV1 paper_shadow
bash scripts/promote_strategy.sh GridTrendV1 paper_active

# Step 6: Operator approval required for live stages
# Set OPERATOR_APPROVAL_TOKEN and run:
bash scripts/promote_strategy.sh GridTrendV1 small_live
```

## Promotion Artifacts

Each promotion artifact contains:
- `strategy_id` — strategy class name
- `version` — semver
- `code_commit` — git SHA of strategy code
- `config_hash` — SHA256 of config files
- `feature_set_version` — version of feature engineering
- `parameter_manifest` — current parameter values
- `backtest_report` — backtest results
- `walk_forward_report` — WF validation results
- `shadow_report` — paper shadow results
- `generated_at` — timestamp
- `passed` — boolean
- `fail_reason` — if not passed

Automated validation does not mark an artifact as passed until the paper shadow report exists.
Backtest plus walk-forward may produce a saved artifact in a pending state, but that artifact is
not eligible for promotion until shadow validation is attached and the artifact passes freshness
checks.

## Enabling Real Trading (Separate Operator Action)

Reaching `full_live` promotion state does NOT enable real trading.

To enable real trading, the operator must:
1. Set `TRADING_MODE=real` in environment
2. Set `REAL_TRADING_ACKNOWLEDGED=true`
3. Set `OPERATOR_APPROVAL_TOKEN` (valid token)
4. Set `dry_run=false` in config
5. Restart the bot
6. An audit log entry is written

These are completely independent of the promotion system.
