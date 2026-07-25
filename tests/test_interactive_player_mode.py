import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from modules.interactive import ActionIntent, ActionType, GamePhase, GameService, LifeState


class PlayerModeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = GameService(".", results_root=self.temp_dir.name)
        self.session = self.service.create_game(
            "stormbound_inn",
            game_id="player-mode-test",
            seed=0,
            player_agent_id="广陵王",
        )
        self.token = self.session.issued_player_token

    def tearDown(self):
        self.temp_dir.cleanup()

    def select_quiet(self):
        quiet = self.session.empty_event_option()
        self.session.select_event_card(quiet["card_id"])

    def test_first_person_view_does_not_leak_other_private_state_or_killer(self):
        view = self.session.player_state(self.token)
        text = json.dumps(view, ensure_ascii=False)
        killer_id = self.session.state.flags["killer_id"]
        self.assertNotEqual(killer_id, "广陵王")
        self.assertNotIn(killer_id + "杀死了陆成", text)
        self.assertNotIn("killer_id", text)
        expected_visible = set(self.session.state.occupants("lobby"))
        self.assertEqual(set(view["visible_agents"]), expected_visible)
        for public_agent in view["visible_agents"].values():
            self.assertNotIn("beliefs", public_agent)
            self.assertNotIn("inventory", public_agent)
        self.assertIn("beliefs", view["self"])
        self.assertNotIn("strategic_plan", view["self"])

    def test_final_questions_are_role_specific_and_do_not_expose_answer_key(self):
        self.session.state.phase = GamePhase.VOTING
        view = self.session.player_state(self.token)
        self.assertEqual(len(view["final_questions"]), 3)
        self.assertTrue(all(question["options"] for question in view["final_questions"]))
        text = json.dumps(view, ensure_ascii=False)
        self.assertNotIn("answer_key", text)
        self.assertNotIn("correct_answer", text)

    def test_player_must_answer_every_final_question(self):
        self.session.state.phase = GamePhase.VOTING
        killer_id = self.session.state.flags["killer_id"]
        with self.assertRaisesRegex(ValueError, "回答全部"):
            self.session.submit_player_vote(
                self.token,
                killer_id,
                "测试未完成答卷",
                [],
            )

    def test_player_receives_rich_dossier_opening_and_dynamic_guide(self):
        view = self.session.player_state(self.token)
        self.assertEqual(len(view["background"]["story"]), 3)
        self.assertGreaterEqual(len(view["background"]["background_memories"]), 2)
        self.assertIn("鸢报有假", view["opening_dispatch"]["dead_note"])
        self.assertGreaterEqual(len(view["player_guide"]["principles"]), 6)
        self.assertEqual(view["story_guide"]["title"], "第 1 轮 · 风雨未歇")
        self.assertIn("亲自选择", view["story_guide"]["objective"])
        self.assertGreaterEqual(len(view["background"]["timeline"]), 6)
        self.assertEqual(len(view["host_options"]["cards"]), 3)
        self.assertTrue(view["host_options"]["quiet"])

        self.select_quiet()
        ready = self.session.player_state(self.token)
        self.assertIn("第 1 轮 · 主要行动 0/3", ready["story_guide"]["title"])
        self.assertEqual(
            ready["story_guide"]["location_name"],
            self.session.state.locations["lobby"]["name"],
        )

    def test_bulletin_update_marks_unread_without_leaking_remote_content(self):
        self.session.state.agents["广陵王"].location_id = "room_east"
        notice = self.session.post_notice(
            "只有回大堂才能读到的测试公告。",
            authority="agent",
            publisher="傅融",
            display_author="傅融",
        )
        view = self.session.player_state(self.token)
        self.assertTrue(view["bulletin"]["has_unread"])
        self.assertNotIn(notice.notice_id, {item["notice_id"] for item in view["notices"]})
        marker = [event for event in view["events"] if event["event_type"] == "bulletin_updated"]
        self.assertTrue(marker)
        self.assertNotIn("测试公告", marker[-1]["summary"])

    def test_poison_and_treatment_are_character_specific(self):
        actions = self.session.available_player_actions("广陵王")
        self.assertIn("treat", actions["types"])
        self.assertNotIn("poison", actions["types"])
        self.assertEqual(
            next(item for item in actions["special_actions"] if item["action_type"] == "treat")["label"],
            "楼主调度",
        )
        self.select_quiet()
        with self.assertRaisesRegex(ValueError, "没有执行"):
            self.session.build_player_intent(self.token, {
                "action_type": "poison",
                "target_id": "傅融",
            })

        self.session.state.flags["killer_id"] = "刘辩"
        killer_actions = self.session.available_player_actions("刘辩")
        self.assertIn("poison", killer_actions["types"])
        self.assertEqual(killer_actions["special_actions"][0]["ability_id"], "killer_poison")

    def test_specialized_investigation_does_not_replace_basic_search(self):
        left_session = self.service.create_game(
            "stormbound_inn",
            game_id="left-skill-test",
            seed=0,
            player_agent_id="左慈",
        )
        actions = left_session.available_player_actions("左慈")
        self.assertIn("investigate", actions["types"])
        skill = next(item for item in actions["special_actions"] if item["ability_id"] == "toxin_diagnosis")
        self.assertEqual(skill["action_type"], "investigate")
        quiet = left_session.empty_event_option()
        left_session.select_event_card(quiet["card_id"])
        location_id = left_session.state.agents["左慈"].location_id
        basic = left_session.build_player_intent(left_session.issued_player_token, {
            "action_type": "investigate",
            "location_id": location_id,
        })
        skilled = left_session.build_player_intent(left_session.issued_player_token, {
            "action_type": "investigate",
            "location_id": location_id,
            "ability_id": "toxin_diagnosis",
        })
        self.assertNotIn("ability_id", basic.metadata)
        self.assertEqual(skilled.metadata["ability_id"], "toxin_diagnosis")

    def test_memory_exchange_names_the_shared_information_and_can_be_reshared(self):
        self.session.state.agents["傅融"].location_id = "lobby"
        self.session.state.agents["左慈"].location_id = "lobby"
        self.session.state.agents["袁基"].location_id = "upper_hall"
        self.select_quiet()
        memory = self.session.state.agents["广陵王"].beliefs[0]
        result = self.session.advance_player_action(self.token, {
            "action_type": "talk",
            "target_id": "傅融",
            "share_belief_id": memory.belief_id,
            "content": "",
        })
        outgoing = result.events[0]
        self.assertIn(memory.claim, outgoing.payload["content"])
        received = next(
            belief for belief in self.session.state.agents["傅融"].beliefs
            if belief.source == outgoing.event_id
        )
        self.assertEqual(received.truth_id, memory.truth_id)
        self.assertEqual(set(received.shared_with), {"广陵王", "左慈"})
        overheard = next(
            belief for belief in self.session.state.agents["左慈"].beliefs
            if belief.source == outgoing.event_id
        )
        self.assertEqual(overheard.speaker_id, "广陵王")
        self.assertEqual(overheard.learned_location, "lobby")
        self.assertEqual(set(overheard.witnesses), set(outgoing.witnesses))
        self.assertFalse(any(
            belief.source == outgoing.event_id
            for belief in self.session.state.agents["袁基"].beliefs
        ))
        record = next(
            item for item in self.session.state.conversations
            if item.event_id == outgoing.event_id
        )
        self.assertEqual(record.speaker_id, "广陵王")
        self.assertEqual(record.content, outgoing.payload["content"])
        self.assertEqual(record.location_id, "lobby")

    def test_player_can_post_persistent_information_at_lobby_board(self):
        notice = self.session.post_player_notice(self.token, "我在尸体袖口发现了深青丝线，请共同核对。")
        self.assertEqual(notice.publisher, "广陵王")
        self.assertEqual(notice.location_id, "lobby")
        self.assertIn("广陵王", notice.seen_by)
        self.session.state.agents["傅融"].location_id = "lobby"
        self.session._deliver_unseen_notices()
        self.assertIn("傅融", notice.seen_by)
        self.assertTrue(any(
            belief.source == notice.notice_id
            for belief in self.session.state.agents["傅融"].beliefs
        ))

    def test_move_and_talk_are_free_but_investigation_uses_major_action(self):
        self.session.state.agents["傅融"].location_id = "lobby"
        self.select_quiet()

        talk = self.session.advance_player_action(self.token, {
            "action_type": "talk",
            "target_id": "傅融",
            "content": "你最后一次见到陆成是什么时候？",
        })
        self.assertEqual(talk.action_step, 0)
        self.assertEqual(self.session.state.action_step, 0)
        self.assertTrue(talk.events[0].payload["free_action"])
        self.assertEqual(len(talk.events), 2)
        self.assertTrue(talk.events[1].payload["is_reply"])
        self.assertEqual(talk.events[1].payload["speaker_id"], "傅融")

        destination = self.session.available_player_actions("广陵王")["moves"][0]["id"]
        move = self.session.advance_player_action(self.token, {
            "action_type": "move",
            "location_id": destination,
        })
        self.assertEqual(move.action_step, 0)
        self.assertEqual(self.session.state.action_step, 0)
        self.assertEqual(len(move.events), 1)
        self.assertFalse(any(
            belief.source == move.events[0].event_id
            for agent in self.session.state.agents.values()
            for belief in agent.beliefs
        ))

        investigate = self.session.advance_player_action(self.token, {
            "action_type": "investigate",
            "location_id": destination,
        })
        self.assertEqual(investigate.action_step, 1)
        self.assertEqual(self.session.state.action_step, 1)

    def test_player_can_choose_the_host_event_and_end_the_round(self):
        intel = self.session.intel_suggestions()[0]
        card = self.session.card_suggestions()[0]
        hosted = self.session.choose_player_host_event(
            self.token, card["card_id"], intel_id=intel["id"]
        )
        self.assertTrue(hosted["card"])
        self.assertIsNotNone(hosted["intel"])
        self.assertEqual(self.session.state.phase, GamePhase.READY)
        self.assertTrue(self.session.state.active_event_card)

        self.session.advance_player_action(self.token, {
            "action_type": "investigate",
            "location_id": "lobby",
        })
        result = self.session.end_player_round(self.token)
        self.assertEqual(result.round_number, 1)
        self.assertEqual(self.session.state.round_number, 1)
        self.assertEqual(self.session.state.action_step, 0)
        self.assertEqual(self.session.state.phase, GamePhase.INTERVENTION)
        player_waits = [
            event for event in result.events
            if event.event_type == "wait" and event.actors == ["广陵王"]
        ]
        self.assertEqual(len(player_waits), 2)

    def test_host_choice_never_publishes_or_selects_anything_until_confirmed(self):
        view = self.session.player_state(self.token)
        self.assertIsNone(self.session.state.active_event_card)
        self.assertFalse(self.session.state.public_intel_history)
        quiet = view["host_options"]["quiet"]
        hosted = self.session.choose_player_host_event(self.token, quiet["card_id"])
        self.assertIsNone(hosted["intel"])
        self.assertEqual(hosted["card"]["category"], "quiet")
        self.assertFalse(self.session.state.public_intel_history)

    def test_player_sees_departure_from_same_room_but_not_remote_actions(self):
        self.session.state.agents["傅融"].location_id = "lobby"
        self.select_quiet()
        destination = self.session.state.locations["lobby"]["connections"][0]
        self.session.engine.resolve_free_action(
            self.session.state,
            ActionIntent("傅融", ActionType.MOVE, location_id=destination),
        )
        view = self.session.player_state(self.token)
        self.assertNotIn("傅融", view["visible_agents"])
        self.assertTrue(any(
            event["event_type"] == "move" and event["actors"] == ["傅融"]
            for event in view["events"]
        ))
        self.session.state.agents["傅融"].location_id = "room_east"
        remote_destination = self.session.state.locations["room_east"]["connections"][0]
        remote_event = self.session.engine.resolve_free_action(
            self.session.state,
            ActionIntent("傅融", ActionType.MOVE, location_id=remote_destination),
        )
        self.assertEqual(remote_event.events[0].witnesses.count("广陵王"), 0)

    def test_three_sequential_actions_close_one_round(self):
        self.select_quiet()
        steps = []
        for _ in range(3):
            view = self.session.player_state(self.token)
            result = self.session.advance_player_action(self.token, {
                "action_type": "investigate",
                "location_id": view["self"]["location_id"],
            })
            steps.append(result.action_step)
        self.assertEqual(steps, [1, 2, 3])
        self.assertEqual(self.session.state.round_number, 1)
        self.assertEqual(self.session.state.action_step, 0)
        self.assertEqual(self.session.state.phase, GamePhase.INTERVENTION)
        player_events = [
            event for event in self.session.state.events
            if "广陵王" in event.actors and event.round_number == 1
        ]
        self.assertEqual([event.action_step for event in player_events], [1, 2, 3])

    def test_secret_discovery_is_scoped_without_official_process_score(self):
        self.session.state.agents["广陵王"].location_id = "room_east"
        self.session.state.agents["刘辩"].location_id = "upper_hall"
        self.select_quiet()
        result = self.session.advance_player_action(self.token, {
            "action_type": "investigate",
            "location_id": "room_east",
        })
        discovery = next(
            event for event in result.events
            if event.actors == ["广陵王"] and event.event_type == "discovery"
        )
        self.assertEqual(
            discovery.payload["reveals_secret_id"], "secret-liubian-identity"
        )
        self.assertIn(
            "广陵王",
            self.session.state.secrets["secret-liubian-identity"].exposed_to,
        )
        self.assertIn(
            "secret-liubian-identity",
            self.session.state.agents["广陵王"].discovered_secret_ids,
        )
        self.assertEqual(self.session.state.agents["广陵王"].score, 0)
        view = self.session.player_state(self.token)
        known_ids = {secret["secret_id"] for secret in view["known_secrets"]}
        self.assertIn("secret-liubian-identity", known_ids)

    def test_full_six_round_game_waits_for_player_vote_and_scores_everyone(self):
        for _ in range(6):
            self.select_quiet()
            for _ in range(3):
                view = self.session.player_state(self.token)
                if view["self"]["life_state"] == "dead":
                    self.session.end_player_round(self.token)
                    break
                action = (
                    {
                        "action_type": "investigate",
                        "location_id": view["self"]["location_id"],
                    }
                    if view["available_actions"]["can_investigate"]
                    else {"action_type": "wait"}
                )
                self.session.advance_player_action(self.token, action)
        self.assertEqual(self.session.state.phase, GamePhase.DISCUSSION)
        self.assertTrue(self.session.state.flags["final_discussion_done"])
        self.assertTrue(any(
            event.event_type == "final_discussion"
            for event in self.session.state.events
        ))
        self.assertTrue(all(
            agent.location_id == "lobby"
            for agent in self.session.state.agents.values()
            if agent.life_state != LifeState.DEAD
        ))
        self.session.open_final_vote(self.token)
        self.assertEqual(self.session.state.phase, GamePhase.VOTING)
        killer_id = self.session.state.flags["killer_id"]
        answers = [
            {
                "question_id": question["id"],
                "answer": self.session._correct_answer_for(question["id"]),
            }
            for question in self.session.final_questions_for("广陵王")
        ]
        self.session.submit_player_vote(
            self.token,
            killer_id,
            "我根据自己掌握的线索作出指认。",
            answers,
        )
        self.assertEqual(self.session.state.phase, GamePhase.FINISHED)
        self.assertTrue(self.session.state.flags["scores_finalized"])
        self.assertEqual(len(self.session.state.votes), 6)
        self.assertEqual(len(self.session.scoreboard()), 6)
        self.assertTrue(all(
            len(item["answer_results"]) == 3
            for item in self.session.scoreboard()
        ))
        self.assertEqual(
            len(self.session.state.final_submissions["广陵王"]["answer_results"]),
            3,
        )
        player_submission = self.session.state.final_submissions["广陵王"]
        self.assertEqual(
            player_submission["case_conclusion"]["killer"],
            killer_id,
        )
        self.assertIn("reasoning_chain", player_submission["case_conclusion"])
        self.assertEqual(
            len(player_submission["personal_task_answers"]),
            len(self.session.state.agents["广陵王"].personal_tasks),
        )

    def test_official_scoring_and_history_cover_answers_votes_teams_and_models(self):
        killer_id = self.session.state.flags["killer_id"]
        votes = []
        for agent_id, agent in self.session.state.agents.items():
            suspect_id = (
                next(item for item in self.session.state.agents if item != killer_id)
                if agent_id == killer_id
                else killer_id
            )
            answers = [
                {
                    "question_id": question["id"],
                    "answer": self.session._correct_answer_for(question["id"]),
                }
                for question in self.session.final_questions_for(agent_id)
            ]
            votes.append({
                "voter_id": agent_id,
                "voter_name": agent.display_name,
                "suspect_id": suspect_id,
                "suspect_name": self.session.state.agents[suspect_id].display_name,
                "reason": "测试提交",
                "answers": answers,
            })
            self.session.state.final_submissions[agent_id] = {
                "vote": {"suspect_id": suspect_id, "reason": "测试提交"},
                "answers": answers,
            }
        self.session.state.flags["voting_result"] = {
            "killer_found": True,
        }

        self.session._finalize_scores(
            votes,
            killer_found=True,
        )

        for agent_id, agent in self.session.state.agents.items():
            expected = 3 if agent_id == killer_id else 11
            self.assertEqual(agent.score, expected)
            categories = {entry["category"] for entry in agent.score_breakdown}
            self.assertIn("correct_answer", categories)
            if agent_id != killer_id:
                self.assertIn("innocent_team_found_killer", categories)
                self.assertIn("correct_vote", categories)

        database = (
            Path(self.temp_dir.name)
            / "interactive"
            / "history"
            / "score_history.sqlite3"
        )
        self.assertTrue(database.exists())
        connection = sqlite3.connect(database)
        try:
            participant_count = connection.execute(
                "SELECT COUNT(*) FROM participant_runs WHERE game_id = ?",
                (self.session.state.game_id,),
            ).fetchone()[0]
            answer_count = connection.execute(
                "SELECT COUNT(*) FROM final_answers WHERE game_id = ?",
                (self.session.state.game_id,),
            ).fetchone()[0]
            model_count = connection.execute(
                "SELECT COUNT(*) FROM model_usage WHERE game_id = ?",
                (self.session.state.game_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(participant_count, 6)
        self.assertEqual(answer_count, 18)
        self.assertGreaterEqual(model_count, 6)

    def test_killer_evading_the_vote_awards_five_points(self):
        evaded = self.service.create_game(
            "stormbound_inn",
            game_id="killer-evaded-vote-score-test",
            seed=0,
        )
        killer_id = evaded.state.flags["killer_id"]
        votes = []
        for agent_id, agent in evaded.state.agents.items():
            suspect_id = next(
                candidate_id
                for candidate_id in evaded.state.agents
                if candidate_id not in {agent_id, killer_id}
            )
            votes.append({
                "voter_id": agent_id,
                "voter_name": agent.display_name,
                "suspect_id": suspect_id,
                "suspect_name": evaded.state.agents[suspect_id].display_name,
                "reason": "测试错误票",
                "answers": [],
            })
        evaded.state.flags["voting_result"] = {
            "killer_found": False,
        }
        evaded._finalize_scores(
            votes,
            killer_found=False,
        )
        self.assertEqual(evaded.state.agents[killer_id].score, 5)
        self.assertEqual(
            evaded.state.agents[killer_id].score_breakdown[0]["category"],
            "killer_evaded_vote",
        )


if __name__ == "__main__":
    unittest.main()
