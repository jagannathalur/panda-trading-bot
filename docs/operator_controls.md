# Operator Controls

## Trading Mode Lock

Trading mode (paper vs real) is locked at startup. It cannot be changed at runtime by anyone.

### Setting Paper Mode (Default)
```bash
# .env
TRADING_MODE=paper
```
No other configuration needed. Paper is always safe.

### Setting Real Mode (Requires all gates)
```bash
# .env
TRADING_MODE=real
REAL_TRADING_ACKNOWLEDGED=true
OPERATOR_APPROVAL_TOKEN=your-secret-token
OPERATOR_APPROVAL_TOKEN_HASH=$(echo -n "your-secret-token" | sha256sum | awk '{print $1}')
DRY_RUN=false   # Must be false in real.yaml config
```

Then verify:
```bash
make verify-mode-lock
```

Then start:
```bash
make run-real
```

### Switching from Real to Paper
1. Stop the bot
2. Set `TRADING_MODE=paper` in `.env`
3. Restart with `make run-paper`
4. Audit log will record the mode change

### What Cannot Change Mode
The following are explicitly blocked from changing mode:
- Dashboard actions (mode display is read-only)
- API endpoints (POST/PUT/PATCH /mode returns 403)
- Strategy callbacks
- Self-healing routines
- Promotion workflow (even full_live promotion ≠ real trading)
- Any internal service

## Kill Switch

### Arming manually
```bash
python3 -c "
from custom_app.risk_layer import RiskEngine
RiskEngine.get_instance().arm_kill_switch('Manual operator action')
"
```

### Emergency Flatten
```bash
make emergency-flatten
# Or directly:
bash scripts/emergency_flatten.sh
```

## Operator Approval Token

Generate your token:
```bash
TOKEN="your-long-secret-string-change-this"
HASH=$(echo -n "$TOKEN" | sha256sum | awk '{print $1}')
echo "OPERATOR_APPROVAL_TOKEN=$TOKEN"
echo "OPERATOR_APPROVAL_TOKEN_HASH=$HASH"
```

Store the hash in `.env`. Store the token in a secure secrets manager.
Never commit either to git.
