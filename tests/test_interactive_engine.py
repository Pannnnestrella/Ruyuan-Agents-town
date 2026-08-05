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
    HeuristicIntentPlanner,
    LifeState,
    LLMIntentPlanner,
    RoundEngine,
    ScenarioLoader,
    TriggerResolver,
    game_state_from_dict,
)
from modules.interactive.models import AgentState, Belief


ROOT = Path(__file__).resolve().parents[1]


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        self.state = self.loaded.create_game_state("test-game")

    def test_scenario_loads_four_timed_rounds_with_growing_action_budgets(self):
        self.assertEqual(len(self.state.agents), 6)
        self.assertEqual(self.state.max_rounds, 4)
        self.assertEqual(self.state.actions_per_round, 3)
        self.assertEqual(
            [self.state.duration_for_round(number) for number in range(1, 5)],
            [360, 480, 600, 900],
        )
        self.assertEqual(
            [self.state.action_limit_for_round(number) for number in range(1, 5)],
            [3, 4, 5, 6],
        )
        self.assertIn("lobby", self.state.locations)
        self.assertEqual(
            set(self.loaded.scenario["llm_scope"]["participant_ids"]),
            {"广陵王", "傅融", "刘辩", "孙策", "左慈", "袁基"},
        )
        self.assertIn("courier_body", self.state.objects)
        self.assertEqual(self.loaded.scenario["behavior_guidelines"]["version"], 2)
        self.assertIn("下毒", self.loaded.scenario["behavior_guidelines"]["text"])
        action_values = {action.value for action in ActionType}
        self.assertTrue({"hide", "escape", "attack"}.isdisjoint(action_values))
        for agent in self.state.agents.values():
            self.assertEqual(agent.state_schema_version, 2)
            self.assertIn("current_area", agent.location_state)
            self.assertIn("held_items", agent.inventory_state)
            self.assertIn("testimonies", agent.information_state)
            self.assertIn("suspect_profiles", agent.case_model)
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

    def test_heuristic_dialogue_uses_character_voice_without_fixed_wrapper(self):
        planner = HeuristicIntentPlanner(seed=3)
        for index, agent in enumerate(self.state.agents.values()):
            agent.location_id = "lobby"
            agent.beliefs.append(Belief(
                belief_id=f"dialogue-style-{index}",
                claim=f"第{index + 1}封驿报的落款时辰与登记簿不符",
                source=f"dialogue-style-source-{index}",
                confidence=0.8,
            ))
        for item in self.state.objects.values():
            if item.location_id == "lobby":
                item.discovered_by = list(self.state.agents)
        intents = planner.plan(
            self.state,
            self.loaded.scenario,
            actor_ids=["广陵王", "傅融", "刘辩", "孙策", "左慈", "袁基"],
        )
        dialogue = [
            intent.content for intent in intents
            if intent.action_type == ActionType.TALK
        ]

        self.assertGreaterEqual(len(dialogue), 3)
        self.assertEqual(len(dialogue), len(set(dialogue)))
        self.assertTrue(all(
            "我愿意分享一条尚未与你核对的信息" not in line
            and "你有能相互印证的线索吗" not in line
            for line in dialogue
        ))

    def test_legacy_health_states_are_migrated_without_numeric_health(self):
        raw = self.state.to_dict(include_private=True)
        raw["agents"]["刘辩"]["life_state"] = "severely_injured"
        raw["agents"]["刘辩"]["health"] = 30

        restored = game_state_from_dict(raw)

        self.assertEqual(restored.agents["刘辩"].life_state, LifeState.INJURED)
        self.assertNotIn("health", restored.agents["刘辩"].to_dict())

    def test_shared_pregame_events_are_identical_in_every_participant_timeline(self):
        timelines = self.state.flags["character_timelines"]
        objective = self.state.flags["objective_timeline"]
        for event in objective:
            if event["private"]:
                continue
            for participant_id in event["participants"]:
                matching = [
                    item for item in timelines[participant_id]
                    if item["id"] == event["id"]
                ]
                self.assertEqual(len(matching), 1, (event["id"], participant_id))
                self.assertEqual(matching[0]["text"], event["text"])
        killer_id = self.state.flags["killer_id"]
        private_entries = [
            (agent_id, entry)
            for agent_id, entries in timelines.items()
            for entry in entries if entry["private"]
        ]
        self.assertEqual(len(private_entries), 1)
        self.assertEqual(private_entries[0][0], killer_id)
        self.assertIn("只有你知道", private_entries[0][1]["text"])
        self.assertTrue(all(timelines[agent_id] for agent_id in self.state.agents))

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
        public_text = str(self.state.public_view())
        self.assertNotIn("identity_state", public_text)
        self.assertNotIn("case_model", public_text)
        self.assertTrue(all(
            "history" not in item for item in public_objects.values()
        ))
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
        self.assertEqual(item.history[-1].action, "world_remove")
        self.assertEqual(item.history[-1].event_id, events[0].event_id)

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

    def test_versioned_state_conversations_and_item_history_round_trip(self):
        self.state.phase = GamePhase.READY
        for agent_id in ("广陵王", "傅融", "左慈"):
            self.state.agents[agent_id].location_id = "lobby"
        result = self.engine.resolve_free_action(
            self.state,
            ActionIntent(
                "广陵王",
                ActionType.TALK,
                target_id="傅融",
                content="请核对你记得的时辰。",
            ),
        )

        restored = game_state_from_dict(
            self.state.to_dict(include_private=True)
        )

        self.assertEqual(restored.agents["广陵王"].state_schema_version, 2)
        self.assertIn("testimonies", restored.agents["傅融"].information_state)
        self.assertEqual(restored.conversations[-1].event_id, result.events[0].event_id)
        self.assertEqual(
            set(restored.conversations[-1].witnesses),
            {"广陵王", "傅融", "左慈"},
        )
        self.assertTrue(all(
            item.history and hasattr(item.history[0], "action")
            for item in restored.objects.values()
        ))

    def test_equivalent_intelligence_is_not_echoed_back_but_can_reach_a_new_person(self):
        self.state.phase = GamePhase.READY
        for agent_id in ("广陵王", "傅融", "左慈"):
            self.state.agents[agent_id].location_id = "lobby"
        original = self.state.agents["广陵王"].beliefs[0]
        first = self.engine.resolve_free_action(self.state, ActionIntent(
            "广陵王", ActionType.TALK, target_id="傅融", content="我说一条亲历。",
            metadata={"share_belief_id": original.belief_id},
        ))
        self.assertEqual(len(first.events), 1)
        # The engine validates exchange lineage; the service normally writes the
        # listener memory, so emulate that one received claim for this unit test.
        received = Belief(
            belief_id="received-test", claim=original.claim,
            source=first.events[0].event_id, confidence=1.0,
            shared_with=["广陵王"],
        )
        self.state.agents["傅融"].beliefs.append(received)
        echoed = self.engine.resolve_free_action(self.state, ActionIntent(
            "傅融", ActionType.TALK, target_id="广陵王", content="再说回给你。",
            metadata={"share_belief_id": received.belief_id},
        ))
        self.assertFalse(echoed.events)
        self.assertTrue(any(
            phrase in echoed.rejected_intents[0]["reason"]
            for phrase in ("already knows", "already shared")
        ))
        reshared = self.engine.resolve_free_action(self.state, ActionIntent(
            "傅融", ActionType.TALK, target_id="左慈", content="这是一条二手消息。",
            metadata={"share_belief_id": received.belief_id},
        ))
        self.assertEqual(len(reshared.events), 1)

    def test_poison_is_private_and_takes_effect_next_round(self):
        self.state.agents["孙策"].location_id = "lobby"
        self.state.agents["刘辩"].location_id = "lobby"
        self.state.flags["killer_id"] = "孙策"
        self.engine.random.random = lambda: 0.0
        result = self.engine.resolve_round(
            self.state,
            [
                ActionIntent(
                    "孙策",
                    ActionType.POISON,
                    target_id="刘辩",
                )
            ],
        )
        self.assertEqual(self.state.agents["刘辩"].life_state, LifeState.ALIVE)
        poison_action = next(
            event for event in result.events if event.event_type == "poison_queued"
        )
        self.assertFalse(poison_action.public)
        self.assertEqual(poison_action.witnesses, ["孙策"])
        self.assertEqual(poison_action.payload["ability_id"], "killer_poison")

        next_round = self.engine.resolve_action_phase(self.state, [])
        self.assertEqual(self.state.agents["刘辩"].life_state, LifeState.INJURED)
        poison_effect = next(
            event for event in next_round.events if event.event_type == "poison_effect"
        )
        self.assertFalse(poison_effect.public)
        self.assertNotIn("孙策", poison_effect.summary)
        self.assertNotIn("poisoner_id", poison_effect.payload)

    def test_search_records_room_traces_and_reports_progress(self):
        actor = self.state.agents["广陵王"]
        actor.location_id = "front_gate"
        for item in self.state.objects.values():
            if item.location_id == "front_gate" and actor.agent_id not in item.discovered_by:
                item.discovered_by.append(actor.agent_id)
        result = self.engine.resolve_round(
            self.state,
            [ActionIntent("广陵王", ActionType.INVESTIGATE, location_id="front_gate")],
        )
        event = result.events[0]
        self.assertEqual(event.event_type, "investigation_empty")
        self.assertTrue(event.payload["disturbance_trace"])
        self.assertFalse(event.payload["evidence_remaining"])
        history = self.state.flags["location_search_history"]["front_gate"]
        self.assertEqual(history[-1]["agent_id"], "广陵王")

    def test_poison_is_limited_once_per_round_and_death_drops_inventory(self):
        self.state.flags["killer_id"] = "孙策"
        attacker = self.state.agents["孙策"]
        target = self.state.agents["刘辩"]
        attacker.location_id = target.location_id = "lobby"
        target.life_state = LifeState.INJURED
        carried = target.inventory[0]
        self.engine.random.random = lambda: 0.0
        first = self.engine.resolve_action_phase(
            self.state,
            [ActionIntent("孙策", ActionType.POISON, target_id="刘辩")],
        )
        self.assertEqual(target.life_state, LifeState.INJURED)
        self.assertTrue(any(event.event_type == "poison_queued" for event in first.events))
        second = self.engine.resolve_action_phase(
            self.state,
            [ActionIntent("孙策", ActionType.POISON, target_id="广陵王")],
        )
        self.assertIn("at most one poisoning per round", second.rejected_intents[0]["reason"])
        self.engine.resolve_action_phase(self.state, [])
        next_round = self.engine.resolve_action_phase(self.state, [])
        self.assertEqual(target.life_state, LifeState.DEAD)
        self.assertNotIn(carried, target.inventory)
        self.assertEqual(self.state.objects[carried].location_id, "lobby")
        self.assertTrue(any(
            entry.action == "drop" for entry in self.state.objects[carried].history
        ))
        self.assertTrue(any(
            event.event_type == "poison_effect" for event in next_round.events
        ))

    def test_authored_events_can_injure_or_accidentally_drop_a_carried_item(self):
        director = EventDirector(self.loaded.scenario["event_cards"], seed=4)
        director.apply(self.state, "pressure-fever")
        self.assertEqual(self.state.agents["刘辩"].life_state, LifeState.INJURED)

        drop_state = self.loaded.create_game_state("drop-event-test", seed=2)
        before_inventory = sum(len(agent.inventory) for agent in drop_state.agents.values())
        drop_director = EventDirector(self.loaded.scenario["event_cards"], seed=4)
        events = drop_director.apply(drop_state, "pressure-collision-drop")
        self.assertEqual(
            sum(len(agent.inventory) for agent in drop_state.agents.values()),
            before_inventory - 1,
        )
        self.assertTrue(any(event.event_type == "object_dropped" for event in events))

        reveal_state = self.loaded.create_game_state("reveal-event-test", seed=2)
        hidden_before = sum(
            1 for item in reveal_state.objects.values()
            if item.location_id and item.hidden and not item.discovered_by
        )
        reveal_director = EventDirector(self.loaded.scenario["event_cards"], seed=4)
        reveal_events = reveal_director.apply(reveal_state, "information-loose-floorboard")
        hidden_after = sum(
            1 for item in reveal_state.objects.values()
            if item.location_id and item.hidden and not item.discovered_by
        )
        self.assertEqual(hidden_after, hidden_before - 1)
        self.assertTrue(any(event.event_type == "object_revealed" for event in reveal_events))

        injury_state = self.loaded.create_game_state("injury-event-test", seed=2)
        injury_director = EventDirector(self.loaded.scenario["event_cards"], seed=4)
        injury_events = injury_director.apply(injury_state, "pressure-falling-rafter")
        self.assertEqual(
            sum(agent.life_state == LifeState.INJURED for agent in injury_state.agents.values()),
            1,
        )
        self.assertTrue(any(event.event_type == "life_state_changed" for event in injury_events))


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
        self.assertTrue(received.claim.startswith("主持人公开公告："))
        self.assertEqual(set(notice.seen_by), set(self.session.state.agents))
        self.assertEqual(set(received.shared_with), set(self.session.state.agents) - {"广陵王"})

    def test_agent_notice_read_by_everyone_is_not_offered_as_new_information(self):
        for agent in self.session.state.agents.values():
            agent.location_id = "lobby"
        notice = self.session.post_notice(
            "西厢客房已经由众人共同检查。",
            display_author="孙策",
            authority="agent",
            publisher="孙策",
            location_id="lobby",
        )
        self.assertEqual(set(notice.seen_by), set(self.session.state.agents))
        for agent_id, agent in self.session.state.agents.items():
            belief = next(
                item for item in agent.beliefs
                if item.source == notice.notice_id
            )
            self.assertEqual(
                set(belief.shared_with),
                set(self.session.state.agents) - {agent_id},
            )

        intents = self.session.planner.plan(
            self.session.state,
            self.loaded.scenario,
            actor_ids=list(self.session.state.agents),
        )
        shared_ids = {
            intent.metadata.get("share_belief_id") for intent in intents
        }
        self.assertTrue(all(
            f"belief-{agent_id}-{notice.notice_id}" not in shared_ids
            for agent_id in self.session.state.agents
        ))

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

    def test_round_ends_with_bounded_structured_lobby_discussion(self):
        self.session.select_event_card(
            self.session.empty_event_option()["card_id"]
        )
        result = self.session.advance_round()
        discussion = [
            event for event in result.events
            if event.event_type == "conversation"
            and event.payload.get("round_discussion")
        ]

        self.assertGreaterEqual(len(discussion), 6)
        self.assertLessEqual(len(discussion), 12)
        self.assertEqual(
            self.session.state.flags["round_discussion_turns"],
            len(discussion),
        )
        self.assertTrue(all(
            event.location_id == "lobby"
            and event.payload["discussion_wave"] in {1, 2}
            and event.payload["planner_source"]
            for event in discussion
        ))
        self.assertTrue(all(
            agent.location_id == "lobby"
            for agent in self.session.state.agents.values()
            if agent.can_act
        ))
        self.assertTrue(any(
            record.event_id == discussion[0].event_id
            and record.speaker_id
            and record.listener_id
            and record.location_id == "lobby"
            for record in self.session.state.conversations
        ))

    def test_round_discussion_respects_global_one_hundred_turn_limit(self):
        self.session.state.round_number = 1
        self.session.state.phase = GamePhase.ROUND_COMPLETE
        self.session.state.flags["round_discussion_turns"] = 98
        self.session.state.flags["completed_round_discussions"] = []

        events = self.session._prepare_round_discussion()
        discussion = [
            event for event in events
            if event.event_type == "conversation"
        ]

        self.assertEqual(len(discussion), 2)
        self.assertEqual(
            self.session.state.flags["round_discussion_turns"],
            100,
        )

    def test_ai_free_movement_is_resolved_before_one_major_action(self):
        class FreeMoveThenMajorPlanner:
            def __init__(self):
                self.moved = set()

            def plan(
                inner_self, state, scenario, progress_callback=None,
                actor_ids=None, force_major=False,
            ):
                intents = []
                for agent_id in actor_ids or sorted(state.agents):
                    agent = state.agents[agent_id]
                    if not force_major and agent_id not in inner_self.moved:
                        inner_self.moved.add(agent_id)
                        destination = state.locations[agent.location_id]["connections"][0]
                        intents.append(ActionIntent(
                            agent_id, ActionType.MOVE, location_id=destination,
                        ))
                    else:
                        intents.append(ActionIntent(
                            agent_id, ActionType.INVESTIGATE,
                            location_id=agent.location_id,
                        ))
                return intents

        self.session.planner = FreeMoveThenMajorPlanner()
        self.session.select_event_card(self.session.empty_event_option()["card_id"])
        result = self.session._advance_action_phase(player_intent=None)
        free_moves = [event for event in result.events if event.event_type == "move"]
        major_events = [event for event in result.events if event.action_step == 1]
        self.assertEqual(len(free_moves), 6)
        self.assertTrue(all(event.payload["free_action"] for event in free_moves))
        self.assertEqual(self.session.state.action_step, 1)
        self.assertEqual({event.actors[0] for event in major_events}, set(self.session.state.agents))

    def test_crowded_lobby_conversation_does_not_starve_exploration(self):
        agent_ids = list(self.session.state.agents)
        for index, agent in enumerate(self.session.state.agents.values()):
            agent.location_id = "lobby"
            agent.beliefs.append(Belief(
                belief_id=f"crowded-private-{index}",
                claim=f"第{index + 1}份私人记录仍需找人核对",
                source=f"private-observation-{index}",
                confidence=0.8,
            ))
        for item in self.session.state.objects.values():
            if item.location_id == "lobby":
                item.discovered_by = list(agent_ids)

        self.session.select_event_card(
            self.session.empty_event_option()["card_id"]
        )
        result = self.session._advance_action_phase(player_intent=None)
        free_moves = [
            event for event in result.events
            if event.event_type == "move"
            and event.payload.get("free_action")
        ]
        major_events = [
            event for event in result.events
            if event.action_step == 1
            and event.event_type not in {"move", "conversation"}
        ]

        self.assertEqual(
            {event.actors[0] for event in free_moves},
            set(agent_ids),
        )
        self.assertTrue(any(
            event.event_type in {"discovery", "investigation_empty"}
            for event in major_events
        ))
        self.assertFalse(all(
            event.event_type == "wait" for event in major_events
        ))
        self.assertGreater(
            len({agent.location_id for agent in self.session.state.agents.values()}),
            1,
        )

    def test_character_plan_survives_and_accumulates_outcomes_across_rounds(self):
        initial_objective = self.session.state.agents["广陵王"].strategic_plan["objective"]
        for expected_round in (1, 2):
            quiet = self.session.empty_event_option()
            self.session.select_event_card(quiet["card_id"])
            self.session.advance_round()
            agent = self.session.state.agents["广陵王"]
            self.assertEqual(agent.strategic_plan["updated_round"], expected_round)
            expected_actions = sum(
                self.session.state.action_limit_for_round(round_number)
                for round_number in range(1, expected_round + 1)
            )
            self.assertEqual(len(agent.plan_history), expected_actions)
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

    def test_four_rounds_offer_twelve_nonrepeating_cards_and_quiet_is_available(self):
        offered = []
        for _ in range(4):
            cards = self.session.card_suggestions()
            offered.extend(card["card_id"] for card in cards)
            quiet = self.session.empty_event_option()
            self.assertEqual(quiet["category"], "quiet")
            self.session.select_event_card(quiet["card_id"])
            self.session.advance_round()
        self.assertEqual(len(offered), 12)
        self.assertEqual(len(set(offered)), 12)

    def test_public_intel_reaches_every_character_immediately(self):
        intel = self.session.intel_suggestions()[0]
        published, event = self.session.publish_public_intel(intel["id"])
        self.assertEqual(published["id"], intel["id"])
        for agent in self.session.state.agents.values():
            received = next(belief for belief in agent.beliefs if belief.source == event.event_id)
            self.assertEqual(
                set(received.shared_with),
                set(self.session.state.agents) - {agent.agent_id},
            )
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
        self.assertIn("据广陵王所说", received.claim)

    def test_four_round_game_writes_evidence_based_recap(self):
        self.session.post_notice("所有住客若发现密信，须先在大堂登记。")
        for _ in range(4):
            cards = self.session.card_suggestions()
            self.assertEqual(len(cards), 3)
            self.session.select_event_card(cards[0]["card_id"])
            self.session.advance_round()
        self.assertEqual(self.session.state.phase, GamePhase.FINISHED)
        recap = self.session.build_recap()
        self.assertEqual(recap["rounds_completed"], 4)
        self.assertEqual(recap["total_major_action_limit"], 18)
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

    def test_llm_scope_rejects_unrelated_character_state_and_lore(self):
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("llm-scope-test")
        state.agents["吕布"] = AgentState(
            agent_id="吕布",
            display_name="吕布",
            location_id="lobby",
            public_role="不属于停云客栈的旧版角色",
        )
        fake_model = FakeModel()
        planner = LLMIntentPlanner(fake_model)

        intents = planner.plan(state, loaded.scenario)

        self.assertEqual({intent.actor_id for intent in intents}, {
            "广陵王", "傅融", "刘辩", "孙策", "左慈", "袁基",
        })
        combined = "\n".join(fake_model.prompts)
        for unrelated_name in ("吕布", "祢衡", "周瑜", "太史慈", "史子眇"):
            self.assertNotIn(unrelated_name, combined)

    def test_resolved_character_actions_are_scoped_to_witnesses(self):
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("visibility-test", seed=2)
        result = RoundEngine(seed=1).resolve_round(state, [
            ActionIntent("广陵王", ActionType.MOVE, location_id="stairs"),
            ActionIntent("傅融", ActionType.INVESTIGATE, location_id="study"),
        ])
        self.assertTrue(all(not event.public for event in result.events))
        self.assertTrue(all(
            set(event.actors).issubset(set(event.witnesses))
            for event in result.events
        ))

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

    def test_deepseek_candidate_uses_environment_key_without_exposing_it(self):
        class FakeCompatible:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        import modules.interactive.llm_planner as planner_module
        original = planner_module.OpenAICompatibleChatModel
        planner_module.OpenAICompatibleChatModel = FakeCompatible
        try:
            planner = LLMIntentPlanner.from_deepseek(
                "secret-deepseek-value",
                model_name="deepseek-v4-flash",
            )
        finally:
            planner_module.OpenAICompatibleChatModel = original
        self.assertEqual(planner.model.kwargs["api_key"], "secret-deepseek-value")
        self.assertEqual(planner.model.kwargs["base_url"], "https://api.deepseek.com")
        self.assertEqual(planner.provider_name, "deepseek:deepseek-v4-flash")
        self.assertNotIn("secret-deepseek-value", planner.provider_name)

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

    def test_deepseek_compatible_request_disables_thinking_for_json_actions(self):
        from modules.interactive.llm_planner import OpenAICompatibleChatModel

        model = object.__new__(OpenAICompatibleChatModel)
        model.base_url = "https://api.deepseek.com"
        model.model = "deepseek-v4-flash"
        model.api_key = "secret"
        model.client = None
        model.timeout_seconds = 20.0

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
            captured["json"] = kwargs["json"]
            return Response()

        requests.post = fake_post
        try:
            self.assertEqual(model.completion("prompt"), "ok")
        finally:
            requests.post = original_post
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["json"]["thinking"], {"type": "disabled"})


if __name__ == "__main__":
    unittest.main()
