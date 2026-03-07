"""Strategy version registry — tracks all strategies and their promotion states."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from custom_app.promotion.pipeline import PromotionPipeline
from custom_app.promotion.states import PromotionState

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """In-memory registry of strategy promotion pipelines. Thread-safe. Persistent."""

    def __init__(self, registry_path: str = "./data/strategy_registry.json") -> None:
        self._pipelines: dict[str, PromotionPipeline] = {}
        self._lock = threading.Lock()
        self._registry_path = Path(registry_path)
        self._load()

    def register(self, strategy_id: str) -> PromotionPipeline:
        """Register strategy. Returns existing pipeline if already registered."""
        with self._lock:
            if strategy_id not in self._pipelines:
                self._pipelines[strategy_id] = PromotionPipeline(strategy_id)
                self._save()
                logger.info("[Registry] Registered strategy: %s", strategy_id)
            return self._pipelines[strategy_id]

    def get(self, strategy_id: str) -> Optional[PromotionPipeline]:
        with self._lock:
            return self._pipelines.get(strategy_id)

    def all_statuses(self) -> list[dict]:
        with self._lock:
            return [p.get_status() for p in self._pipelines.values()]

    def _save(self) -> None:
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            sid: {"current_state": str(p.current_state), "history": p._history}
            for sid, p in self._pipelines.items()
        }
        with open(self._registry_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        if not self._registry_path.exists():
            return
        try:
            with open(self._registry_path) as f:
                data = json.load(f)
            for sid, info in data.items():
                pipeline = PromotionPipeline(sid, PromotionState(info["current_state"]))
                pipeline._history = info.get("history", [])
                self._pipelines[sid] = pipeline
        except Exception as exc:
            logger.warning("[Registry] Failed to load: %s", exc)
