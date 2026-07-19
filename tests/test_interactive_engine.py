from __future__ import annotations

import unittest
import time
from tempfile import TemporaryDirectory
from pathlib import Path

from modules.interactive import (
    ActionIntent,
    ActionType,
    EventDirector,
    GameSession,
    GamePhase,
    LifeState,
    LLMIntentPlanner,
    RoundEngine,
    ScenarioLoader,
    TriggerResolver,
)


ROOT = Path(__file__).resolve().parents[1]


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        self.state = self.loaded.create_game_state("test-game")

    def test_scenario_loads_with_six_characters_and_three_actions_for_six_rounds(self):
        self.assertEqual(len(self.state.agents), 6)
        self.assertEqual(self.state.max_rounds, 6)
        self.assertEqual(self.state.actions_per_round, 3)
        self.assertIn("lobby", self.state.locations)
        self.assertIn("courier_body", self.state.objects)
        self.assertGreaterEqual(len(self.loaded.scenario["event_cards"]), 30)
        self.assertGreaterEqual(len(self.loaded.scenario["public_intel"]), 12)
        for location_id in self.state.locations:
            clues = [
                item for item in self.state.objects.values()
                if item.location_id == location_id
            ]
            self.assertGreaterEqual(len(clues), 2, location_id)
        self.assertEqual(
            {secret.owner_id for secret in self.state.secrets.values() if secret.category == "personal"},
            set(self.state.agents),
        )

    def test_exactly_one_character_receives_the_private_killer_memory(self):
        killer_id = self.state.flags["killer_id"]
        holders = [
            agent.agent_id
            for agent in self.state.agents.values()
            if any(belief.source == "凶手记忆" for belief in agent.beliefs)
        ]
        self.assertEqual(holders, [killer_id])
        public_text = str(self.state.public_view())
        self.assertNotIn("killer_id", public_text)
        self.assertNotIn("凶手记忆", public_text)

    def test_seed_selects_a_complete_self_consistent_case_variant(self):
        expected = {
            0: ("孙策", "jiangdong-forged-order", {
                "jiangdong_forged_order", "chipped_spur_buckle"
            }),
            1: ("傅融", "east-safehouse-letter", {
                "east_safehouse_list", "dark_teal_silk_thread"
            }),
            5: ("袁基", "yuan-branch-purchase", {
                "yuan_purchase_correspondence", "yuan_watermark_wax_paper"
            }),
        }
        for seed, (killer_id, case_id, object_ids) in expected.items():
            with self.subTest(seed=seed):
                first = self.loaded.create_game_state(f"variant-{seed}-a", seed=seed)
                second = self.loaded.create_game_state(f"variant-{seed}-b", seed=seed)
                self.assertEqual(first.flags["killer_id"], killer_id)
                self.assertEqual(first.flags["case_manifest"], second.flags["case_manifest"])
                self.assertEqual(first.flags["case_manifest"]["case_id"], case_id)
                active_variant_ids = {
                    item.object_id for item in first.objects.values()
                    if "case_variant" in item.tags
                }
                self.assertEqual(active_variant_ids, object_ids)
                self.assertTrue(object_ids.issubset(first.objects))
                stolen_id = first.flags["case_manifest"]["stolen_item_id"]
                self.assertEqual(first.objects[stolen_id].holder_id, killer_id)
                self.assertIn(stolen_id, first.agents[killer_id].inventory)
                for candidate_id in {"傅融", "孙策", "袁基"} - {killer_id}:
                    self.assertTrue(any(
                        belief.source == "个人经历"
                        for belief in first.agents[candidate_id].beliefs
                    ))
                public_text = str(first.public_view())
                self.assertNotIn(case_id, public_text)
                self.assertNotIn("case_manifest", public_text)

    def test_private_objects_do_not_leak_into_public_state(self):
        public_objects = self.state.public_view()["objects"]
        self.assertNotIn("palace_token", public_objects)
        self.assertNotIn("yuan_sealed_letter", public_objects)
        private_objects = self.state.to_dict(include_private=True)["objects"]
        self.assertIn("palace_token", private_objects)

    def test_strategic_plans_are_initialized_but_never_public(self):
        self.assertTrue(all(agent.strategic_plan for agent in self.state.agents.values()))
        public_agents = self.state.public_view()["agents"]
        self.assertTrue(all("strategic_plan" not in agent for agent in public_agents.values()))
        self.assertTrue(all("plan_history" not in agent for agent in public_agents.values()))

    def test_director_suggests_one_card_from_each_category(self):
        director = EventDirector(self.loaded.scenario["event_cards"], seed=4)
        cards = director.suggest(self.state)
        self.assertEqual({card.category for card in cards}, {
            "pressure", "information", "relationship"
        })
        for card in cards:
            public_card = card.to_dict()
            self.assertNotIn("hidden_consequence", public_card)
            self.assertNotIn("effects", public_card)
            self.assertNotIn("preconditions", public_card)

    def test_card_application_changes_flags_and_is_not_repeatable(self):
        director = EventDirector(self.loaded.scenario["event_cards"], seed=0)
        events = director.apply(self.state, "pressure-horses")
        self.assertTrue(self.state.flags["stable_in_disarray"])
        self.assertEqual(self.state.phase, GamePhase.READY)
        self.assertTrue(any(event.public for event in events))
        with self.assertRaises(ValueError):
            director.apply(self.state, "pressure-horses")

    def test_delayed_trigger_changes_world_only_when_due(self):
        resolver = TriggerResolver(self.loaded.scenario["round_triggers"])
        self.state.flags["guards_arrival_round"] = 2
        self.state.round_number = 0
        self.assertEqual(resolver.apply_due(self.state), [])
        self.state.round_number = 1
        events = resolver.apply_due(self.state)
        self.assertTrue(self.state.flags["guards_arrived"])
        self.assertEqual(events[0].event_type, "world_trigger")

    def test_uninvestigated_evidence_can_be_destroyed_by_delayed_world_event(self):
        resolver = TriggerResolver(self.loaded.scenario["round_triggers"])
        self.state.flags["stable_damage_round"] = 1
        events = resolver.apply_due(self.state)
        item = self.state.objects["wet_footprints"]
        self.assertIsNone(item.location_id)
        self.assertEqual(item.metadata["removed_reason"], "stable_in_disarray")
        self.assertEqual(events[0].event_type, "evidence_lost")

    def test_director_keeps_three_choices_after_authored_cards_are_exhausted(self):
        director = EventDirector(self.loaded.scenario["event_cards"], seed=0)
        self.state.round_number = 8
        self.state.used_event_cards = [card["id"] for card in self.loaded.scenario["event_cards"]]
        cards = director.suggest(self.state)
        self.assertEqual(len(cards), 3)
        self.assertEqual({card.category for card in cards}, {
            "pressure", "information", "relationship"
        })
        self.assertTrue(all(card.card_id.startswith("director-") for card in cards))


