#!/usr/bin/env bash
# Verify that all mode lock requirements are satisfied.
# Exits 0 if paper mode (always safe).
# Exits 0 if real mode with all gates satisfied.
# Exits 1 if real mode requirements are not met.
set -euo pipefail

if [ -f "$(dirname "$0")/../.env" ]; then
  set -a; source "$(dirname "$0")/../.env"; set +a
fi

TRADING_MODE="${TRADING_MODE:-paper}"
REAL_TRADING_ACKNOWLEDGED="${REAL_TRADING_ACKNOWLEDGED:-false}"
OPERATOR_APPROVAL_TOKEN="${OPERATOR_APPROVAL_TOKEN:-}"
OPERATOR_APPROVAL_TOKEN_HASH="${OPERATOR_APPROVAL_TOKEN_HASH:-}"

echo "=== Mode Lock Verification ==="
echo "TRADING_MODE: $TRADING_MODE"

if [ "$TRADING_MODE" = "paper" ]; then
  echo "MODE: PAPER — No gates required. Safe to proceed."
  exit 0
fi

if [ "$TRADING_MODE" != "real" ]; then
  echo "ERROR: Invalid TRADING_MODE='$TRADING_MODE'. Must be 'paper' or 'real'."
  exit 1
fi

echo "MODE: REAL — Checking all operator gates..."
ERRORS=0

# Gate 1: Acknowledgement
if [ "$REAL_TRADING_ACKNOWLEDGED" != "true" ]; then
  echo "  [FAIL] REAL_TRADING_ACKNOWLEDGED must be 'true' (got: '$REAL_TRADING_ACKNOWLEDGED')"
  ERRORS=$((ERRORS+1))
else
  echo "  [PASS] REAL_TRADING_ACKNOWLEDGED=true"
fi

# Gate 2: Operator token
if [ -z "$OPERATOR_APPROVAL_TOKEN" ]; then
  echo "  [FAIL] OPERATOR_APPROVAL_TOKEN is not set"
  ERRORS=$((ERRORS+1))
elif [ -z "$OPERATOR_APPROVAL_TOKEN_HASH" ]; then
  echo "  [FAIL] OPERATOR_APPROVAL_TOKEN_HASH is not set"
  ERRORS=$((ERRORS+1))
else
  COMPUTED_HASH=$(echo -n "$OPERATOR_APPROVAL_TOKEN" | sha256sum | awk '{print $1}')
  if [ "$COMPUTED_HASH" = "$OPERATOR_APPROVAL_TOKEN_HASH" ]; then
    echo "  [PASS] Operator token validated"
  else
    echo "  [FAIL] Operator token hash mismatch"
    ERRORS=$((ERRORS+1))
  fi
fi

# Gate 3: Bybit testnet check
if [ "${BYBIT_TESTNET:-true}" = "true" ]; then
  echo "  [WARN] BYBIT_TESTNET=true — this is testnet, not mainnet"
fi

if [ "$ERRORS" -gt 0 ]; then
  echo ""
  echo "ERROR: $ERRORS gate(s) failed. Real trading NOT started."
  exit 1
fi

echo ""
echo "All gates PASSED. Real trading mode authorized."
