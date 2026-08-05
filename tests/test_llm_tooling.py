"""Tests for structured-output retry, adapter retry semantics, and LLM tracing."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.interactive import HeuristicIntentPlanner, LLMIntentPlanner, ScenarioLoader
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


class FailingModel:
    supports_json_mode = True

    def __init__(self):
        self.calls = 0

    def completion(self, prompt: str, **kwargs: object) -> str:
        self.calls += 1
        raise ConnectionError("remote provider unavailable")


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

    def test_json_mode_kwarg_does_not_collide_with_retry_loop(self):
        adapter = OpenAICompatibleChatModel(
            base_url="http://127.0.0.1:9/v1", model="test", api_key="test",
        )
        seen: list[bool] = []

        def fake(prompt: str, *, json_mode: bool = False, **kwargs: object) -> str:
            seen.append(json_mode)
            return "ok"

        adapter._request_once = fake
        self.assertEqual(
            adapter.completion("hi", retry=2, json_mode=True, caller="x"), "ok",
        )
        self.assertEqual(seen, [True])

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

    def test_remote_failure_uses_local_model_before_heuristic(self):
        remote = FailingModel()
        local = ScriptedModel([json.dumps({
            "action_type": "wait", "reason": "先观察片刻",
        }, ensure_ascii=False)])
        planner = LLMIntentPlanner(
            remote,
            provider_name="deepseek:test",
            model_fallbacks=[("ollama:qwen2.5:7b-instruct", local)],
        )

        intents = planner.plan(
            self.state, self.scenario, actor_ids=[self.actor_id],
        )

        self.assertEqual(remote.calls, 1)
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(
            intents[0].metadata.get("planner_source"), "llm_local_fallback",
        )
        self.assertEqual(
            intents[0].metadata.get("planner_provider"),
            "ollama:qwen2.5:7b-instruct",
        )

    def test_conversation_prompt_leaves_social_response_to_character(self):
        speaker_id = next(
            agent_id for agent_id in sorted(self.state.agents)
            if agent_id != self.actor_id
        )
        model = ScriptedModel([json.dumps({
            "content": "嗯，我在听。",
            "share_belief_id": None,
            "item_disposition": "none",
            "display_object_id": None,
        }, ensure_ascii=False)])
        planner = LLMIntentPlanner(model)

        response = planner.respond_to_player(
            self.state, self.scenario, speaker_id, self.actor_id, "楼主！",
        )

        prompt = str(model.calls[0]["prompt"])
        self.assertEqual(response["content"], "嗯，我在听。")
        self.assertIn("自由回应", prompt)
        self.assertIn("寒暄可以只作自然回应", prompt)
        self.assertNotIn("你可以回避、反问、撒谎或交换情报", prompt)

    def test_emergency_fallback_does_not_dump_intel_on_a_greeting(self):
        speaker_id = next(
            agent_id for agent_id in sorted(self.state.agents)
            if agent_id not in {self.actor_id, self.state.flags.get("killer_id")}
        )
        planner = HeuristicIntentPlanner(seed=4)

        response = planner.respond_to_player(
            self.state, self.scenario, speaker_id, self.actor_id, "楼主！",
        )

        self.assertIsNone(response["share_belief_id"])
        self.assertIn(self.state.agents[self.actor_id].display_name, response["content"])

    def test_valid_llm_vote_is_accepted_not_silently_discarded(self):
        candidates = [
            agent_id for agent_id in sorted(self.state.agents)
            if agent_id != self.actor_id
        ]
        vote_json = json.dumps({
            "suspect_id": candidates[0],
            "reason": "他在案发前后行踪矛盾。",
            "answers": [],
            "case_conclusion": {"killer": candidates[0]},
            "personal_task_answers": [],
        }, ensure_ascii=False)
        model = ScriptedModel([vote_json])
        planner = LLMIntentPlanner(model)
        decision = planner.vote(self.state, self.scenario, self.actor_id)
        self.assertEqual(decision.get("_model_source"), "llm")
        self.assertEqual(decision.get("suspect_id"), candidates[0])
        self.assertEqual(len(model.calls), 1, "合法投票不应触发重试")
        self.assertGreaterEqual(
            int(model.calls[0].get("max_tokens", 0)), 1500,
            "终局提交需要足够的输出预算,避免 JSON 被截断",
        )

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