class RoundEngineTests(unittest.TestCase):
    def setUp(self):
        self.loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        self.state = self.loaded.create_game_state("round-test")
        self.engine = RoundEngine(seed=1)

    def test_round_resolves_actions_and_creates_wait_events(self):
        result = self.engine.resolve_round(
            self.state,
            [
                ActionIntent("广陵王", ActionType.INVESTIGATE, location_id="lobby"),
                ActionIntent("傅融", ActionType.MOVE, location_id="upper_hall"),
            ],
        )
        self.assertEqual(result.round_number, 1)
        self.assertEqual(self.state.agents["傅融"].location_id, "upper_hall")
        self.assertEqual(len(result.events), 6)
        self.assertEqual(self.state.phase, GamePhase.ROUND_COMPLETE)

    def test_only_one_major_action_is_accepted_per_actor(self):
        result = self.engine.resolve_round(
            self.state,
            [
                ActionIntent("广陵王", ActionType.INVESTIGATE, location_id="lobby"),
                ActionIntent("广陵王", ActionType.WAIT),
            ],
        )
        self.assertEqual(len(result.rejected_intents), 1)
        self.assertIn("one major action", result.rejected_intents[0]["reason"])

    def test_attack_is_world_adjudicated_and_updates_life_state(self):
        self.state.agents["孙策"].location_id = "lobby"
        self.state.agents["刘辩"].location_id = "lobby"
        self.state.flags["killer_id"] = "傅融"
        self.state.agents["刘辩"].health = 60
        self.engine.random.random = lambda: 0.0
        result = self.engine.resolve_round(
            self.state,
            [
                ActionIntent(
                    "孙策",
                    ActionType.ATTACK,
                    target_id="刘辩",
                )
            ],
        )
        self.assertEqual(self.state.agents["刘辩"].health, 48)
        self.assertEqual(self.state.agents["刘辩"].life_state, LifeState.INJURED)
        self.assertEqual(result.events[0].event_type, "attack")
        self.assertEqual(result.events[0].payload["ability_id"], "swift_restraint")


