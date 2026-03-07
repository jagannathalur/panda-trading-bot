"""
Promotion — Strategy validation and promotion pipeline.

Every strategy must pass:
  backtest → walk-forward → paper_shadow → (operator approval) → live

Promotion eligibility does NOT imply real trading is enabled.

Public API:
    PromotionState, PromotionArtifact, PromotionPipeline, StrategyRegistry
"""

from custom_app.promotion.states import PromotionState
from custom_app.promotion.artifacts import PromotionArtifact
from custom_app.promotion.pipeline import PromotionPipeline
from custom_app.promotion.registry import StrategyRegistry

__all__ = ["PromotionState", "PromotionArtifact", "PromotionPipeline", "StrategyRegistry"]
