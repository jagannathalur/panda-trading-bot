# Operations Runbook

## Daily Checks

1. Check dashboard: http://localhost:8080
2. Verify kill switch state: `make verify-mode-lock`
3. Check audit log for anomalies: `tail -f data/audit.log | python3 -m json.tool`
4. Check daily PnL and drawdown
5. Check artifact freshness (alert if > 7 days old)

## Starting the Bot

### Paper mode (safe)
```bash
make run-paper
```

### Real mode (requires all gates)
```bash
make verify-mode-lock   # Must pass before proceeding
make run-real
```

## Stopping the Bot

```bash
# Graceful stop (sends SIGTERM to Freqtrade)
ps aux | grep freqtrade | grep -v grep | awk '{print $2}' | xargs kill -TERM

# Or via Docker:
docker-compose stop freqtrade
```

## Emergency Procedures

### Kill switch triggered automatically
- All new trades halted
- Check dashboard for reason
- Review audit log
- Decide whether to:
  a) Wait for drawdown to recover, restart with fresh mode
  b) Emergency flatten if situation is deteriorating

### Emergency flatten
```bash
make emergency-flatten
```

### Strategy performing badly
1. Check live vs backtest drift
2. Check no-alpha gate block rate
3. If bad: demote strategy to `paper_active` or `research`
4. Do NOT re-enable live without fresh validation artifacts

## Configuration Changes

ANY material config change requires:
1. Stop the bot
2. Update config
3. Compute new config hash: `python3 -c "from custom_app.config.hashing import hash_config_file; print(hash_config_file('configs/paper.yaml'))"`
4. Re-run full validation pipeline
5. Generate fresh promotion artifact
6. Restart

## Adding a New Strategy

1. Create strategy in `user_data/strategies/MyStrategy.py`
2. Register it: `python3 -c "from custom_app.promotion import StrategyRegistry; StrategyRegistry().register('MyStrategy')"`
3. Run full validation pipeline: `FREQTRADE_STRATEGY=MyStrategy make backtest walk-forward shadow`
4. Promote through states: `bash scripts/promote_strategy.sh MyStrategy backtest_passed`
5. Only after all stages + operator approval: start in real mode

## Viewing Audit Log

```bash
# Tail live
tail -f data/audit.log | python3 -m json.tool

# Query specific event type
python3 -c "
from custom_app.audit.storage import query_audit_log
from custom_app.audit.events import AuditEventType
events = query_audit_log('data/audit.log', event_type=AuditEventType.RISK_VETO, limit=10)
import json; print(json.dumps(events, indent=2))
"
```
