"""Tests for validation orchestrator semantics."""

from __future__ import annotations

from custom_app.validation.orchestrator import ValidationConfig, ValidationOrchestrator


def _config(tmp_path):
    config_path = tmp_path / "paper.json"
    config_path.write_text("{}", encoding="utf-8")
    return ValidationConfig(
        strategy_id="GridTrendV2",
        strategy_version="2.0.0",
        config_paths=[str(config_path)],
        artifacts_dir=str(tmp_path / "artifacts"),
    )


def test_full_pipeline_leaves_artifact_pending_until_shadow(monkeypatch, tmp_path):
    orchestrator = ValidationOrchestrator(_config(tmp_path))

    monkeypatch.setattr(
        orchestrator,
        "_run_backtest",
        lambda: {"status": "ok", "kind": "backtest"},
    )
    monkeypatch.setattr(
        orchestrator,
        "_run_walk_forward",
        lambda: {"status": "ok", "kind": "walk_forward", "passed": 5, "total": 5},
    )
    monkeypatch.setattr(orchestrator, "_audit_completion", lambda artifact: None)

    artifact = orchestrator.run_full_pipeline(
        code_commit="abc123",
        config_hash="def456",
    )

    assert artifact.passed is False
    assert artifact.shadow_report is not None
    assert artifact.shadow_report["status"] == "pending"
    assert "shadow" in (artifact.fail_reason or "").lower()
