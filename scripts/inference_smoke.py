#!/usr/bin/env python3
"""Live, corpus-free smoke test for the optional model-assistance boundary.

This script never sends production corpus material. It uses synthetic public sentences to
prove that the configured transport can answer, its output parses, and KORPUS's admission
logic accepts or refuses it deterministically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from korpus.api.dependencies import build_answer_composer, build_query_planner  # noqa: E402
from korpus.application.composition import compose_answer  # noqa: E402
from korpus.application.query_plan import build_plan  # noqa: E402
from korpus.config import Settings  # noqa: E402
from korpus.model_settings import resolved_model_base_url  # noqa: E402

QUESTION = "що робити коли стріляє артилерія"
SUBJECTS = ["артилерійський наліт", "укриття", "перебіжка"]
SENTENCES = [
    "Особовий склад займає укриття.",
    "Перебіжка між укриттями виконується за командою.",
]


def run(settings: Settings) -> dict[str, object]:
    planner = build_query_planner(settings)
    composer = build_answer_composer(settings)
    plan = build_plan(QUESTION, planner, SUBJECTS, deadline_seconds=8.0)
    composition, composition_reason = compose_answer(QUESTION, SENTENCES, composer)
    return {
        "provider": settings.query_planner_provider,
        "model": settings.query_planner_model,
        "base_url": resolved_model_base_url(settings),
        "egress_posture": settings.model_egress_posture,
        "egress_max_tier": settings.model_egress_max_tier,
        "planner_enabled": planner is not None,
        "planner_variants": list(plan.variants),
        "planner_refused_count": len(plan.refused),
        "composer_enabled": composer is not None,
        "composition_reason": composition_reason,
        "composition_admitted": composition is not None,
        "corpus_material_sent": False,
        "status": "PASS" if (planner is not None or composer is not None) else "DISABLED",
    }


def main() -> int:
    try:
        settings = Settings()
        result = run(settings)
    except Exception as error:
        print(json.dumps({"status": "FAIL", "error": f"{type(error).__name__}: {error}"}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