class GameSessionTests(unittest.TestCase):
    def setUp(self):
        self.loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        self.temporary_results = TemporaryDirectory()
        self.session = GameSession(
            self.loaded,
            self.loaded.create_game_state("session-test"),
            results_root=self.temporary_results.name,
            seed=3,
        )

    def tearDown(self):
        self.temporary_results.cleanup()

    def test_notice_is_a_reported_belief_not_an_objective_truth(self):
        notice = self.session.post_notice("亥时后任何人不得离开客栈。")
        self.assertIn("广陵王", notice.seen_by)
        beliefs = self.session.state.agents["广陵王"].beliefs
        received = next(belief for belief in beliefs if belief.source == notice.notice_id)
        self.assertEqual(received.stance, "reported")
        self.assertTrue(received.claim.startswith("公告板声称："))
        self.assertNotIn("傅融", notice.seen_by)

    def test_card_and_round_form_a_persisted_interactive_cycle(self):
        cards = self.session.card_suggestions()
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards, self.session.card_suggestions())
        self.session.select_event_card(cards[0]["card_id"])
        selected_event = next(
            event for event in self.session.state.events
            if event.event_type == "event_card_selected"
        )
        self.assertTrue(selected_event.payload["title"])
        self.assertTrue(selected_event.payload["description"])
        result = self.session.advance_round()
        self.assertEqual(result.round_number, 1)
        self.assertEqual(self.session.state.phase, GamePhase.INTERVENTION)
        self.assertIsNone(self.session.state.active_event_card)
        game_dir = Path(self.temporary_results.name) / "interactive" / "session-test"
        self.assertTrue((game_dir / "state.json").is_file())
        self.assertTrue((game_dir / "round-01.json").is_file())

    def test_character_plan_survives_and_accumulates_outcomes_across_rounds(self):
        initial_objective = self.session.state.agents["广陵王"].strategic_plan["objective"]
        for expected_round in (1, 2):
            quiet = self.session.empty_event_option()
            self.session.select_event_card(quiet["card_id"])
            self.session.advance_round()
            agent = self.session.state.agents["广陵王"]
            self.assertEqual(agent.strategic_plan["updated_round"], expected_round)
            self.assertEqual(len(agent.plan_history), expected_round * 3)
            self.assertTrue(agent.plan_history[-1]["outcome"])
        self.assertEqual(
            self.session.state.agents["广陵王"].strategic_plan["objective"],
            initial_objective,
        )
        public_text = str(self.session.public_state())
        self.assertNotIn("plan_history", public_text)
        saved = (
            Path(self.temporary_results.name)
            / "interactive" / "session-test" / "state.json"
        ).read_text(encoding="utf-8")
        self.assertIn('"strategic_plan"', saved)
        self.assertIn('"plan_history"', saved)

    def test_six_rounds_offer_eighteen_nonrepeating_cards_and_quiet_is_available(self):
        offered = []
        for _ in range(6):
            cards = self.session.card_suggestions()
            offered.extend(card["card_id"] for card in cards)
            quiet = self.session.empty_event_option()
            self.assertEqual(quiet["category"], "quiet")
            self.session.select_event_card(quiet["card_id"])
            self.session.advance_round()
        self.assertEqual(len(offered), 18)
        self.assertEqual(len(set(offered)), 18)

    def test_public_intel_reaches_every_character_immediately(self):
        intel = self.session.intel_suggestions()[0]
        published, event = self.session.publish_public_intel(intel["id"])
        self.assertEqual(published["id"], intel["id"])
        for agent in self.session.state.agents.values():
            self.assertTrue(any(belief.source == event.event_id for belief in agent.beliefs))
        self.assertEqual(self.session.state.public_intel_history[0]["claim"], intel["claim"])
        self.assertEqual(event.payload["title"], intel["title"])
        self.assertEqual(event.payload["claim"], intel["claim"])

    def test_round_requires_player_to_choose_a_card(self):
        with self.assertRaisesRegex(ValueError, "Select one"):
            self.session.advance_round()

    def test_player_cannot_select_a_card_outside_the_frozen_three(self):
        suggestions = self.session.card_suggestions()
        all_ids = {card["id"] for card in self.loaded.scenario["event_cards"]}
        unoffered = next(card_id for card_id in all_ids if card_id not in {
            card["card_id"] for card in suggestions
        })
        with self.assertRaisesRegex(ValueError, "three suggestions"):
            self.session.select_event_card(unoffered)

    def test_discoveries_and_conversations_update_personal_beliefs(self):
        first_cards = self.session.card_suggestions()
        self.session.select_event_card(first_cards[0]["card_id"])
        result = self.session.advance_round([
            ActionIntent("广陵王", ActionType.INVESTIGATE, location_id="lobby"),
            ActionIntent("刘辩", ActionType.MOVE, location_id="upper_hall"),
        ])
        discovery = next(event for event in result.events if event.event_type == "discovery")
        self.assertTrue(any(
            belief.source == discovery.event_id
            for belief in self.session.state.agents["广陵王"].beliefs
        ))

        self.session.state.agents["广陵王"].location_id = "lobby"
        self.session.state.agents["刘辩"].location_id = "lobby"
        self.session.select_event_card(self.session.card_suggestions()[0]["card_id"])
        result = self.session.advance_round([
            ActionIntent(
                "广陵王",
                ActionType.TALK,
                target_id="刘辩",
                content="死者所说的暗语，你是否曾经听过？",
            )
        ])
        conversation = next(event for event in result.events if event.event_type == "conversation")
        received = next(
            belief for belief in self.session.state.agents["刘辩"].beliefs
            if belief.source == conversation.event_id
        )
        self.assertEqual(received.stance, "reported")
        self.assertIn("广陵王声称", received.claim)

    def test_six_round_game_writes_evidence_based_recap(self):
        self.session.post_notice("所有住客若发现密信，须先在大堂登记。")
        for _ in range(6):
            cards = self.session.card_suggestions()
            self.assertEqual(len(cards), 3)
            self.session.select_event_card(cards[0]["card_id"])
            self.session.advance_round()
        self.assertEqual(self.session.state.phase, GamePhase.FINISHED)
        recap = self.session.build_recap()
        self.assertEqual(recap["rounds_completed"], 6)
        self.assertEqual(len(recap["characters"]), 6)
        self.assertEqual(len(recap["voting_result"]["votes"]), 6)
        self.assertTrue(recap["voting_result"]["killer_name"])
        self.assertEqual(recap["player_notices"][0]["content"], "所有住客若发现密信，须先在大堂登记。")
        game_dir = Path(self.temporary_results.name) / "interactive" / "session-test"
        self.assertTrue((game_dir / "recap.json").is_file())
        self.assertTrue((game_dir / "recap.md").is_file())
        self.assertTrue((game_dir / "story-outline.json").is_file())
        self.assertTrue((game_dir / "story-outline.md").is_file())
        outline = self.session.build_story_outline()
        self.assertEqual(len(outline["acts"]), 3)
        source_ids = {
            event["event_id"]
            for events in recap["timeline"].values()
            for event in events
        }
        self.assertTrue(set(outline["source_event_ids"]).issubset(source_ids))


