"""
Promotion artifacts — validation evidence required before promotion.
Stale artifacts are automatically rejected.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PromotionArtifact:
    """Immutable promotion artifact generated after validation."""
    strategy_id: str
    version: str
    code_commit: str
    config_hash: str
    feature_set_version: str
    parameter_manifest: dict
    backtest_report: Optional[dict] = None
    walk_forward_report: Optional[dict] = None
    shadow_report: Optional[dict] = None
    generated_at: datetime = field(default_factory=_now_utc)
    passed: bool = False
    fail_reason: Optional[str] = None

    @property
    def artifact_id(self) -> str:
        raw = f"{self.strategy_id}:{self.version}:{self.generated_at.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_fresh(self, max_age_hours: Optional[float] = None) -> bool:
        max_hours = max_age_hours or float(os.environ.get("ARTIFACT_MAX_AGE_HOURS", "168"))
        age = _now_utc() - self.generated_at
        return age < timedelta(hours=max_hours)

    def assert_fresh(self, max_age_hours: Optional[float] = None) -> None:
        if not self.is_fresh(max_age_hours):
            max_hours = max_age_hours or float(os.environ.get("ARTIFACT_MAX_AGE_HOURS", "168"))
            age = _now_utc() - self.generated_at
            raise ValueError(
                f"Artifact for {self.strategy_id}@{self.version} is stale. "
                f"Age: {age.total_seconds() / 3600:.1f}h > max {max_hours}h. "
                "Re-run the full validation pipeline."
            )

    def assert_passed(self) -> None:
        if not self.passed:
            raise ValueError(
                f"Artifact for {self.strategy_id}@{self.version} did not pass. "
                f"Reason: {self.fail_reason or 'unknown'}. Fix and re-run validation."
            )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["generated_at"] = self.generated_at.isoformat()
        d["artifact_id"] = self.artifact_id
        d["is_fresh"] = self.is_fresh()
        return d

    def save(self, artifacts_dir: str) -> Path:
        path = Path(artifacts_dir) / f"{self.strategy_id}_{self.version}_{self.artifact_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        return path

    @classmethod
    def load(cls, path: str) -> "PromotionArtifact":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["generated_at"] = datetime.fromisoformat(data["generated_at"])
        data.pop("artifact_id", None)
        data.pop("is_fresh", None)
        return cls(**data)
