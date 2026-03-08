#!/usr/bin/env python3
"""Generate a weekly strategy review artifact."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from custom_app.reviews import generate_weekly_review  # noqa: E402


def main() -> int:
    review = generate_weekly_review()
    print(json.dumps({
        "review_id": review["review_id"],
        "generated_at": review["generated_at"],
        "strategy_id": review["strategy_id"],
        "recommendation": review["recommendation"],
        "operator_action": review["operator_action"],
        "report_file": review.get("report_file"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
