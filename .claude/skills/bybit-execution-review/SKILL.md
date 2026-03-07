# Skill: Bybit Execution Review

Use when reviewing Bybit-specific execution, connectivity, or order management.

## Bybit via Freqtrade

Freqtrade handles all Bybit connectivity via CCXT. We do not build custom exchange adapters.

Config location: `configs/base.yaml` → `exchange:` section

```yaml
exchange:
  name: bybit
  key: "${BYBIT_API_KEY}"
  secret: "${BYBIT_API_SECRET}"
  ccxt_config:
    enableRateLimit: true
    defaultType: future    # For Bybit futures
```

## Testnet vs Mainnet

| Setting | Testnet | Mainnet |
|---------|---------|---------|
| `BYBIT_TESTNET` | `true` | `false` |
| API endpoint | `testnet.bybit.com` | `bybit.com` |
| Funds | Paper funds | Real funds |
| Risk | None | REAL CAPITAL |

**Always verify `BYBIT_TESTNET` before real trading.**

## Execution Quality Checks

When reviewing execution, check:
- [ ] Fill ratio > 95% on limit orders
- [ ] Slippage < 5 bps on average
- [ ] Order rejection rate < 5%
- [ ] Latency < 500ms for order submission
- [ ] Stoploss on exchange enabled (`stoploss_on_exchange: true`)

## Order Types

Bybit Futures recommended settings:
```yaml
order_types:
  entry: limit
  exit: limit
  stoploss: market           # Market for reliable execution
  stoploss_on_exchange: true # Bybit handles stoploss on exchange side
```

## Rate Limits

Bybit has strict rate limits. Freqtrade's CCXT integration handles these automatically with `enableRateLimit: true`. Don't bypass rate limiting.

## Reconciliation

If there is a discrepancy between Freqtrade's view and Bybit's view:
1. Check `data/audit.log` for recent order events
2. Check Bybit's order history via their dashboard
3. Check Freqtrade's trade database
4. Use `custom_app/replay/` for reconciliation
