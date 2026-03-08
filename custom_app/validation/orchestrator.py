"""
Validation orchestrator — runs the full validation pipeline.

Pipeline: backtest → walk_forward → paper_shadow → promotion_artifact

Each stage must pass before the next can run.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from custom_app.promotion.artifacts import PromotionArtifact

logger = logging.getLogger(__name__)


@dataclass
class ValidationConfig:
    """Configuration for a validation run."""
    strategy_id: str
    strategy_version: str
    freqtrade_dir: str = "./freqtrade"
    user_data_dir: str = "./user_data"
    config_paths: list[str] = None  # type: ignore
    timerange: str = "20230101-20231231"
    walk_forward_windows: int = 5
    shadow_min_hours: int = 72
    artifacts_dir: str = "./data/artifacts"

    def __post_init__(self):
        if self.config_paths is None:
            self.config_paths = ["configs/base.json", "configs/paper.json"]


class ValidationOrchestrator:
    """
    Orchestrates the full validation pipeline for a strategy.

    Produces a PromotionArtifact on success.
    """

    def __init__(self, config: ValidationConfig) -> None:
        self._config = config
        self._ft_dir = Path(config.freqtrade_dir)

    def run_full_pipeline(
        self,
        code_commit: str,
        config_hash: str,
        feature_set_version: str = "1.0.0",
        parameter_manifest: Optional[dict] = None,
    ) -> PromotionArtifact:
        """
        Run the full validation pipeline.

        Returns a PromotionArtifact if all stages pass.
        Raises RuntimeError if any stage fails.
        """
        logger.info(
            "[Validation] Starting full pipeline for %s@%s",
            self._config.strategy_id,
            self._config.strategy_version,
        )

        self._validate_config_paths()

        artifact = PromotionArtifact(
            strategy_id=self._config.strategy_id,
            version=self._config.strategy_version,
            code_commit=code_commit,
            config_hash=config_hash,
            feature_set_version=feature_set_version,
            parameter_manifest=parameter_manifest or {},
            passed=False,
        )

        # Stage 1: Backtest
        try:
            bt_report = self._run_backtest()
            artifact.backtest_report = bt_report
            logger.info("[Validation] Backtest PASSED")
        except Exception as exc:
            artifact.fail_reason = f"Backtest failed: {exc}"
            artifact.save(self._config.artifacts_dir)
            raise RuntimeError(f"Validation failed at backtest stage: {exc}")

        # Stage 2: Walk-forward
        try:
            wf_report = self._run_walk_forward()
            artifact.walk_forward_report = wf_report
            logger.info("[Validation] Walk-forward PASSED (%d/%d windows)",
                        wf_report["passed"], wf_report["total"])
        except Exception as exc:
            artifact.fail_reason = f"Walk-forward failed: {exc}"
            artifact.save(self._config.artifacts_dir)
            raise RuntimeError(f"Validation failed at walk-forward stage: {exc}")

        # Stage 3: Shadow (long-running, started separately)
        logger.info(
            "[Validation] Shadow stage requires %dh of paper run. "
            "Run make shadow to start shadow mode separately.",
            self._config.shadow_min_hours,
        )

        artifact.shadow_report = {
            "status": "pending",
            "required_min_hours": self._config.shadow_min_hours,
            "note": "Paper shadow must complete before this artifact can pass.",
        }
        artifact.fail_reason = (
            f"Paper shadow pending: run shadow mode for at least "
            f"{self._config.shadow_min_hours}h before promotion."
        )
        saved_path = artifact.save(self._config.artifacts_dir)
        logger.info("[Validation] Shadow pending artifact saved: %s", saved_path)

        self._audit_completion(artifact)
        return artifact

    def _validate_config_paths(self) -> None:
        """Raise FileNotFoundError if any config file is missing."""
        for cp in self._config.config_paths:
            if not Path(cp).exists():
                raise FileNotFoundError(
                    f"Config file not found: {cp}. "
                    f"Check ValidationConfig.config_paths."
                )

    def _run_backtest(self) -> dict:
        """Run deterministic backtest via Freqtrade CLI."""
        cmd = [
            "python3", "-m", "freqtrade", "backtesting",
            "--strategy", self._config.strategy_id,
            "--timerange", self._config.timerange,
            "--userdir", self._config.user_data_dir,
        ]
        for cp in self._config.config_paths:
            cmd += ["--config", cp]

        logger.info("[Validation] Running backtest: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self._ft_dir)

        if result.returncode != 0:
            raise RuntimeError(f"Backtest failed:\n{result.stderr}")

        return {
            "command": " ".join(cmd),
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-2000:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _run_walk_forward(self) -> dict:
        """
        Run walk-forward validation via rolling backtest windows.

        Splits the configured timerange into N equal windows and runs a
        backtest for each window's out-of-sample period.
        All windows must pass for walk-forward to succeed.
        """
        try:
            start_str, end_str = self._config.timerange.split("-")
            start = datetime.strptime(start_str, "%Y%m%d")
            end = datetime.strptime(end_str, "%Y%m%d")
        except (ValueError, AttributeError) as exc:
            raise RuntimeError(
                f"Invalid timerange format '{self._config.timerange}'. "
                f"Expected YYYYMMDD-YYYYMMDD: {exc}"
            )

        total_days = (end - start).days
        window_days = total_days // self._config.walk_forward_windows

        if window_days < 7:
            raise RuntimeError(
                f"Walk-forward window too small ({window_days} days per window). "
                f"Increase timerange or reduce walk_forward_windows "
                f"(current: {self._config.walk_forward_windows})."
            )

        results = []
        n = self._config.walk_forward_windows
        logger.info("[Validation] Running %d walk-forward windows (%d days each)", n, window_days)

        for i in range(n):
            window_start = start + timedelta(days=i * window_days)
            # Last window absorbs any remaining days
            window_end = end if i == n - 1 else start + timedelta(days=(i + 1) * window_days)
            tr = f"{window_start.strftime('%Y%m%d')}-{window_end.strftime('%Y%m%d')}"

            logger.info("[Validation] Walk-forward window %d/%d: %s", i + 1, n, tr)

            cmd = [
                "python3", "-m", "freqtrade", "backtesting",
                "--strategy", self._config.strategy_id,
                "--timerange", tr,
                "--userdir", self._config.user_data_dir,
            ]
            for cp in self._config.config_paths:
                cmd += ["--config", cp]

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=self._ft_dir)
            window_result = {
                "window": i + 1,
                "timerange": tr,
                "returncode": result.returncode,
                "passed": result.returncode == 0,
                "stdout_tail": result.stdout[-1000:],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            results.append(window_result)

            if result.returncode != 0:
                raise RuntimeError(
                    f"Walk-forward window {i + 1}/{n} ({tr}) failed:\n"
                    f"{result.stderr[-500:]}"
                )

        passed_count = sum(1 for r in results if r["passed"])
        return {
            "windows": results,
            "total": n,
            "passed": passed_count,
            "pass_rate": passed_count / n,
        }

    def _audit_completion(self, artifact: PromotionArtifact) -> None:
        try:
            from custom_app.audit import AuditLogger, AuditEventType
            AuditLogger.get_instance().log_event(
                event_type=AuditEventType.BACKTEST_COMPLETED,
                actor="validation_orchestrator",
                action=f"Validation pipeline completed for {artifact.strategy_id}",
                details={"artifact_id": artifact.artifact_id, "passed": artifact.passed},
            )
        except Exception:
            pass
