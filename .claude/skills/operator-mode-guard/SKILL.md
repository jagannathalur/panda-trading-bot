# Skill: Operator Mode Guard

Ensures trading mode immutability is preserved whenever code is added or modified.

## Trigger Conditions

Use this skill whenever:
- Any file in `custom_app/mode_control/` is modified
- Any API endpoint is added (check it doesn't expose mode mutation)
- Any dashboard component is added (check no mode toggle)
- Any self-healing or health-check logic is added
- Any strategy callback touches mode-related logic

## Checklist

### Before making changes
- [ ] Read `custom_app/mode_control/guard.py` to understand ModeViolationError
- [ ] Read `custom_app/mode_control/startup.py` for startup gate logic
- [ ] Read `tests/unit/test_mode_control.py` for existing tests

### When adding API endpoints
- [ ] Mode endpoint is GET only (read-only)
- [ ] POST/PUT/PATCH /mode returns 403
- [ ] No endpoint accepts a `mode` or `dry_run` mutation parameter

### When adding dashboard components
- [ ] No toggle/switch component for mode
- [ ] Mode displayed as static badge only
- [ ] Add "READ-ONLY" label near mode display

### When adding self-healing/health logic
- [ ] Does NOT call `dry_run` config mutation
- [ ] Does NOT call Freqtrade restart with different config
- [ ] Does NOT call any mode-changing API

### After making changes
- [ ] Run: `python3 -m pytest tests/unit/test_mode_control.py -v`
- [ ] All immutability tests pass
- [ ] Add new test for new code path if needed

## Key Invariants (Never Break)

1. `ModeGuard._instance` is set exactly once per process
2. `ModeGuard.attempt_mode_change()` ALWAYS raises `ModeViolationError`
3. `TradingModeConfig` is `frozen=True` — cannot be mutated
4. Real trading requires ALL THREE: acknowledged + token + dry_run=false
5. Paper is the default when `TRADING_MODE` is not set

## Pattern: Checking Mode Safely

```python
from custom_app.mode_control import ModeGuard

guard = ModeGuard.get_instance()
if guard.is_paper():
    # paper-only code path
elif guard.is_real():
    # real-mode code path

# Display-safe (never expose as mutable)
display = guard.to_display_dict()  # has read_only=True
```

## Pattern: Blocking Mode Mutation

```python
# In any component that receives a "change mode" request:
guard = ModeGuard.get_instance()
guard.attempt_mode_change(requested_mode, caller="component_name")
# This ALWAYS raises ModeViolationError — that is correct behavior
```
