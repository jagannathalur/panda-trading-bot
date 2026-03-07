# =========================================================
# Panda Trading Bot — Makefile
# =========================================================
.PHONY: help setup install run-paper run-real backtest walk-forward shadow \
        promote dashboard test test-unit test-integration test-regression \
        test-coverage verify-mode-lock emergency-flatten lint format clean \
        docker-up docker-down docker-logs

PYTHON   := python3
PIP      := pip3
FT_DIR   := freqtrade
UD_DIR   := user_data

ifneq (,$(wildcard .env))
    include .env
    export
endif

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# ----- Setup -------------------------------------------------------
setup: install create-userdir ## Full setup
	@echo "Setup complete. Copy .env.example to .env and configure."

install: ## Install all dependencies
	cd $(FT_DIR) && $(PIP) install -e ".[all]"
	$(PIP) install fastapi uvicorn prometheus-client httpx pytest pytest-cov ruff mypy

create-userdir: ## Create Freqtrade user data directories
	cd $(FT_DIR) && $(PYTHON) -m freqtrade create-userdir --userdir ../$(UD_DIR)
	mkdir -p data logs

# ----- Trading -----------------------------------------------------
run-paper: ## Run bot in paper/dry-run mode (SAFE DEFAULT)
	@echo "[PAPER MODE] Starting bot in dry-run mode..."
	bash scripts/run_paper.sh

run-real: ## Run bot in REAL trading mode (requires operator gates)
	@echo "[REAL MODE] Verifying operator gates..."
	bash scripts/verify_mode_lock.sh
	bash scripts/run_real.sh

# ----- Validation --------------------------------------------------
backtest: ## Run deterministic backtest
	bash scripts/run_backtest.sh

walk-forward: ## Run walk-forward validation
	bash scripts/run_walk_forward.sh

shadow: ## Run paper shadow mode
	bash scripts/run_shadow.sh

promote: ## Run promotion workflow
	bash scripts/promote_strategy.sh

# ----- Dashboard ---------------------------------------------------
dashboard: ## Start operations dashboard
	$(PYTHON) -m uvicorn custom_app.dashboard.app:app --host 0.0.0.0 --port $${DASHBOARD_PORT:-8080} --reload

# ----- Tests -------------------------------------------------------
test: test-unit test-integration test-regression ## Run all tests

test-unit: ## Run unit tests
	$(PYTHON) -m pytest tests/unit/ -v --tb=short

test-integration: ## Run integration tests
	$(PYTHON) -m pytest tests/integration/ -v --tb=short

test-regression: ## Run regression tests
	$(PYTHON) -m pytest tests/regression/ -v --tb=short

test-coverage: ## Run tests with coverage report
	$(PYTHON) -m pytest tests/ --cov=custom_app --cov-report=html --cov-report=term-missing --cov-fail-under=80
	@echo "Coverage report: htmlcov/index.html"

# ----- Safety ------------------------------------------------------
verify-mode-lock: ## Verify mode lock is properly enforced
	bash scripts/verify_mode_lock.sh

emergency-flatten: ## Emergency: flatten all open positions
	@echo "EMERGENCY FLATTEN — press Ctrl+C to cancel. You have 5 seconds."
	@sleep 5
	bash scripts/emergency_flatten.sh

# ----- Code Quality ------------------------------------------------
lint: ## Run linter and type checker
	$(PYTHON) -m ruff check custom_app/ tests/
	$(PYTHON) -m mypy custom_app/ --ignore-missing-imports

format: ## Format code
	$(PYTHON) -m ruff format custom_app/ tests/

# ----- Docker ------------------------------------------------------
docker-up: ## Start all services
	docker-compose up -d

docker-down: ## Stop all services
	docker-compose down

docker-logs: ## Follow all service logs
	docker-compose logs -f

# ----- Cleanup -----------------------------------------------------
clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete
	rm -rf .pytest_cache htmlcov .coverage .mypy_cache
