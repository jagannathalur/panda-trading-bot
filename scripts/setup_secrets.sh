#!/bin/bash
# =============================================================
# setup_secrets.sh — Interactive credential setup.
# Walks you through every secret, validates it, writes to .env
# Optionally backs up to macOS Keychain for extra safety.
# =============================================================

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET} $*"; }
err()  { echo -e "${RED}✗${RESET} $*"; }
hdr()  { echo -e "\n${BOLD}$*${RESET}"; }

echo -e "${BOLD}=================================================${RESET}"
echo -e "${BOLD}  Panda Trading Bot — Secret Setup${RESET}"
echo -e "${BOLD}=================================================${RESET}"
echo ""
echo "This script will walk you through setting up all credentials."
echo "Nothing is sent anywhere — secrets are saved only to .env"
echo ""

# Initialise .env from example if missing
if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    ok "Created .env from .env.example"
fi

# Helper: read a secret without echoing
read_secret() {
    local prompt="$1"
    local var_name="$2"
    local required="${3:-false}"
    local value=""
    while true; do
        read -s -p "$prompt: " value
        echo ""
        if [[ -z "$value" && "$required" == "true" ]]; then
            err "This field is required. Please enter a value."
        else
            break
        fi
    done
    echo "$var_name=$value"
}

# Helper: update a key in .env
set_env() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        # Replace existing
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        else
            sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
        fi
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

# Helper: store in macOS Keychain
store_in_keychain() {
    local label="$1"
    local value="$2"
    if command -v security &>/dev/null; then
        security add-generic-password \
            -a "panda-trading-bot" \
            -s "$label" \
            -w "$value" \
            -U 2>/dev/null && ok "Stored '$label' in macOS Keychain" || true
    fi
}

# ==========================================================
hdr "1. Anthropic API Key (Claude Haiku sentiment gate)"
echo ""
echo "Get your key at: https://console.anthropic.com/settings/keys"
echo "This enables the LLM sentiment filter. Expected cost: < \$0.25/month."
echo ""
read -s -p "ANTHROPIC_API_KEY (starts with sk-ant-): " ANTHROPIC_KEY
echo ""

if [[ -n "$ANTHROPIC_KEY" ]]; then
    if [[ "$ANTHROPIC_KEY" != sk-ant-* ]]; then
        warn "Key doesn't start with sk-ant- — double-check it's a valid Anthropic key"
    fi
    # Validate with a minimal API call
    echo "Validating key..."
    HTTP_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" \
        "https://api.anthropic.com/v1/models" \
        -H "x-api-key: $ANTHROPIC_KEY" \
        -H "anthropic-version: 2023-06-01" 2>/dev/null || echo "000")
    if [[ "$HTTP_STATUS" == "200" ]]; then
        ok "Anthropic API key validated"
        set_env "ANTHROPIC_API_KEY" "$ANTHROPIC_KEY"
        store_in_keychain "ANTHROPIC_API_KEY" "$ANTHROPIC_KEY"
    else
        warn "Validation returned HTTP $HTTP_STATUS — saved anyway, check the key"
        set_env "ANTHROPIC_API_KEY" "$ANTHROPIC_KEY"
    fi
else
    warn "Skipped — LLM sentiment gate will be disabled"
fi

# ==========================================================
hdr "2. Bybit API Keys"
echo ""
echo "Paper mode works WITHOUT API keys (simulated)."
echo "Only add keys when you're ready for real trading."
echo ""
read -p "Add Bybit keys now? (y/N): " add_bybit
if [[ "${add_bybit,,}" == "y" ]]; then
    read -s -p "BYBIT_API_KEY: " BYBIT_KEY; echo ""
    read -s -p "BYBIT_API_SECRET: " BYBIT_SECRET; echo ""
    if [[ -n "$BYBIT_KEY" && -n "$BYBIT_SECRET" ]]; then
        set_env "BYBIT_API_KEY" "$BYBIT_KEY"
        set_env "BYBIT_API_SECRET" "$BYBIT_SECRET"
        store_in_keychain "BYBIT_API_KEY" "$BYBIT_KEY"
        store_in_keychain "BYBIT_API_SECRET" "$BYBIT_SECRET"
        ok "Bybit keys saved"
    fi
else
    ok "Skipped — bot will run in simulated mode"
fi

# ==========================================================
hdr "3. FreqUI Password"
echo ""
echo "This secures the FreqUI web interface (default: change-me)."
echo ""
read -s -p "New FreqUI password (leave blank to keep default): " FT_PASS; echo ""
if [[ -n "$FT_PASS" ]]; then
    set_env "FREQTRADE_API_PASSWORD" "$FT_PASS"
    # Also update base.json
    BASE_JSON="$PROJECT_DIR/configs/base.json"
    if [[ -f "$BASE_JSON" ]]; then
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "s|\"password\": \"change-me\"|\"password\": \"${FT_PASS}\"|" "$BASE_JSON"
        else
            sed -i "s|\"password\": \"change-me\"|\"password\": \"${FT_PASS}\"|" "$BASE_JSON"
        fi
    fi
    ok "FreqUI password updated"
else
    warn "Keeping default 'change-me' — change this before exposing to a network"
fi

# ==========================================================
hdr "4. Operator Token (required for real trading)"
echo ""
echo "This token is needed to promote strategies to live trading."
echo "Generate and record it safely — you cannot recover it."
echo ""
read -p "Generate a new operator token? (y/N): " gen_token
if [[ "${gen_token,,}" == "y" ]]; then
    TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    TOKEN_HASH=$(python3 -c "import hashlib; print(hashlib.sha256(b'$TOKEN').hexdigest())")
    echo ""
    echo -e "${BOLD}YOUR OPERATOR TOKEN (save this securely):${RESET}"
    echo ""
    echo "  $TOKEN"
    echo ""
    echo "Store it in a password manager. It will NOT be shown again."
    echo ""
    read -p "Press Enter once you've saved the token..."
    set_env "OPERATOR_APPROVAL_TOKEN_HASH" "$TOKEN_HASH"
    store_in_keychain "OPERATOR_APPROVAL_TOKEN" "$TOKEN"
    ok "Token hash saved to .env. Token stored in Keychain."
fi

# ==========================================================
echo ""
echo -e "${BOLD}=================================================${RESET}"
echo -e "${GREEN}${BOLD}  Setup complete!${RESET}"
echo -e "${BOLD}=================================================${RESET}"
echo ""
echo "Your .env is at: $ENV_FILE"
echo ""
echo "Secrets are stored ONLY on this machine."
echo "Never commit .env to git (it's in .gitignore)."
echo ""
echo "Next step: double-click desktop/LaunchPandaBot.command"
echo ""
