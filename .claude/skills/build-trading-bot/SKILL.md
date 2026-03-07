# Skill: Build Trading Bot Feature

Use when adding new features to the Panda Trading Bot.

## Pre-Build Checklist

- [ ] Feature touches which modules? (mode_control / risk / no_alpha / promotion / dashboard / validation)
- [ ] Does it touch mode? If yes, use operator-mode-guard skill
- [ ] Does it touch risk? If yes, use risk-review skill
- [ ] Does it touch strategy? If yes, ensure validation artifacts will be updated

## Build Pattern

1. **Read first**: Always read existing module before modifying
2. **Extend don't replace**: Prefer adding to existing modules
3. **No upstream edits**: Prefer wrapping Freqtrade, not editing it
4. **Fail closed**: New safety checks should fail closed (reject on error)
5. **Audit everything**: Critical actions must write to AuditLogger

## Module Entry Points

| What you want | Where to look |
|--------------|--------------|
| Check/change mode | `custom_app/mode_control/guard.py` |
| Veto a trade | `custom_app/risk_layer/engine.py` |
| Gate on edge | `custom_app/no_alpha/gate.py` |
| Promote strategy | `custom_app/promotion/pipeline.py` |
| Log audit event | `custom_app/audit/logger.py` |
| Dashboard panel | `custom_app/dashboard/api.py` + `app.py` |

## Testing Requirements (per testing.md)

- Unit test for the new function (80%+ coverage)
- If mode-related: add immutability test
- If risk-related: add veto test
- If promotion-related: add state machine test
- Run: `make test-unit` before marking complete

## Freqtrade Integration Points

| Need | Use |
|------|-----|
| Exchange data | Freqtrade strategy `dataframe` in callbacks |
| Trade entry gate | Override `confirm_trade_entry()` |
| Stop management | Override `custom_stoploss()` |
| Exit gate | Override `custom_exit()` |
| Backtest | `make backtest` |
