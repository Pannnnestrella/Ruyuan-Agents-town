"""Make one real model call to validate interactive intent generation."""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.interactive import LLMIntentPlanner, ScenarioLoader


def main() -> int:
    loaded = ScenarioLoader(ROOT).load("stormbound_inn")
    state = loaded.create_game_state("llm-smoke")
    planner = LLMIntentPlanner.from_project_config(ROOT)
    participant = next(
        item for item in loaded.scenario["participants"] if item["id"] == "广陵王"
    )
    prompt = planner._build_prompt(state, loaded.scenario, participant)
    response = planner.model.completion(
        prompt,
        retry=1,
        failsafe=None,
        caller="interactive_smoke",
        temperature=0.4,
    )
    intent = planner._parse_intent("广陵王", response)
    if intent is None:
        print(json.dumps({"ok": False, "error": "model output was not a valid intent"}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "ok": True,
        "actor_id": intent.actor_id,
        "action_type": intent.action_type.value,
        "target_id": intent.target_id,
        "location_id": intent.location_id,
        "object_id": intent.object_id,
        "reason": intent.reason,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
