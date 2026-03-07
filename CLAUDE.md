# CLAUDE.md — Panda Trading Bot

This repo is built on top of Freqtrade (cloned into `freqtrade/`).
All custom platform logic lives in `custom_app/`.

## Core Principles

### 1. Extension Over Invasion
- ALWAYS prefer wrapping Freqtrade over modifying its internals.
- When modification is unavoidable, document it in UPGRADE.md under "Patched Upstream Areas."
- Every touched upstream file must be listed in ARCHITECTURE_EXTENSIONS.md.

### 2. Operator-Only Mode Lock (CRITICAL)
- `TRADING_MODE` (paper vs real) is decided ONCE at startup.
- It is read from environment variables + config ONLY.
- The bot MUST NEVER switch between dry-run and live at runtime.
- NO dashboard action, API endpoint, strategy hook, self-healing flow, promotion step,
  or internal service may mutate trading mode.
- Mode changes require: (a) restart, (b) audit log entry, (c) explicit operator action.
- Real trading requires ALL of:
  - `DRY_RUN=false` in config
  - `REAL_TRADING_ACKNOWLEDGED=true` env var
  - `OPERATOR_APPROVAL_TOKEN` env var matching stored hash
- Strategy promotion eligibility does NOT imply real trading is enabled.

### 3. Strategy & Config Validation
- Any new strategy or material config change MUST produce fresh validation artifacts before use.
- Required artifacts: backtest report + walk-forward report + paper shadow report + promotion artifact.
- Stale artifacts (older than configured threshold) are automatically rejected.
- Promotion states: draft → research → backtest_passed → walk_forward_passed → paper_shadow → paper_active → small_live → full_live.

### 4. Risk Engine Veto
- The custom risk layer in `custom_app/risk_layer/` has VETO POWER over all trading intents.
- Risk checks run BEFORE any order is submitted to Freqtrade's execution path.
- Risk layer decisions are immutable within a trade lifecycle.

### 5. No-Alpha Default
- "Do nothing" is a valid and preferred action when edge is weak.
- The no-alpha gate in `custom_app/no_alpha/` blocks trades when:
  - expected_net_edge_bps < threshold, OR
  - market_quality_score < threshold, OR
  - model_quality_score < threshold.
- Never force a trade to meet activity targets.

### 6. Dashboard Read-Only Mode
- The dashboard MUST display trading mode (paper/real) as READ-ONLY.
- The dashboard MUST NOT contain a runtime paper/live toggle.
- Dashboard panels showing mode state are informational only.

### 7. Auditability
- Every critical action must produce an audit log entry.
- Audit log entries include: timestamp, actor, action, before_state, after_state, outcome.
- Audit log is append-only and stored durably.

### 8. Bounded Self-Correction
- No unconstrained online learning.
- No runtime ad hoc parameter mutation.
- Only bounded, scheduled reoptimization within hard parameter bounds.
- Champion/challenger framework governs any parameter changes.

## When Editing Code

### Touching mode_control/
- Add a test in tests/unit/test_mode_control.py proving immutability.
- Update ARCHITECTURE_EXTENSIONS.md if any upstream file was touched.

### Touching risk_layer/
- Add a test proving risk veto fires correctly.
- Update docs/risk_spec.md if any behavior changes.

### Touching promotion/
- Ensure promotion state does NOT imply live trading enablement.
- Update docs/promotion_workflow.md.

### Touching dashboard/
- Ensure no runtime mode toggle is added.
- Ensure mode display is read-only.

### Touching any strategy file
- Validate fresh artifacts are generated before use.
- Do not put safety logic inside strategy callbacks.

## File Ownership
- `freqtrade/` — upstream, minimize changes
- `custom_app/` — our extensions, full ownership
- `configs/` — our configs, layered on top of Freqtrade conventions
- `docs/` — our docs
- `scripts/` — our operational scripts
- `tests/` — our tests