class FakeModel:
    def __init__(self):
        self.prompts = []

    def completion(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return '{"action_type":"wait","target_id":null,"location_id":null,"object_id":null,"content":"","reason":"先观察局势"}'


class SlowFakeModel(FakeModel):
    def completion(self, prompt, **kwargs):
        time.sleep(0.08)
        return super().completion(prompt, **kwargs)


class InvalidTalkModel(FakeModel):
    def completion(self, prompt, **kwargs):
        return '{"action_type":"talk","target_id":"并不存在的人","content":"在吗？","reason":"想交谈"}'


class LLMPlannerTests(unittest.TestCase):
    def test_ungrounded_llm_action_falls_back_before_world_resolution(self):
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("llm-grounding-test")
        planner = LLMIntentPlanner(InvalidTalkModel())
        progress = []
        intents = planner.plan(state, loaded.scenario, progress_callback=progress.append)
        self.assertEqual(len(intents), 6)
        self.assertTrue(all(intent.target_id != "并不存在的人" for intent in intents))
        self.assertTrue(all(
            intent.metadata.get("planner_source") == "heuristic_fallback"
            for intent in intents
        ))
        self.assertTrue(all(item["source"] == "heuristic_fallback" for item in progress))

    def test_six_character_requests_run_in_parallel_and_report_progress(self):
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("llm-parallel-test")
        planner = LLMIntentPlanner(SlowFakeModel(), max_workers=6)
        progress = []
        started = time.monotonic()
        intents = planner.plan(state, loaded.scenario, progress_callback=progress.append)
        elapsed = time.monotonic() - started
        self.assertEqual(len(intents), 6)
        self.assertLess(elapsed, 0.35)
        self.assertEqual(len(progress), 6)
        self.assertEqual(progress[-1]["completed"], 6)
        self.assertTrue(all(item["source"] == "llm" for item in progress))

    def test_each_character_prompt_contains_only_their_private_beliefs(self):
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("llm-test")
        fake_model = FakeModel()
        planner = LLMIntentPlanner(fake_model)
        intents = planner.plan(state, loaded.scenario)
        self.assertEqual(len(intents), 6)
        prompts = {agent_id: prompt for agent_id, prompt in zip(sorted(state.agents), fake_model.prompts)}
        self.assertIn("雁归北阙", prompts["刘辩"])
        self.assertNotIn("雁归北阙", prompts["傅融"])
        self.assertNotIn("里八华细作以迟发毒针", "\n".join(fake_model.prompts))
        killer_prompt_count = sum("你是本局隐藏凶手" in prompt for prompt in fake_model.prompts)
        self.assertEqual(killer_prompt_count, 1)

    def test_all_resolved_character_actions_are_visible_to_the_player(self):
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("visibility-test", seed=2)
        result = RoundEngine(seed=1).resolve_round(state, [
            ActionIntent("广陵王", ActionType.MOVE, location_id="stairs"),
            ActionIntent("傅融", ActionType.INVESTIGATE, location_id="study"),
        ])
        self.assertTrue(all(event.public for event in result.events))

    def test_json_inside_code_fence_is_parsed(self):
        response = '```json\n{"action_type":"wait","reason":"观察"}\n```'
        intent = LLMIntentPlanner._parse_intent("左慈", response)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action_type, ActionType.WAIT)

    def test_llm_plan_is_sanitized_and_attached_to_intent(self):
        response = '''{
          "action_type":"wait",
          "reason":"继续观察",
          "plan":{
            "objective":"确认谁接触过死者",
            "horizon_rounds":9,
            "steps":["核对证词","寻找物证","决定是否公开怀疑","多余步骤"],
            "contingencies":["若证词冲突则对质"],
            "suspects":[{"agent_id":"傅融","confidence":1.8,"basis":"账目异常"}],
            "public_posture":"保持克制",
            "revision_reason":"上一轮没有得到答案"
          }
        }'''
        intent = LLMIntentPlanner._parse_intent("广陵王", response)
        plan = intent.metadata["strategic_plan"]
        self.assertEqual(plan["horizon_rounds"], 3)
        self.assertEqual(len(plan["steps"]), 3)
        self.assertEqual(plan["suspects"][0]["confidence"], 1.0)

    def test_openai_compatible_fallback_selects_provider_key_without_exposing_it(self):
        class FakeCompatible:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        import modules.interactive.llm_planner as planner_module
        original = planner_module.OpenAICompatibleChatModel
        planner_module.OpenAICompatibleChatModel = FakeCompatible
        try:
            model = LLMIntentPlanner._openai_compatible_fallback(
                {"model": "GLM-test", "base_url": "https://example.invalid/v1"},
                {"ZHIPUAI_API_KEY": "secret-value", "OPENAI_API_KEY": "other"},
            )
        finally:
            planner_module.OpenAICompatibleChatModel = original
        self.assertEqual(model.kwargs["api_key"], "secret-value")
        self.assertEqual(model.kwargs["model"], "GLM-test")

    def test_compatible_endpoint_does_not_duplicate_chat_completions_suffix(self):
        from modules.interactive.llm_planner import OpenAICompatibleChatModel

        model = object.__new__(OpenAICompatibleChatModel)
        model.base_url = "https://example.invalid/v1/chat/completions"
        model.model = "test-model"
        model.api_key = "secret"
        model.client = None

        import requests
        original_post = requests.post
        captured = {}

        class Response:
            ok = True
            status_code = 200

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "ok"}}]}

        def fake_post(url, **kwargs):
            captured["url"] = url
            return Response()

        requests.post = fake_post
        try:
            self.assertEqual(model.completion("prompt"), "ok")
        finally:
            requests.post = original_post
        self.assertEqual(captured["url"], "https://example.invalid/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
