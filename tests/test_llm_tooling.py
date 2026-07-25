"""Tests for structured-output retry, adapter retry semantics, and LLM tracing."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.interactive import LLMIntentPlanner, ScenarioLoader
from modules.interactive.llm_planner import OpenAICompatibleChatModel

ROOT = Path(__file__).resolve().parents[1]


class ScriptedModel:
    """Returns queued responses in order; repeats the last one when drained."""

    supports_json_mode = True

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def completion(self, prompt: str, **kwargs: object) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


class AdapterRetryTests(unittest.TestCase):
    def test_retry_kwarg_drives_real_attempts(self):
        adapter = OpenAICompatibleChatModel(
            base_url="http://127.0.0.1:9/v1",
            model="test",
            api_key="test",
        )
        attempts: list[int] = []

        def flaky(prompt: str, **kwargs: object) -> str:
            attempts.append(1)
            if len(attempts) < 2:
                raise RuntimeError("transient failure")
            return "ok"

        adapter._request_once = flaky
        self.assertEqual(adapter.completion("hi", retry=3), "ok")
        self.assertEqual(len(attempts), 2)

    def test_exhausted_retries_raise_last_error(self):
        adapter = OpenAICompatibleChatModel(
            base_url="http://127.0.0.1:9/v1",
            model="test",
            api_key="test",
        )

        def always_fail(prompt: str, **kwargs: object) -> str:
            raise RuntimeError("permanent failure")

        adapter._request_once = always_fail
        with self.assertRaises(RuntimeError):
            adapter.completion("hi", retry=2)


class UsageScriptedModel(ScriptedModel):
    def __init__(self, responses: list[str], usage: dict[str, int]):
        super().__init__(responses)
        self._usage = usage

    def consume_last_usage(self) -> dict[str, int]:
        return dict(self._usage)


class TokenAccountingTests(unittest.TestCase):
    def test_adapter_stores_and_consumes_usage_once(self):
        adapter = OpenAICompatibleChatModel(
            base_url="http://127.0.0.1:9/v1", model="test", api_key="test",
        )
        adapter._record_usage({"prompt_tokens": 5, "completion_tokens": 7})
        self.assertEqual(
            adapter.consume_last_usage(),
            {"prompt_tokens": 5, "completion_tokens": 7},
        )
        self.assertIsNone(adapter.consume_last_usage())

    def test_planner_accumulates_usage_into_state_flags(self):
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("usage-test", seed=4)
        actor_id = sorted(state.agents)[0]
        model = UsageScriptedModel(
            [json.dumps({"action_type": "wait", "reason": "等待"}, ensure_ascii=False)],
            {"prompt_tokens": 111, "completion_tokens": 22},
        )
        planner = LLMIntentPlanner(model)
        planner.plan(state, loaded.scenario, actor_ids=[actor_id])
        totals = state.flags["token_usage"]["totals"]
        self.assertEqual(totals["prompt_tokens"], 111)
        self.assertEqual(totals["completion_tokens"], 22)
        self.assertEqual(totals["calls"], 1)
        per_agent = state.flags["token_usage"]["by_agent"][actor_id]
        self.assertEqual(per_agent["prompt_tokens"], 111)


class PlannerRetryAndTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        cls.scenario = cls.loaded.scenario

    def setUp(self):
        self.state = self.loaded.create_game_state("tooling-test", seed=3)
        self.actor_id = sorted(self.state.agents)[0]

    def test_invalid_output_is_retried_with_error_feedback(self):
        valid = json.dumps({
            "action_type": "wait",
            "reason": "观察局势",
        }, ensure_ascii=False)
        model = ScriptedModel(["这不是 JSON", valid])
        planner = LLMIntentPlanner(model)
        intents = planner.plan(self.state, self.scenario, actor_ids=[self.actor_id])
        self.assertEqual(len(intents), 1)
        self.assertEqual(intents[0].metadata.get("planner_source"), "llm")
        self.assertEqual(len(model.calls), 2)
        retry_prompt = str(model.calls[1]["prompt"])
        self.assertIn("上一次的输出无效", retry_prompt)
        self.assertIn("无法解析", retry_prompt)

    def test_json_mode_is_requested_from_capable_models(self):
        model = ScriptedModel([json.dumps({
            "action_type": "wait", "reason": "等待",
        }, ensure_ascii=False)])
        planner = LLMIntentPlanner(model)
        planner.plan(self.state, self.scenario, actor_ids=[self.actor_id])
        self.assertTrue(all(call.get("json_mode") for call in model.calls))

    def test_prompts_and_responses_are_traced_to_jsonl(self):
        valid = json.dumps({
            "action_type": "wait", "reason": "等待",
        }, ensure_ascii=False)
        with TemporaryDirectory() as tmp:
            planner = LLMIntentPlanner(
                ScriptedModel(["坏输出", valid]), trace_root=tmp,
            )
            planner.plan(self.state, self.scenario, actor_ids=[self.actor_id])
            trace_path = (
                Path(tmp) / "interactive" / self.state.game_id
                / "llm_trace" / "round-01.jsonl"
            )
            self.assertTrue(trace_path.is_file())
            records = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [record["stage"] for record in records],
                ["intent", "intent_retry"],
            )
            self.assertEqual(records[0]["agent_id"], self.actor_id)
            self.assertIn("prompt", records[0])
            self.assertEqual(records[0]["response"], "坏输出")


if __name__ == "__main__":
    unittest.main()
