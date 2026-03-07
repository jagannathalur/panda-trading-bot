# Skill: Risk Review

Run this skill whenever touching risk_layer, no_alpha, or kill switch logic.

## Risk Engine Checklist

### Veto behavior
- [ ] All new checks raise `RiskVetoError` with a descriptive `check_name`
- [ ] `check_name` is short, snake_case, unique
- [ ] Fail closed: exceptions in new checks are caught and also result in veto
- [ ] New check is added to `RiskEngine.evaluate()` and called in correct order

### Limits
- [ ] New limits added to `RiskLimits` dataclass
- [ ] Default values are CONSERVATIVE
- [ ] Limits loadable from environment variables
- [ ] Limits documented in `configs/risk.yaml`

### Kill switch
- [ ] Kill switch check is FIRST in the evaluation chain
- [ ] `arm_kill_switch()` writes audit log
- [ ] Kill switch once armed stays armed until restart

### No-alpha gate
- [ ] All metric thresholds default to conservative values
- [ ] Zero/missing metrics are blocked (not passed)
- [ ] Gate writes audit log for both pass and block

## Test Requirements

```python
# Every new risk check must have a test like:
def test_new_check_vetoes_when_limit_exceeded():
    engine = RiskEngine.initialize(RiskLimits(new_limit=threshold))
    engine.update_state(new_metric=over_threshold)
    with pytest.raises(RiskVetoError, match="new_check_name"):
        engine.evaluate(_intent())
```

## Risk Limits to Never Increase Without Operator Approval

- `kill_switch_drawdown_pct` — hard stop, only decrease
- `max_daily_loss_pct` — daily cap, conservative always
- `max_leverage` — leverage limit, only decrease
- `consecutive_loss_pause_count` — loss pause, only decrease

## Audit Events to Write

| Event | When |
|-------|------|
| `RISK_VETO` | Every veto (already in engine) |
| `KILL_SWITCH_ARMED` | Kill switch activation (already in engine) |
| `DAILY_LOSS_CAP_HIT` | Daily cap reached |
| `DRAWDOWN_CAP_HIT` | Drawdown cap reached |
| `CONSECUTIVE_LOSS_PAUSE` | Pause triggered |
