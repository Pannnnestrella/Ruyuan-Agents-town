"""Game-session orchestration for the interactive simulation."""

from __future__ import annotations

import json
import hashlib
import random
import re
import secrets as token_secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Protocol

from .event_director import EventDirector
from .abilities import abilities_for, action_is_authorized, apply_ability
from .models import (
    ActionIntent,
    ActionType,
    Belief,
    EventRecord,
    EventCard,
    GamePhase,
    GameState,
    LifeState,
    Notice,
    RoundResult,
)
from .round_engine import RoundEngine
from .recap import RecapBuilder
from .persistence import atomic_write_json, atomic_write_text, game_state_from_dict
from .history import record_completed_game
from .scenario_loader import LoadedScenario, ScenarioLoader
from .trigger_resolver import TriggerResolver
from .story_compiler import StoryCompiler


class IntentPlanner(Protocol):
    def plan(
        self,
        state: GameState,
        scenario: dict[str, Any],
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        actor_ids: list[str] | None = None,
        force_major: bool = False,
    ) -> list[ActionIntent]: ...

    def respond_to_player(
        self,
        state: GameState,
        scenario: dict[str, Any],
        speaker_id: str,
        player_id: str,
        player_message: str,
    ) -> dict[str, str | None]: ...


class HeuristicIntentPlanner:
    """Dependency-free planner used to exercise the interactive loop.

    It is not the final character intelligence.  The interface is deliberately
    small so the legacy LLM agents can replace it without changing the service
    or API layers.
    """

    def __init__(self, *, seed: int = 0):
        self.random = random.Random(seed)

    def _compose_exchange_line(
        self,
        speaker_id: str,
        target_name: str,
        claim: str,
    ) -> str:
        """Turn structured information sharing into characterful dialogue."""

        fact = str(claim).strip().rstrip("。！？；;")
        character_lines = {
            "广陵王": [
                f"{target_name}，先核实一件事：{fact}。你所见的情况与此一致吗？",
                f"我暂不下结论，但有一点值得查清——{fact}。{target_name}，你怎么看？",
            ],
            "傅融": [
                f"账目可以作假，时辰却总会留下痕迹。{fact}。{target_name}，你能补上缺的那一段吗？",
                f"{target_name}，我重新核过现有记录：{fact}。若你记得不同，最好现在指出来。",
            ],
            "刘辩": [
                f"说来倒有意思，{fact}。{target_name}，你觉得这是巧合，还是有人故意留下的？",
                f"{target_name}，我听到一桩颇耐人寻味的事：{fact}。你可别告诉我自己毫无头绪。",
            ],
            "孙策": [
                f"我不绕弯子：{fact}。{target_name}，你见过什么就直说。",
                f"{fact}。这事靠猜没用，{target_name}，把你知道的时辰和地点对上。",
            ],
            "左慈": [
                f"{target_name}，若把这件事放进前后因果里——{fact}——你觉得哪一处仍说不通？",
                f"贫道只说亲眼可验之事：{fact}。{target_name}，你的记忆可与它相合？",
            ],
            "袁基": [
                f"{target_name}，我先给你一句实话：{fact}。作为交换，我想听听你的判断。",
                f"空泛的怀疑没有价值。现有消息是：{fact}。{target_name}，你能提供什么佐证？",
            ],
        }
        options = character_lines.get(speaker_id) or [
            f"{target_name}，我掌握的情况是：{fact}。你对此知道多少？",
            f"有件事需要当面核对：{fact}。{target_name}，说说你的看法。",
        ]
        return self.random.choice(options)[:180]

    @staticmethod
    def _low_value_claim(claim: str) -> bool:
        text = str(claim)
        return any(fragment in text for fragment in (
            "留在客栈大堂观察局势",
            "本轮没有采取主要行动",
            "公告栏有一条尚未读取的新张贴",
            "公告栏出现了新张贴",
        ))

    def plan(
        self,
        state: GameState,
        scenario: dict[str, Any],
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        actor_ids: list[str] | None = None,
        force_major: bool = False,
    ) -> list[ActionIntent]:
        intents: list[ActionIntent] = []
        participants = {item["id"]: item for item in scenario.get("participants", [])}
        killer_id = state.flags.get("killer_id")
        requested = set(actor_ids) if actor_ids is not None else set(state.agents)
        active_total = sum(
            1 for agent_id, agent in state.agents.items()
            if agent_id in requested and agent.can_act
        )
        completed = 0
        for agent_id in sorted(state.agents):
            agent = state.agents[agent_id]
            if agent_id not in requested or not agent.can_act:
                continue

            if agent_id == killer_id:
                possible_targets = [
                    other for other in state.agents.values()
                    if other.agent_id != agent_id
                    and other.location_id == agent.location_id
                    and other.can_act
                ]
                already_poisoned = agent_id in state.flags.get(
                    "poisons_by_round", {}
                ).get(str(state.round_number + 1), [])
                if possible_targets and not already_poisoned and state.round_number >= 1 and self.random.random() < 0.34:
                    target = self.random.choice(sorted(possible_targets, key=lambda item: item.agent_id))
                    intent = ActionIntent(
                        agent_id,
                        ActionType.POISON,
                        target_id=target.agent_id,
                        reason="秘密下毒，延迟削弱可能在终局投票中指认自己的人",
                    )
                    apply_ability(state, intent)
                    intents.append(intent)
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue
            # Treatment belongs to the innkeeper's character ability.
            if agent_id == "广陵王":
                wounded = [
                    other for other in state.agents.values()
                    if other.location_id == agent.location_id
                    and other.life_state == LifeState.INJURED
                ]
                if wounded:
                    target = sorted(wounded, key=lambda item: item.agent_id)[0]
                    intent = ActionIntent(agent_id, ActionType.TREAT, target_id=target.agent_id)
                    apply_ability(state, intent)
                    intents.append(intent)
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue

            unseen_notices = [
                notice for notice in state.notices
                if agent_id not in notice.seen_by
                and (
                    notice.expires_after_round is None
                    or notice.expires_after_round >= state.round_number
                )
            ]
            if unseen_notices and agent.location_id != "lobby" and not force_major and self.random.random() < 0.45:
                route = self._shortest_path(state, agent.location_id, "lobby")
                if len(route) > 1:
                    intents.append(ActionIntent(
                        agent_id,
                        ActionType.MOVE,
                        location_id=route[1],
                        reason="大堂公告栏出现新张贴，前往读取原文并核对来源",
                    ))
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue

            location = state.locations[agent.location_id]
            others = [
                other for other in state.agents.values()
                if other.agent_id != agent_id
                and other.location_id == agent.location_id
                and other.can_act
            ]
            undiscovered_here = any(
                item.location_id == agent.location_id
                and agent_id not in item.discovered_by
                for item in state.objects.values()
            )
            if location.get("searchable") and undiscovered_here:
                intents.append(
                    ActionIntent(
                        agent_id,
                        ActionType.INVESTIGATE,
                        location_id=agent.location_id,
                        reason="当前地点仍有尚未检查的线索，优先完成现场调查",
                    )
                )
                completed = self._report_progress(
                    progress_callback, agent, completed, active_total
                )
                continue

            public_event_ids = {
                event.event_id for event in state.events if event.public
            }
            notices_by_id = {
                notice.notice_id: notice for notice in state.notices
            }
            exchange_options: list[tuple[Any, Belief]] = []
            for target in others:
                for belief in reversed(agent.beliefs):
                    source_notice = notices_by_id.get(belief.source)
                    if (
                        belief.source not in {"凶手记忆", "个人秘密"}
                        and not str(belief.truth_id or "").startswith("secret:")
                        and belief.source not in public_event_ids
                        and not (
                            source_notice
                            and target.agent_id in source_notice.seen_by
                        )
                        and not self._low_value_claim(belief.claim)
                        and target.agent_id not in belief.shared_with
                        and not any(
                            (
                                belief.truth_id
                                and known.truth_id == belief.truth_id
                            )
                            or (
                                GameSession._normalize_dialogue_text(known.claim)
                                == GameSession._normalize_dialogue_text(belief.claim)
                            )
                            for known in target.beliefs
                        )
                    ):
                        exchange_options.append((target, belief))
                        break
            if exchange_options and not force_major:
                target, shared = self.random.choice(exchange_options)
                talk_intent = ActionIntent(
                    agent_id,
                    ActionType.TALK,
                    target_id=target.agent_id,
                    content=self._compose_exchange_line(
                        agent_id,
                        target.display_name,
                        shared.claim,
                    ),
                    reason="依据人物说话方式提出信息、质询或交换条件",
                    metadata={"share_belief_id": shared.belief_id},
                )
                intents.append(talk_intent)
                completed = self._report_progress(
                    progress_callback, agent, completed, active_total
                )
                continue

            if agent.location_id == "lobby":
                existing_posts = {notice.content for notice in state.notices}
                other_agent_ids = set(state.agents) - {agent_id}
                publishable = next((
                    belief for belief in reversed(agent.beliefs)
                    if belief.confidence >= 0.75
                    and belief.source not in {"凶手记忆", "个人秘密"}
                    and not str(belief.truth_id or "").startswith("secret:")
                    and belief.source not in public_event_ids
                    and not self._low_value_claim(belief.claim)
                    and belief.claim not in existing_posts
                    and not other_agent_ids.issubset(set(belief.shared_with))
                ), None)
                if publishable and self.random.random() < 0.25:
                    intents.append(ActionIntent(
                        agent_id,
                        ActionType.POST_NOTICE,
                        content=publishable.claim,
                        reason="这条情报已经足够可靠，公开后能让分散的调查者共同核对",
                    ))
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue

            connections = list(location.get("connections", []))
            if connections and not force_major:
                destination = self.random.choice(sorted(connections))
                intents.append(
                    ActionIntent(
                        agent_id,
                        ActionType.MOVE,
                        location_id=destination,
                        reason="前往相邻地点寻找新的线索或交谈对象",
                    )
                )
            else:
                intents.append(ActionIntent(agent_id, ActionType.WAIT))
            completed = self._report_progress(
                progress_callback, agent, completed, active_total
            )
        for intent in intents:
            agent = state.agents[intent.actor_id]
            apply_ability(state, intent)
            participant = participants.get(intent.actor_id, {})
            previous = dict(agent.strategic_plan)
            goals = [str(item) for item in participant.get("goals", [])]
            current_step = intent.reason or f"执行{intent.action_type.value}行动"
            follow_up = next(
                (
                    str(step) for step in previous.get("steps", [])
                    if str(step) and str(step) != current_step
                ),
                goals[1] if len(goals) > 1 else "根据本轮结果重新核对线索",
            )
            intent.metadata["strategic_plan"] = {
                "objective": previous.get("objective") or (goals[0] if goals else "观察并适应局势"),
                "horizon_rounds": 3,
                "steps": [current_step, follow_up, "在终局前形成可解释的判断"],
                "contingencies": ["若出现新证据或人身危险，优先重新评估当前路线"],
                "suspects": list(previous.get("suspects", [])),
                "public_posture": previous.get("public_posture", "保持谨慎，避免过早下结论"),
                "revision_reason": "本轮由本地规则根据既有目标延续计划。",
                "source": "heuristic",
            }
        return intents

    @staticmethod
    def _report_progress(
        progress_callback: Callable[[dict[str, Any]], None] | None,
        agent: Any,
        completed: int,
        total: int,
    ) -> int:
        completed += 1
        if progress_callback:
            progress_callback({
                "stage": "intent",
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "status": "completed",
                "source": "heuristic",
                "completed": completed,
                "total": total,
            })
        return completed

    @staticmethod
    def _shortest_path(state: GameState, start: str, destination: str) -> list[str]:
        if start == destination:
            return [start]
        queue: list[list[str]] = [[start]]
        visited = {start}
        while queue:
            path = queue.pop(0)
            for neighbor in state.locations[path[-1]].get("connections", []):
                if neighbor in visited:
                    continue
                next_path = [*path, neighbor]
                if neighbor == destination:
                    return next_path
                visited.add(neighbor)
                queue.append(next_path)
        return [start]

    def vote(
        self,
        state: GameState,
        scenario: dict[str, Any],
        voter_id: str,
    ) -> dict[str, Any]:
        voter = state.agents[voter_id]
        candidates = [
            agent for agent in state.agents.values()
            if agent.agent_id != voter_id and agent.life_state != LifeState.DEAD
        ]
        if not candidates:
            return {"suspect_id": voter_id, "reason": "已经没有其他可指认的人。"}

        suspicion_words = (
            "凶手", "毒", "藏", "异常", "伪造", "指控", "说谎", "失踪", "矛盾", "掩护"
        )
        scores = {candidate.agent_id: 0.0 for candidate in candidates}
        evidence = {candidate.agent_id: [] for candidate in candidates}
        for belief in voter.beliefs:
            weight = max(0.1, float(belief.confidence))
            for candidate in candidates:
                if candidate.display_name not in belief.claim:
                    continue
                if any(word in belief.claim for word in suspicion_words):
                    scores[candidate.agent_id] += weight
                    evidence[candidate.agent_id].append(belief.claim)

        for event in state.events:
            if voter_id not in event.witnesses and voter_id not in event.actors:
                continue
            event_weight = {
                "object_transfer": 0.4,
            }.get(event.event_type, 0.0)
            for actor_id in event.actors[:1]:
                if actor_id in scores and event_weight:
                    scores[actor_id] += event_weight
                    evidence[actor_id].append(event.summary)

        killer_id = state.flags.get("killer_id")
        if voter_id == killer_id:
            # The culprit deliberately backs the most plausible alternative.
            non_killer = [candidate for candidate in candidates if candidate.agent_id != killer_id]
            if non_killer:
                candidates = non_killer
        suspect = max(
            sorted(candidates, key=lambda item: item.agent_id),
            key=lambda item: scores.get(item.agent_id, 0.0),
        )
        reasons = evidence.get(suspect.agent_id, [])
        reason = (
            f"我的记忆中最可疑的一点是：{reasons[-1]}"
            if reasons
            else f"现有记忆无法形成铁证，但{suspect.display_name}的行踪最需要重新核对。"
        )
        questions = list(
            (
                (scenario.get("final_assessment") or {}).get("questions_by_agent") or {}
            ).get(voter_id, [])
        )
        memory_text = " ".join(belief.claim for belief in voter.beliefs)
        answers = []
        for question in questions:
            options = list(question.get("options", []))
            if question.get("option_source") == "agents":
                options = [
                    {"id": agent.agent_id, "label": agent.display_name}
                    for agent in state.agents.values()
                ]
            answer = ""
            if question.get("type") == "agent_choice":
                answer = suspect.agent_id
            elif options:
                answer = max(
                    options,
                    key=lambda option: sum(
                        1 for character in str(option.get("label", ""))
                        if character.strip() and character in memory_text
                    ),
                ).get("id", "")
            answers.append({
                "question_id": str(question.get("id", "")),
                "answer": str(answer),
            })
        return {
            "suspect_id": suspect.agent_id,
            "reason": reason[:180],
            "answers": answers,
            "case_conclusion": {
                "killer": suspect.agent_id,
                "motive": "",
                "true_cause_of_death": "",
                "time_of_death": "",
                "primary_crime_scene": "",
                "method": "",
                "weapon_or_medium": "",
                "approach_route": "",
                "alibi_method": "",
                "evidence_disposal": "",
                "key_facts": [
                    belief.belief_id for belief in voter.beliefs
                    if belief.information_type == "fact"
                ][-4:],
                "unreliable_testimonies": [
                    belief.belief_id for belief in voter.beliefs
                    if belief.information_type == "testimony"
                    and belief.confidence_score <= 2
                ][-4:],
                "reasoning_chain": reason[:180],
                "alternative_suspects_excluded": [],
                "confidence": 3,
            },
            "personal_task_answers": [
                {
                    "question": str(task.get("question", "")),
                    "answer": str(
                        task.get("current_hypothesis")
                        or "依据当前掌握的信息形成暂定答案"
                    ),
                    "supporting_facts": list(task.get("known_information", [])),
                    "supporting_testimonies": [],
                    "remaining_uncertainty": list(task.get("missing_information", [])),
                    "confidence": int(task.get("confidence", 0)),
                }
                for task in voter.personal_tasks
            ],
            "_model_source": "heuristic",
        }

    def respond_to_player(
        self,
        state: GameState,
        scenario: dict[str, Any],
        speaker_id: str,
        player_id: str,
        player_message: str,
    ) -> dict[str, str | None]:
        """Give a grounded in-character reply when no LLM is available."""

        speaker = state.agents[speaker_id]
        listener = state.agents[player_id]
        public_event_ids = {
            event.event_id for event in state.events if event.public
        }
        notices_by_id = {
            notice.notice_id: notice for notice in state.notices
        }
        shareable = [
            belief for belief in speaker.beliefs
            if belief.source not in {"凶手记忆", "个人秘密"}
            and not str(belief.truth_id or "").startswith("secret:")
            and belief.source not in public_event_ids
            and not (
                belief.source in notices_by_id
                and player_id in notices_by_id[belief.source].seen_by
            )
            and not self._low_value_claim(belief.claim)
            and player_id not in belief.shared_with
            and not any(
                (
                    belief.truth_id
                    and known.truth_id == belief.truth_id
                )
                or (
                    GameSession._normalize_dialogue_text(known.claim)
                    == GameSession._normalize_dialogue_text(belief.claim)
                )
                for known in listener.beliefs
            )
        ]
        shared = shareable[-1] if shareable else None
        if speaker_id == state.flags.get("killer_id"):
            evasions = [
                f"{listener.display_name}，你现在追问的是推测，还是已经有了能落到时辰和地点上的证据？",
                f"先说清楚你依据的是谁的口供。没有来源的怀疑，我不会顺着它替任何人定罪。",
                f"你把问题问得太快了。若真要查我，就先解释这句话与你掌握的物证如何相连。",
            ]
            text = self.random.choice(evasions)
            shared = None
        elif shared:
            fact = shared.claim.strip().rstrip("。！？")
            replies = [
                f"{fact}。这与刚才的说法究竟相合还是冲突，得把时辰重新排一遍。",
                f"等等，{listener.display_name}。{fact}。你刚才的判断漏掉了这一处。",
                f"{fact}。如果这条记忆没有出错，真正需要解释的就不是表面上的那个人。",
                f"我想到另一件事：{fact}。你愿意用自己的行踪来验证它吗？",
            ]
            text = self.random.choice(replies)
        elif "?" in player_message or "？" in player_message:
            text = self.random.choice([
                f"这个问题我现在答不死。{listener.display_name}，先把你引用的那条证词来源说清楚。",
                "我没有能直接支持这个结论的记忆。与其逼我选边，不如先找出两段口供冲突的时辰。",
                "若只凭现有这些话，我只能说两种解释都成立。你手里有没有能排除其中一种的物证？",
            ])
        else:
            excerpt = str(player_message).strip()[:45]
            text = self.random.choice([
                f"你刚才说“{excerpt}”。这句话里最需要核对的是时间，而不是态度。",
                f"我听见了，但这还只是你的陈述。谁在场、何时发生、有什么实物能留下来？",
                f"这条说法可以先记下。下一步应当找一个不依赖你我立场的证据来验证。",
            ])
        item_request = any(word in player_message for word in ("出示", "展示", "随身", "物品", "搜身", "给我看"))
        display_object_id = None
        item_disposition = "none"
        if item_request:
            safe_items = [
                object_id for object_id in speaker.inventory
                if object_id in state.objects
                and "evidence" not in state.objects[object_id].tags
            ]
            if speaker_id == state.flags.get("killer_id") or not safe_items:
                text = "你可以问我来意，却不能凭一句怀疑就翻看我的随身之物。我拒绝。"
                item_disposition = "refuse"
            else:
                display_object_id = safe_items[0]
                item = state.objects[display_object_id]
                text = f"可以。我当面出示{item.name}，但它仍由我保管；你只能验看，不能拿走。"
                item_disposition = "show"
        return {
            "content": text[:180],
            "share_belief_id": shared.belief_id if shared else None,
            "display_object_id": display_object_id,
            "item_disposition": item_disposition,
            "_host_item_disposition": item_disposition,
            "_model_source": "heuristic_fallback",
        }


class GameSession:
    def __init__(
        self,
        loaded: LoadedScenario,
        state: GameState,
        *,
        results_root: str | Path,
        seed: int = 0,
        planner: IntentPlanner | None = None,
    ):
        self.loaded = loaded
        self.state = state
        self.results_root = Path(results_root)
        self.director = EventDirector(loaded.scenario.get("event_cards", []), seed=seed)
        self.engine = RoundEngine(seed=seed)
        self.planner = planner or HeuristicIntentPlanner(seed=seed)
        self.recap_builder = RecapBuilder()
        self.trigger_resolver = TriggerResolver(loaded.scenario.get("round_triggers", []))
        self.story_compiler = StoryCompiler()
        self.random = random.Random(seed + 711)
        self._notice_sequence = len(state.notices)
        self._event_sequence = len(state.events)
        self._save_lock = threading.RLock()
        self.engine._event_sequence = len(state.events)
        self.director._event_sequence = len(state.events)
        self.trigger_resolver._event_sequence = len(state.events)
        self.issued_player_token: str | None = None
        self._ensure_pregame_timelines()
        self._discard_legacy_movement_beliefs()
        self._discard_recursive_conversation_beliefs()
        self._normalize_universal_public_knowledge()
        self._record_model_assignments()
        self.save()

    def _ensure_pregame_timelines(self) -> None:
        """Backfill authored chronologies when opening a save from an older build."""

        if self.state.flags.get("character_timelines"):
            return
        case_id = str(
            (self.state.flags.get("case_manifest") or {}).get("case_id") or ""
        )
        timelines, objective = self.loaded._materialize_timelines(case_id)
        self.state.flags["character_timelines"] = timelines
        self.state.flags["objective_timeline"] = objective
        for agent_id, entries in timelines.items():
            agent = self.state.agents.get(agent_id)
            if agent is None:
                continue
            existing_sources = {belief.source for belief in agent.beliefs}
            for entry in entries:
                source = f"timeline:{entry['id']}"
                if source in existing_sources:
                    continue
                agent.beliefs.append(Belief(
                    belief_id=f"belief-{agent_id}-timeline-{entry['id']}",
                    claim=str(entry["text"]),
                    source=source,
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id=(
                        "truth-killer"
                        if entry.get("kind") == "killer-private" else None
                    ),
                ))

    def _discard_legacy_movement_beliefs(self) -> None:
        """Migrate saved games created before movement stopped being memory."""

        movement_event_ids = {
            event.event_id for event in self.state.events if event.event_type == "move"
        }
        if not movement_event_ids:
            return
        for agent in self.state.agents.values():
            agent.beliefs = [
                belief for belief in agent.beliefs
                if belief.source not in movement_event_ids
            ]

    def _discard_recursive_conversation_beliefs(self) -> None:
        """Remove legacy self-echo memories that could recursively feed dialogue."""

        conversation_by_id = {
            event.event_id: event
            for event in self.state.events if event.event_type == "conversation"
        }
        for agent in self.state.agents.values():
            cleaned: list[Belief] = []
            seen_claims: set[str] = set()
            for belief in agent.beliefs:
                event = conversation_by_id.get(belief.source)
                if event and event.payload.get("speaker_id") == agent.agent_id:
                    continue
                if event:
                    raw_claim = str(
                        event.payload.get("shared_claim")
                        or event.payload.get("content")
                        or belief.claim
                    )
                    belief.claim = self._extract_information_claim(raw_claim)
                normalized = self._normalize_dialogue_text(belief.claim)
                if event and normalized in seen_claims:
                    continue
                if event:
                    seen_claims.add(normalized)
                cleaned.append(belief)
            agent.beliefs = cleaned

    @staticmethod
    def _extract_information_claim(value: str) -> str:
        text = str(value).strip()
        for _ in range(8):
            previous = text
            text = re.sub(r"^我曾对[^：:]{1,20}说[：:]", "", text).strip()
            text = re.sub(
                r"^(?:我把这条情报告诉你|我愿意把这条情报告诉你|我愿意分享一条尚未与你核对的信息)[：:]",
                "",
                text,
            ).strip()
            text = re.split(
                r"[。；;]?你(?:是否)?有能相互印证的线索(?:吗|\?|？)?",
                text,
                maxsplit=1,
            )[0].strip(" 。；;：:")
            if text == previous:
                break
        return text or str(value).strip()

    @staticmethod
    def _normalize_dialogue_text(value: str) -> str:
        extracted = GameSession._extract_information_claim(value)
        text = re.sub(r"[\s，。！？；：“”‘’、,.!?;:]", "", extracted)
        return text[:240]

    def public_state(self) -> dict[str, Any]:
        data = self.state.public_view()
        data["title"] = self.loaded.scenario["title"]
        data["premise"] = self.loaded.scenario["premise"]
        data["planner"] = self.planner.__class__.__name__
        data["planner_provider"] = getattr(self.planner, "provider_name", "heuristic")
        recent_model_calls = [
            item for item in self.state.model_usage
            if item.get("stage") in {"action", "round_discussion"}
        ][-24:]
        fallback_calls = [
            item for item in recent_model_calls
            if item.get("actual_source") == "heuristic_fallback"
        ]
        data["planner_runtime"] = {
            "recent_calls": len(recent_model_calls),
            "fallback_calls": len(fallback_calls),
            "llm_calls": sum(
                item.get("actual_source") == "llm"
                for item in recent_model_calls
            ),
            "is_falling_back": bool(
                recent_model_calls
                and len(fallback_calls) == len(recent_model_calls)
            ),
        }
        data["public_facts"] = self.loaded.scenario.get("public_facts", [])
        data["ending_questions"] = self.loaded.scenario.get("ending_questions", [])
        data["game_rules"] = self.loaded.scenario.get("game_rules", [])
        data["controlled_agent_id"] = self.state.player_agent_id
        if self.state.phase == GamePhase.FINISHED:
            data["voting_result"] = dict(self.state.flags.get("voting_result", {}))
            data["scoreboard"] = self.scoreboard()
        return data

    def observer_state(self) -> dict[str, Any]:
        """Return the live-map view without exposing the director's casebook.

        The live observer needs local movement, investigation, and conversation
        events to animate the map and build character tracks.  Those events are
        intentionally absent from ``public_state`` because players outside the
        scene must not learn them.  Secret poisoning attempts remain hidden here;
        only their later, observable effect may enter the live event stream.
        """

        data = self.public_state()
        data["events"] = [
            event.to_dict()
            for event in self.state.events
            if event.event_type != "poison_queued"
            and not (
                event.event_type == "action_failed"
                and event.payload.get("action") == "下毒"
            )
        ]
        return data

    def set_planner(self, planner: IntentPlanner) -> dict[str, str]:
        if self.state.phase == GamePhase.RESOLVING:
            raise ValueError("角色正在决策，需等待当前行动完成后再切换模型")
        self.planner = planner
        self._record_model_assignments(force=True)
        self.save()
        return {
            "planner": planner.__class__.__name__,
            "planner_provider": str(getattr(planner, "provider_name", "heuristic")),
        }

    def _record_model_assignments(self, *, force: bool = False) -> None:
        provider_name = str(getattr(self.planner, "provider_name", "heuristic"))
        for agent_id in self.state.agents:
            assigned = "human" if agent_id == self.state.player_agent_id else provider_name
            previous = next(
                (
                    item for item in reversed(self.state.model_usage)
                    if item.get("agent_id") == agent_id and item.get("stage") == "assignment"
                ),
                None,
            )
            if not force and previous and previous.get("provider_name") == assigned:
                continue
            self._record_model_usage(
                agent_id,
                stage="assignment",
                actual_source="player_input" if assigned == "human" else "configured",
                provider_name=assigned,
            )

    def _record_model_usage(
        self,
        agent_id: str,
        *,
        stage: str,
        actual_source: str,
        provider_name: str | None = None,
        succeeded: bool = True,
    ) -> None:
        self.state.model_usage.append({
            "usage_id": f"usage-{self.state.game_id}-{len(self.state.model_usage) + 1:05d}",
            "agent_id": agent_id,
            "stage": stage,
            "round_number": self.state.round_number,
            "action_step": self.state.action_step,
            "provider_name": provider_name or str(
                getattr(self.planner, "provider_name", "heuristic")
            ),
            "actual_source": actual_source,
            "succeeded": bool(succeeded),
        })

    def final_questions_for(self, agent_id: str) -> list[dict[str, Any]]:
        assessment = dict(self.loaded.scenario.get("final_assessment", {}))
        authored = list(
            (assessment.get("questions_by_agent") or {}).get(agent_id, [])
        )
        questions: list[dict[str, Any]] = []
        for raw in authored:
            question = {
                key: value for key, value in dict(raw).items()
                if key not in {"answer", "correct_answer"}
            }
            if question.get("option_source") == "agents":
                question["options"] = [
                    {"id": other.agent_id, "label": other.display_name}
                    for other in self.state.agents.values()
                ]
            questions.append(question)
        return questions

    def _correct_answer_for(self, question_id: str) -> str:
        assessment = dict(self.loaded.scenario.get("final_assessment", {}))
        rule = dict((assessment.get("answer_key") or {}).get(question_id, {}))
        resolver = str(rule.get("resolver", ""))
        if resolver == "literal":
            return str(rule.get("answer", ""))
        if resolver == "state_flag":
            return str(self.state.flags.get(str(rule.get("path", "")), ""))
        if resolver == "case_manifest":
            return str(
                (self.state.flags.get("case_manifest") or {}).get(
                    str(rule.get("path", "")), ""
                )
            )
        raise ValueError(f"Unsupported final-answer resolver for {question_id}")

    def _clean_final_answers(
        self,
        agent_id: str,
        answers: list[dict[str, Any]] | None,
    ) -> list[dict[str, str]]:
        questions = {item["id"]: item for item in self.final_questions_for(agent_id)}
        cleaned: dict[str, dict[str, str]] = {}
        for raw in answers or []:
            question_id = str(raw.get("question_id", ""))
            answer = str(raw.get("answer", ""))
            question = questions.get(question_id)
            if not question:
                continue
            valid_answers = {
                str(option.get("id", "")) for option in question.get("options", [])
            }
            if answer not in valid_answers:
                continue
            cleaned[question_id] = {
                "question_id": question_id,
                "answer": answer,
            }
        return [
            cleaned.get(question_id, {"question_id": question_id, "answer": ""})
            for question_id in questions
        ]

    def _structured_final_submission(
        self,
        agent_id: str,
        suspect_id: str,
        reason: str,
        case_conclusion: dict[str, Any] | None = None,
        personal_task_answers: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        agent = self.state.agents[agent_id]
        known_ids = {belief.belief_id for belief in agent.beliefs}
        facts = [
            belief.belief_id for belief in agent.beliefs
            if belief.information_type == "fact"
        ]
        testimonies = [
            belief.belief_id for belief in agent.beliefs
            if belief.information_type == "testimony"
        ]
        raw_case = dict(case_conclusion or {})
        case_fields = (
            "motive", "true_cause_of_death", "time_of_death",
            "primary_crime_scene", "method", "weapon_or_medium",
            "approach_route", "alibi_method", "evidence_disposal",
            "reasoning_chain",
        )
        cleaned_case: dict[str, Any] = {
            "killer": (
                str(raw_case.get("killer") or suspect_id)
                if str(raw_case.get("killer") or suspect_id) in self.state.agents
                else suspect_id
            ),
            **{
                key: str(raw_case.get(key) or (
                    reason if key == "reasoning_chain" else ""
                ))[:500]
                for key in case_fields
            },
            "key_facts": [
                str(item) for item in raw_case.get("key_facts", facts[-6:])
                if str(item) in known_ids
            ][:12],
            "unreliable_testimonies": [
                str(item) for item in raw_case.get(
                    "unreliable_testimonies", testimonies[-4:]
                )
                if str(item) in known_ids
            ][:12],
            "alternative_suspects_excluded": [
                str(item) for item in raw_case.get(
                    "alternative_suspects_excluded", []
                )
                if str(item) in self.state.agents
                and str(item) != suspect_id
            ],
            "confidence": max(0, min(5, int(raw_case.get("confidence", 3)))),
        }

        submitted_by_question = {
            str(item.get("question", "")): item
            for item in personal_task_answers or []
            if isinstance(item, dict)
        }
        cleaned_tasks: list[dict[str, Any]] = []
        for task in agent.personal_tasks:
            question = str(task.get("question", ""))
            raw = dict(submitted_by_question.get(question, {}))
            cleaned_tasks.append({
                "question": question,
                "answer": str(
                    raw.get("answer")
                    or task.get("current_hypothesis")
                    or "尚未形成确定答案"
                )[:500],
                "supporting_facts": [
                    str(item) for item in raw.get(
                        "supporting_facts", task.get("known_information", facts[-3:])
                    )
                    if str(item) in known_ids
                ][:10],
                "supporting_testimonies": [
                    str(item) for item in raw.get(
                        "supporting_testimonies", testimonies[-3:]
                    )
                    if str(item) in known_ids
                ][:10],
                "remaining_uncertainty": [
                    str(item)[:240] for item in raw.get(
                        "remaining_uncertainty",
                        task.get("missing_information", []),
                    )
                ][:10],
                "confidence": max(
                    0, min(5, int(raw.get("confidence", task.get("confidence", 0))))
                ),
            })
        return cleaned_case, cleaned_tasks

    def director_state(self) -> dict[str, Any]:
        """Return the omniscient casebook used only by the local host console.

        The ordinary state and player endpoints deliberately omit this material.
        Keeping the casebook behind a distinct endpoint makes it much harder for
        the role view to reveal the seeded killer or another character's memory by
        accident.
        """

        data = self.public_state()
        participants = {
            item["id"]: item for item in self.loaded.scenario.get("participants", [])
        }
        killer_id = str(self.state.flags.get("killer_id", ""))
        killer = self.state.agents.get(killer_id)
        profile = dict(self.state.flags.get("killer_profile", {}))
        manifest = dict(self.state.flags.get("case_manifest", {}))

        weapon_id = str(
            (self.loaded.scenario.get("killer_setup") or {}).get("weapon_object_id", "")
        )
        weapon = self.state.objects.get(weapon_id)
        stolen_id = str(manifest.get("stolen_item_id") or "")
        stolen = self.state.objects.get(stolen_id)
        evidence = [
            self.state.objects[object_id].to_dict(reveal_hidden=True, reveal_metadata=True)
            for object_id in manifest.get("evidence_object_ids", [])
            if object_id in self.state.objects
        ]

        murder_chain = [
            {
                "stage": "诱因",
                "title": "死者带着足以改变局势的真信进入客栈",
                "detail": str(profile.get("motive", "")),
            },
            {
                "stage": "行凶",
                "title": f"{killer.display_name if killer else killer_id}趁近身机会下手",
                "detail": str(profile.get("method", "")),
            },
            {
                "stage": "取走",
                "title": f"关键物“{stolen.name}”失踪" if stolen else "死者携带的关键物失踪",
                "detail": str((stolen.metadata if stolen else {}).get("description", "")),
            },
            {
                "stage": "遗痕",
                "title": "凶手留下了可被交叉验证的专属痕迹",
                "detail": "；".join(
                    f"{item['name']}：{item.get('metadata', {}).get('description', '')}"
                    for item in evidence
                ),
            },
            {
                "stage": "掩护预案",
                "title": "凶手试图在终局投票中摆脱正确指认",
                "detail": str(profile.get("cover_plan", "")),
            },
        ]

        character_files: list[dict[str, Any]] = []
        for agent_id, agent in self.state.agents.items():
            participant = participants.get(agent_id, {})
            owned_secrets = [
                secret.to_dict()
                for secret in self.state.secrets.values()
                if secret.owner_id == agent_id
            ]
            inventory = [
                self.state.objects[object_id].to_dict(
                    reveal_hidden=True, reveal_metadata=True
                )
                for object_id in agent.inventory
                if object_id in self.state.objects
            ]
            actions = [
                event.to_dict()
                for event in self.state.events
                if agent_id in event.actors
            ]
            witnessed = [
                event.to_dict()
                for event in self.state.events
                if agent_id in event.witnesses and agent_id not in event.actors
            ]
            character_files.append({
                "agent_id": agent_id,
                "display_name": agent.display_name,
                "is_killer": agent_id == killer_id,
                "public_role": agent.public_role,
                "background_story": list(participant.get("background_story", [])),
                "opening_hook": str(participant.get("opening_hook", "")),
                "background_memories": list(participant.get("background_memories", [])),
                "pregame_timeline": list(
                    self.state.flags.get("character_timelines", {}).get(agent_id, [])
                ),
                "goals": list(participant.get("goals", [])),
                "decision_rules": list(participant.get("decision_rules", [])),
                "private_facts": list(participant.get("private_facts", [])),
                "current_state": agent.to_dict(include_private=True),
                "inventory_objects": inventory,
                "secrets": owned_secrets,
                "actions": actions,
                "witnessed_events": witnessed,
            })

        authored_objects = {
            item["id"]: item for item in self.loaded.scenario.get("objects", [])
        }
        for item in [profile.get("stolen_item"), *profile.get("evidence_objects", [])]:
            if item:
                authored_objects[item["id"]] = item
        clue_map: list[dict[str, Any]] = []
        truth_claims = {
            item["id"]: item.get("claim", "")
            for item in self.loaded.scenario.get("truths", [])
        }
        for object_id, item in self.state.objects.items():
            authored = authored_objects.get(object_id, {})
            metadata = dict(item.metadata)
            tags = list(item.tags)
            kind = str(metadata.get("clue_kind", ""))
            if not kind:
                kind = (
                    "decoy" if "misdirection" in tags
                    else "secret" if "secret" in tags
                    else "evidence" if "evidence" in tags
                    else "personal"
                )
            if item.holder_id in self.state.agents:
                current_where = f"{self.state.agents[item.holder_id].display_name}随身持有"
                current_group = f"holder:{item.holder_id}"
            elif item.location_id in self.state.locations:
                current_where = self.state.locations[item.location_id]["name"]
                current_group = f"location:{item.location_id}"
            else:
                current_where = "当前不在任何房间或人物手中"
                current_group = "unplaced"
            authored_holder = str(authored.get("holder_id") or "")
            authored_location = str(authored.get("location_id") or "")
            initial_where = (
                f"{killer.display_name}随身" if authored_holder == "$killer" and killer
                else
                f"{self.state.agents[authored_holder].display_name}随身"
                if authored_holder in self.state.agents
                else self.state.locations[authored_location]["name"]
                if authored_location in self.state.locations
                else "本局变体生成"
            )
            truth_id = str(metadata.get("truth_id") or "")
            claim = str(
                metadata.get("clue_claim")
                or metadata.get("description")
                or (
                    "这是角色的随身物或身份物证，需要结合持有者的口供、秘密与行动判断。"
                    if item.holder_id else "该物件需要与其他线索交叉验证，不能单独定罪。"
                )
            )
            clue_map.append({
                "object_id": object_id,
                "name": item.name,
                "kind": kind,
                "tags": tags,
                "is_case_variant": "case_variant" in tags,
                "hidden": item.hidden,
                "searchable": item.location_id is not None,
                "current_where": current_where,
                "current_group": current_group,
                "initial_where": initial_where,
                "claim": claim,
                "truth_id": truth_id or None,
                "truth_claim": truth_claims.get(truth_id, ""),
                "reveals_secret_id": metadata.get("reveals_secret_id"),
                "implicates": metadata.get("implicates"),
                "discovered_by": [
                    self.state.agents[agent_id].display_name
                    for agent_id in item.discovered_by
                    if agent_id in self.state.agents
                ],
            })

        reference_index: dict[str, dict[str, str]] = {}
        for clue in clue_map:
            reference_index[clue["object_id"]] = {
                "label": clue["name"],
                "where": clue["current_where"],
                "kind": clue["kind"],
            }
        for candidate in (self.loaded.scenario.get("killer_setup") or {}).get("candidates", []):
            candidate_name = self.state.agents[candidate["agent_id"]].display_name
            dormant_items = [candidate.get("stolen_item"), *candidate.get("evidence_objects", [])]
            for dormant in dormant_items:
                if not dormant or dormant["id"] in reference_index:
                    continue
                dormant_location = str(dormant.get("location_id") or "")
                holder = str(dormant.get("holder_id") or "")
                reference_index[dormant["id"]] = {
                    "label": str(dormant.get("name", dormant["id"])),
                    "where": (
                        f"{candidate_name}随身持有"
                        if holder == "$killer" or holder == candidate["agent_id"]
                        else self.state.locations.get(dormant_location, {}).get("name", "本变体生成")
                    ),
                    "kind": "variant",
                }
        for intel in self.loaded.scenario.get("public_intel", []):
            reference_index[intel["id"]] = {
                "label": str(intel.get("title", intel["id"])),
                "where": "主持台公开情报",
                "kind": "intel",
            }
        for card in self.loaded.scenario.get("event_cards", []):
            reference_index[card["id"]] = {
                "label": str(card.get("title", card["id"])),
                "where": "主持事件卡",
                "kind": "event_card",
            }

        deduction = dict(self.loaded.scenario.get("director_deduction", {}))
        guides = []
        for guide in deduction.get("variant_guides", []):
            guides.append({
                **guide,
                "active": guide.get("case_id") == manifest.get("case_id"),
            })

        data["events"] = [event.to_dict() for event in self.state.events]
        data["objects"] = {
            object_id: item.to_dict(reveal_hidden=True, reveal_metadata=True)
            for object_id, item in self.state.objects.items()
        }
        data["director_casebook"] = {
            "killer_id": killer_id,
            "killer_name": killer.display_name if killer else killer_id,
            "motive": str(profile.get("motive", "")),
            "method": str(profile.get("method", "")),
            "cover_plan": str(profile.get("cover_plan", "")),
            "weapon": weapon.to_dict(reveal_hidden=True, reveal_metadata=True)
            if weapon else None,
            "stolen_item": stolen.to_dict(reveal_hidden=True, reveal_metadata=True)
            if stolen else None,
            "evidence": evidence,
            "murder_chain": murder_chain,
            "timeline_title": str(
                (self.loaded.scenario.get("timeline") or {}).get("title", "案发前时间线")
            ),
            "objective_timeline": list(self.state.flags.get("objective_timeline", [])),
            "objective_truths": list(self.loaded.scenario.get("truths", [])),
            "characters": character_files,
            "all_secrets": [secret.to_dict() for secret in self.state.secrets.values()],
            "clue_map": clue_map,
            "shared_deduction_foundation": list(deduction.get("shared_foundation", [])),
            "variant_guides": guides,
            "reference_index": reference_index,
        }
        return data

    def verify_player_token(self, token: str) -> str:
        player_id = self.state.player_agent_id
        expected = str(self.state.flags.get("player_token_hash", ""))
        actual = hashlib.sha256(str(token).encode("utf-8")).hexdigest()
        if not player_id or not expected or not token_secrets.compare_digest(expected, actual):
            raise ValueError("角色席凭证无效，请从本局的选角页面重新进入")
        return player_id

    def _build_story_guide(
        self,
        player_id: str,
        known_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Turn simulation state into a concise, first-person dramatic prompt."""

        phase = self.state.phase
        actor = self.state.agents[player_id]
        location = self.state.locations.get(actor.location_id, {})
        location_name = str(location.get("name", actor.location_id))
        display_round = min(self.state.round_number + 1, self.state.max_rounds)
        action_number = min(self.state.action_step + 1, self.state.actions_per_round)
        latest_event = next(
            (
                event for event in reversed(known_events)
                if event.get("event_type") not in {"vote_cast", "killer_revealed"}
            ),
            None,
        )
        recent = str(latest_event.get("summary", "")) if latest_event else ""

        active_card = next(
            (
                card for card in self.loaded.scenario.get("event_cards", [])
                if card.get("card_id") == self.state.active_event_card
            ),
            None,
        )
        card_description = str((active_card or {}).get("description", ""))
        killer_id = str(self.state.flags.get("killer_id", ""))

        if phase == GamePhase.INTERVENTION:
            title = f"第 {display_round} 轮 · 风雨未歇"
            situation = "客栈暂时陷入压抑的安静。主持权现在交到你手中：事件与公开情报都不会自动发生。"
            objective = "查看三张候选事件卡，决定是否发布一条公开情报，再亲自选择本轮变局或“无事件”。"
            suggestions = ["先读事件影响再选择", "公开情报也可以留空", "主持选择不会替角色作出行动"]
        elif phase in {GamePhase.READY, GamePhase.PLAYER_TURN}:
            title = f"第 {display_round} 轮 · 主要行动 {self.state.action_step}/{self.state.actions_per_round}"
            situation = card_description or recent or f"你此刻位于{location_name}，所有人都在根据刚刚发生的事重新打算。"
            if player_id == killer_id:
                objective = "选择一个能推进表面目标、又不会暴露作案事实的行动。别人会记住你做过和说过的一切。"
            else:
                objective = "自由移动和交谈以探索现场；确认目标后再使用有限的搜查、交付或治疗行动。"
            if action_number == 1:
                suggestions = ["先确认现场与同室者", "调查最贴近个人任务的房间", "用问题试探他人掌握了什么"]
            elif action_number < self.state.actions_per_round:
                suggestions = ["根据刚发生的行动修正判断", "追问一条矛盾信息", "交换一条不致暴露自己的记忆"]
            else:
                suggestions = ["这是本轮最后一次行动", "补上尚未验证的关键环节", "为下一轮保留可追查的目标"]
        elif phase == GamePhase.RESOLVING:
            title = f"第 {display_round} 轮 · 局势正在回应"
            situation = recent or "你已经作出决定，客栈中的其他人正在同时回应新的局势。"
            objective = "观察地图与最新动静。等所有人的行动结算后，你会获得下一次决策机会。"
            suggestions = ["注意谁改变了位置", "记住谁与谁发生了交谈", "检查新消息是否与自己的记忆矛盾"]
        elif phase == GamePhase.ROUND_COMPLETE:
            title = f"第 {display_round} 轮 · 余波"
            situation = recent or "这一轮的行动暂时告一段落，但没有人的目的因此停止。"
            objective = "整理本轮见闻，等待主持人揭开下一张事件卡。"
            suggestions = ["重读新增记忆", "比较本轮前后的角色位置", "确定下一轮最想核实的问题"]
        elif phase == GamePhase.DISCUSSION:
            title = "天将破晓 · 大堂公议"
            situation = recent or "终局钟声把仍在客栈的人召回大堂。每名密探将公开最后掌握的事实与怀疑。"
            objective = "听完众人的陈述，在对话档案中核对他们是否重复、隐瞒或改变说法；准备好后再进入投票。"
            suggestions = ["核对谁在复述二手情报", "比较终局陈述与此前对话", "区分个人秘密与杀人证据"]
        elif phase == GamePhase.VOTING:
            title = "天将破晓 · 最终指认"
            situation = recent or "封锁即将解除。每个人都只能依据自己亲历、听闻和记住的内容作出判断。"
            objective = "从你的记忆中找出最能形成因果链的证据，亲自投票指认凶手并写下理由。"
            suggestions = ["区分秘密与杀人动机", "核对作案手段、时机和痕迹", "不要把单一可疑物当作完整结论"]
        else:
            title = "案卷封存 · 天色已明"
            situation = recent or "终局已经揭晓，你的选择与记忆共同构成了这一次故事。"
            objective = "查看投票与计分结果，回顾哪些事实被揭开，哪些秘密被保住。"
            suggestions = ["比较你的判断与客观真相", "查看各人的得分来源", "从复盘中整理本局故事"]

        return {
            "title": title,
            "situation": situation,
            "objective": objective,
            "suggestions": suggestions,
            "recent_event": recent,
            "location_name": location_name,
        }

    def player_state(self, token: str) -> dict[str, Any]:
        """Return a deliberately scoped first-person view for the chosen role."""

        player_id = self.verify_player_token(token)
        actor = self.state.agents[player_id]
        participant = next(
            item for item in self.loaded.scenario["participants"]
            if item["id"] == player_id
        )
        global_event_types = {
            "event_card_selected", "public_fact", "public_intel", "world_trigger",
            "object_hint", "object_revealed", "health_changed",
            "life_state_changed", "object_dropped",
            "evidence_lost", "killer_revealed", "vote_cast",
            "bulletin_updated",
        }
        known_events = [
            self._player_event_dict(event) for event in self.state.events
            if player_id in event.actors
            or player_id in event.witnesses
            or event.event_type in global_event_types
        ]
        visible_agent_ids = {
            other.agent_id for other in self.state.agents.values()
            if other.location_id == actor.location_id
        }
        visible_agents: dict[str, dict[str, Any]] = {}
        for other_id in visible_agent_ids:
            other = self.state.agents[other_id]
            visible_agents[other_id] = {
                "agent_id": other.agent_id,
                "display_name": other.display_name,
                "public_role": other.public_role,
                "location_id": other.location_id,
                "life_state": other.life_state.value,
                "conditions": list(other.conditions),
                "is_self": other_id == player_id,
            }
        objects: dict[str, dict[str, Any]] = {}
        for object_id, item in self.state.objects.items():
            if item.holder_id == player_id:
                visible = item.to_dict(viewer_id=player_id, reveal_hidden=True)
            elif item.location_id == actor.location_id:
                visible = item.to_dict(viewer_id=player_id)
            else:
                visible = None
            if visible is not None:
                objects[object_id] = visible
        known_secrets = [
            secret.to_dict() for secret in self.state.secrets.values()
            if secret.owner_id == player_id or player_id in secret.exposed_to
        ]
        own_data = actor.to_dict(include_private=True)
        own_data.pop("strategic_plan", None)
        own_data.pop("plan_history", None)
        conversation_history = []
        for event in self.state.events:
            if event.event_type not in {"conversation", "final_discussion"}:
                continue
            if not (
                player_id in event.actors
                or player_id in event.witnesses
                or event.event_type == "final_discussion"
            ):
                continue
            speaker_id = str(event.payload.get("speaker_id") or (event.actors[0] if event.actors else ""))
            listener_id = str(event.payload.get("listener_id") or "")
            speaker = self.state.agents.get(speaker_id)
            listener = self.state.agents.get(listener_id)
            conversation_history.append({
                "event_id": event.event_id,
                "round_number": event.round_number,
                "speaker_id": speaker_id,
                "speaker_name": speaker.display_name if speaker else speaker_id,
                "listener_id": listener_id,
                "listener_name": listener.display_name if listener else ("大堂众人" if event.event_type == "final_discussion" else listener_id),
                "content": str(event.payload.get("content") or event.summary),
                "shared_claim": event.payload.get("shared_claim"),
                "overheard": player_id not in {speaker_id, listener_id},
                "final_discussion": event.event_type == "final_discussion",
            })
        may_choose_host_event = bool(
            self.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
            and not self.state.active_event_card
        )
        state = {
            "game_id": self.state.game_id,
            "title": self.loaded.scenario["title"],
            "premise": self.loaded.scenario["premise"],
            "round_number": self.state.round_number,
            "max_rounds": self.state.max_rounds,
            "action_step": self.state.action_step,
            "actions_per_round": self.state.actions_per_round,
            "phase": self.state.phase.value,
            "active_event_card": self.state.active_event_card,
            "locations": self.state.locations,
            "self": own_data,
            "visible_agents": visible_agents,
            "visible_objects": objects,
            "events": known_events,
            "notices": [
                notice.to_dict() for notice in self.state.notices
                if player_id in notice.seen_by
            ],
            "bulletin": {
                "has_unread": any(
                    player_id not in notice.seen_by for notice in self.state.notices
                ),
                "unread_count": sum(
                    1 for notice in self.state.notices if player_id not in notice.seen_by
                ),
                "location_id": "lobby",
            },
            "public_intel_history": list(self.state.public_intel_history),
            "opening_dispatch": dict(self.loaded.scenario.get("opening_dispatch", {})),
            "player_guide": dict(self.loaded.scenario.get("player_guide", {})),
            "background": {
                "display_name": participant.get("display_name", player_id),
                "public_role": participant.get("public_role", ""),
                "story": list(participant.get("background_story", [])),
                "opening_hook": participant.get("opening_hook", ""),
                "background_memories": list(participant.get("background_memories", [])),
                "goals": list(participant.get("goals", [])),
                "decision_rules": list(participant.get("decision_rules", [])),
                "private_facts": list(participant.get("private_facts", [])),
                "abilities": abilities_for(self.state, player_id),
                "timeline": list(
                    self.state.flags.get("character_timelines", {}).get(player_id, [])
                ),
            },
            "known_secrets": known_secrets,
            "conversations": conversation_history,
            "story_guide": self._build_story_guide(player_id, known_events),
            "available_actions": self.available_player_actions(player_id),
            "host_options": {
                "cards": self.card_suggestions(),
                "quiet": self.empty_event_option(),
                "intel": self.intel_suggestions(),
            } if may_choose_host_event else None,
            "requires_vote": self.state.phase == GamePhase.VOTING,
            "final_questions": (
                self.final_questions_for(player_id)
                if self.state.phase == GamePhase.VOTING else []
            ),
            "can_open_voting": self.state.phase == GamePhase.DISCUSSION,
            "voting_candidates": [
                {"id": other.agent_id, "name": other.display_name, "role": other.public_role}
                for other in self.state.agents.values()
                if other.agent_id != player_id and other.life_state != LifeState.DEAD
            ] if self.state.phase == GamePhase.VOTING else [],
        }
        if self.state.phase == GamePhase.FINISHED:
            state["voting_result"] = dict(self.state.flags.get("voting_result", {}))
            state["scoreboard"] = self.scoreboard()
        return state

    @staticmethod
    def _player_event_dict(event: EventRecord) -> dict[str, Any]:
        data = event.to_dict()
        data["payload"] = {
            key: value for key, value in data.get("payload", {}).items()
            if not str(key).startswith("_host_")
        }
        return data

    def available_player_actions(self, player_id: str) -> dict[str, Any]:
        actor = self.state.agents[player_id]
        special_actions = abilities_for(self.state, player_id)
        can_submit = bool(
            self.state.active_event_card
            and self.state.phase in {GamePhase.READY, GamePhase.PLAYER_TURN}
        )
        people = [
            {"id": other.agent_id, "name": other.display_name, "life_state": other.life_state.value}
            for other in self.state.agents.values()
            if other.agent_id != player_id
            and other.location_id == actor.location_id
            and other.life_state != LifeState.DEAD
        ]
        inventory = [
            {"id": object_id, "name": self.state.objects[object_id].name}
            for object_id in actor.inventory if object_id in self.state.objects
        ]
        shareable_memories = [
            {
                "id": belief.belief_id,
                "claim": belief.claim,
                "source": belief.source,
                "confidence": belief.confidence,
            }
            for belief in actor.beliefs[-40:]
            if belief.source != "凶手记忆"
        ]
        action_types = [
            "move", "investigate", "talk", "transfer",
        ]
        for ability in special_actions:
            action_type = str(ability["action_type"])
            if action_type in {"poison", "treat"} and action_type not in action_types:
                action_types.append(action_type)
        already_poisoned = player_id in self.state.flags.get(
            "poisons_by_round", {}
        ).get(str(self.state.round_number + 1), [])
        return {
            "can_submit": can_submit,
            "can_act": actor.can_act,
            "can_end_round": can_submit,
            "can_auto_host": bool(
                self.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
                and not self.state.active_event_card
            ),
            "can_post_notice": bool(
                actor.location_id == "lobby"
                and self.state.phase in {
                    GamePhase.READY, GamePhase.PLAYER_TURN,
                    GamePhase.INTERVENTION, GamePhase.DISCUSSION,
                }
            ),
            "round_number": min(self.state.round_number + 1, self.state.max_rounds),
            "action_step": self.state.action_step + 1,
            "major_actions_used": self.state.action_step,
            "major_actions_remaining": max(
                0, self.state.actions_per_round - self.state.action_step
            ),
            "free_action_types": ["move", "talk"],
            "moves": [
                {"id": location_id, "name": self.state.locations[location_id]["name"]}
                for location_id in self.state.locations[actor.location_id].get("connections", [])
            ],
            "people": people,
            "inventory": inventory,
            "shareable_memories": shareable_memories,
            "can_investigate": bool(
                self.state.locations[actor.location_id].get("searchable")
                and actor.life_state == LifeState.ALIVE
            ),
            "can_poison_this_round": not already_poisoned,
            "special_actions": special_actions,
            "types": action_types,
        }

    def build_player_intent(self, token: str, raw: dict[str, Any]) -> ActionIntent:
        player_id = self.verify_player_token(token)
        if self.state.phase not in {GamePhase.READY, GamePhase.PLAYER_TURN}:
            raise ValueError("当前不是角色行动阶段")
        try:
            action_type = ActionType(str(raw.get("action_type", "")))
        except ValueError as error:
            raise ValueError("未知的行动类型") from error
        intent = ActionIntent(
            actor_id=player_id,
            action_type=action_type,
            target_id=str(raw.get("target_id") or "") or None,
            location_id=str(raw.get("location_id") or "") or None,
            object_id=str(raw.get("object_id") or "") or None,
            content=str(raw.get("content") or "")[:200],
            reason=str(raw.get("reason") or "玩家亲自决定")[:200],
            metadata={"planner_source": "player"},
        )
        if not action_is_authorized(self.state, intent):
            raise ValueError("你的角色没有执行这项下毒或治疗行动的能力")
        selected_ability_id = str(raw.get("ability_id") or "")
        if selected_ability_id:
            ability = apply_ability(self.state, intent, selected_ability_id)
            if not ability:
                raise ValueError("这项专属技能不属于你的角色，或不能用于当前行动")
        elif action_type in {ActionType.POISON, ActionType.TREAT}:
            apply_ability(self.state, intent)
        share_belief_id = str(raw.get("share_belief_id") or "")
        if share_belief_id:
            actor = self.state.agents[player_id]
            if not any(belief.belief_id == share_belief_id for belief in actor.beliefs):
                raise ValueError("只能交换自己记忆中真实存在的情报")
            intent.metadata["share_belief_id"] = share_belief_id
        if action_type == ActionType.TALK:
            lowered = intent.content.lower()
            display_words = ("出示", "展示", "给你看", "让你看", "验看")
            if any(word in lowered for word in display_words):
                actor = self.state.agents[player_id]
                named_item = next((
                    self.state.objects[object_id]
                    for object_id in actor.inventory
                    if object_id in self.state.objects
                    and self.state.objects[object_id].name in intent.content
                ), None)
                if named_item:
                    intent.metadata["display_object_id"] = named_item.object_id
                    intent.metadata["item_disposition"] = "show"
        reason = self.engine._validate_intent(self.state, intent, set())
        if reason:
            raise ValueError(f"当前无法执行该行动：{reason}")
        return intent

    def scoreboard(self) -> list[dict[str, Any]]:
        return [
            {
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "score": agent.score,
                "breakdown": list(agent.score_breakdown),
                "models": sorted({
                    str(item.get("provider_name", "heuristic"))
                    for item in self.state.model_usage
                    if item.get("agent_id") == agent.agent_id
                }),
                "answer_results": list(
                    self.state.final_submissions.get(
                        agent.agent_id, {}
                    ).get("answer_results", [])
                ),
            }
            for agent in sorted(
                self.state.agents.values(), key=lambda item: (-item.score, item.agent_id)
            )
        ]

    def card_suggestions(self) -> list[dict[str, Any]]:
        if not self.state.suggested_event_cards:
            cards = self.director.suggest(self.state)
            self.state.suggested_event_cards = [
                card.to_dict(reveal_hidden=True) for card in cards
            ]
            for card in cards:
                if card.card_id not in self.state.seen_event_cards:
                    self.state.seen_event_cards.append(card.card_id)
            self.save()
        return [
            EventCard(**card).to_dict()
            for card in self.state.suggested_event_cards
        ]

    def empty_event_option(self) -> dict[str, Any]:
        return self.director.quiet_card(self.state).to_dict()

    def intel_suggestions(self) -> list[dict[str, Any]]:
        if self.state.active_public_intel:
            return []
        if not self.state.suggested_public_intel:
            available = [
                dict(item)
                for item in self.loaded.scenario.get("public_intel", [])
                if item["id"] not in self.state.used_public_intel
            ]
            if not available:
                return []
            count = min(3, len(available))
            self.state.suggested_public_intel = self.random.sample(available, count)
            self.save()
        return [dict(item) for item in self.state.suggested_public_intel]

    def post_notice(
        self,
        content: str,
        *,
        display_author: str = "临时掌柜",
        authority: str = "host",
        publisher: str = "host",
        location_id: str | None = None,
    ) -> Notice:
        if self.state.phase not in {
            GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE, GamePhase.READY,
            GamePhase.PLAYER_TURN, GamePhase.DISCUSSION,
        }:
            raise ValueError("Notices can only be posted between rounds")
        content = content.strip()
        if not content:
            raise ValueError("Notice content cannot be empty")
        if len(content) > 500:
            raise ValueError("Notice content cannot exceed 500 characters")
        location_id = location_id or self.loaded.world.get("default_notice_location", "lobby")
        if location_id not in self.state.locations:
            raise ValueError("Unknown notice location")

        self._notice_sequence += 1
        present = self.state.occupants(location_id, include_dead=False)
        is_host_publication = authority == "host"
        readers = (
            [agent_id for agent_id, agent in self.state.agents.items() if agent.can_act]
            if is_host_publication
            else present
        )
        notice = Notice(
            notice_id=f"notice-{self._notice_sequence:04d}",
            round_number=self.state.round_number,
            publisher=publisher,
            display_author=display_author,
            content=content,
            location_id=location_id,
            authority=authority,
            seen_by=list(readers),
        )
        self.state.notices.append(notice)
        self._add_notice_beliefs(notice, readers)
        event = self._event(
            "notice_posted",
            f"{display_author}在{self.state.locations[location_id]['name']}公告板发布：{content}",
            public=True,
            location_id=location_id,
            witnesses=readers,
            payload={
                "notice_id": notice.notice_id,
                "universally_known": is_host_publication,
            },
        )
        self.state.events.append(event)
        if not is_host_publication:
            self._signal_bulletin_update(notice, present)
        self.save()
        return notice

    def post_player_notice(self, token: str, content: str) -> Notice:
        player_id = self.verify_player_token(token)
        actor = self.state.agents[player_id]
        if actor.location_id != "lobby":
            raise ValueError("公告栏设在客栈大堂，必须亲自到场才能张贴")
        return self.post_notice(
            content,
            display_author=actor.display_name,
            authority="player",
            publisher=player_id,
            location_id="lobby",
        )

    def _materialize_agent_notices(self, events: list[EventRecord]) -> None:
        for event in events:
            if event.event_type != "notice_posted" or event.payload.get("notice_id"):
                continue
            publisher = str(event.payload.get("publisher") or (event.actors[0] if event.actors else ""))
            content = str(event.payload.get("content") or "").strip()
            if not publisher or not content:
                continue
            self._notice_sequence += 1
            notice = Notice(
                notice_id=f"notice-{self._notice_sequence:04d}",
                round_number=event.round_number,
                publisher=publisher,
                display_author=str(event.payload.get("display_author") or publisher),
                content=content,
                location_id="lobby",
                authority="agent",
                seen_by=list(event.witnesses),
            )
            self.state.notices.append(notice)
            event.payload["notice_id"] = notice.notice_id
            self._add_notice_beliefs(notice, notice.seen_by)
            self._signal_bulletin_update(notice, notice.seen_by)

    def _signal_bulletin_update(self, notice: Notice, readers: list[str]) -> None:
        """Tell everyone a post exists without leaking its text outside the lobby."""

        all_agent_ids = list(self.state.agents)
        signal = self._event(
            "bulletin_updated",
            "客栈大堂的公告栏出现了新张贴；要知道原文，必须回到大堂查看。",
            public=True,
            location_id="lobby",
            witnesses=all_agent_ids,
            payload={"notice_id": notice.notice_id, "content_hidden_until_read": True},
        )
        self.state.events.append(signal)
        self.state.flags["bulletin_last_notice_id"] = notice.notice_id
        for agent_id, agent in self.state.agents.items():
            if agent_id in readers:
                continue
            if any(belief.source == signal.event_id for belief in agent.beliefs):
                continue
            agent.beliefs.append(Belief(
                belief_id=f"belief-{agent_id}-{signal.event_id}",
                claim="大堂公告栏有一条尚未读取的新张贴。",
                source=signal.event_id,
                confidence=1.0,
                stance="observed",
                learned_round=self.state.round_number,
            ))

    def select_event_card(self, card_id: str) -> list[EventRecord]:
        if self.state.active_event_card:
            raise ValueError("An event card has already been selected for the upcoming round")
        if not self.state.suggested_event_cards:
            self.card_suggestions()
        suggested = {
            raw["card_id"]: EventCard(**raw)
            for raw in self.state.suggested_event_cards
        }
        quiet_card = self.director.quiet_card(self.state)
        if card_id == quiet_card.card_id:
            suggested[card_id] = quiet_card
        if card_id not in suggested:
            raise ValueError("Event card is not one of this round's three suggestions")
        self.director.cards[card_id] = suggested[card_id]
        events = self.director.apply(self.state, card_id)
        self.state.suggested_event_cards = []
        self._distribute_public_events(events)
        self.save()
        return events

    def publish_public_intel(self, intel_id: str) -> tuple[dict[str, Any], EventRecord]:
        if self.state.phase not in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE, GamePhase.READY}:
            raise ValueError("Public intel can only be released between rounds")
        if self.state.active_public_intel:
            raise ValueError("One public intel item has already been released this round")
        suggestions = {item["id"]: item for item in self.intel_suggestions()}
        if intel_id not in suggestions:
            raise ValueError("Public intel is not one of this round's suggestions")
        intel = dict(suggestions[intel_id])
        intel["round_number"] = self.state.round_number
        self.state.active_public_intel = intel_id
        self.state.used_public_intel.append(intel_id)
        self.state.public_intel_history.append(intel)
        self.state.suggested_public_intel = []
        event = self._event(
            "public_intel",
            f"公开情报“{intel['title']}”（{intel['source']}）：{intel['claim']}",
            public=True,
            payload={
                "intel_id": intel_id,
                "title": intel["title"],
                "claim": intel["claim"],
                "source": intel["source"],
                "reliability": float(intel.get("reliability", 0.75)),
            },
        )
        self.state.events.append(event)
        confidence = max(0.0, min(1.0, float(intel.get("reliability", 0.75))))
        all_agent_ids = list(self.state.agents)
        for agent in self.state.agents.values():
            if not agent.can_act:
                continue
            agent.beliefs.append(Belief(
                belief_id=f"belief-{agent.agent_id}-{event.event_id}",
                claim=f"公开情报称：{intel['claim']}",
                source=event.event_id,
                confidence=confidence,
                stance="reported",
                learned_round=self.state.round_number,
                shared_with=[agent_id for agent_id in all_agent_ids if agent_id != agent.agent_id],
            ))
        self.save()
        return intel, event

    def advance_round(
        self,
        intents: list[ActionIntent] | None = None,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> RoundResult:
        if self.state.player_agent_id:
            raise ValueError("角色代入局必须由玩家逐次提交行动，导演不能替角色推进整轮")
        if self.state.phase in {GamePhase.FINISHED, GamePhase.VOTING}:
            raise ValueError("Game is already finished")
        if not self.state.active_event_card:
            raise ValueError("Select one of the suggested event cards before advancing")
        all_events: list[EventRecord] = []
        all_rejected: list[dict[str, Any]] = []
        explicit_intents = intents
        resolved_round = self.state.round_number + 1
        active_at_start = sum(1 for agent in self.state.agents.values() if agent.can_act)

        def report_round_progress(update: dict[str, Any]) -> None:
            if progress_callback is None:
                return
            enriched = dict(update)
            phase_index = self.state.action_step
            enriched["action_step"] = phase_index + 1
            enriched["completed"] = phase_index * active_at_start + int(update.get("completed", 0))
            enriched["total"] = self.state.actions_per_round * active_at_start
            progress_callback(enriched)

        while self.state.round_number < resolved_round:
            phase_intents = explicit_intents
            explicit_intents = None
            result = self._advance_action_phase(
                player_intent=None,
                override_intents=phase_intents,
                progress_callback=report_round_progress,
            )
            all_events.extend(result.events)
            all_rejected.extend(result.rejected_intents)
        result = RoundResult(
            resolved_round,
            all_events,
            all_rejected,
            self.state,
            self.state.actions_per_round,
        )
        self.save(round_result=result)
        if self.state.phase == GamePhase.FINISHED:
            self.save_recap()
        return result

    def advance_player_action(
        self,
        token: str,
        raw_intent: dict[str, Any],
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> RoundResult:
        if not self.state.player_agent_id:
            raise ValueError("这不是角色代入局")
        player_intent = self.build_player_intent(token, raw_intent)
        self._record_model_usage(
            player_intent.actor_id,
            stage="action",
            actual_source="player_input",
            provider_name="human",
        )
        if player_intent.action_type in {ActionType.MOVE, ActionType.TALK}:
            result = self.engine.resolve_free_action(self.state, player_intent)
            if player_intent.action_type == ActionType.TALK and result.events:
                outgoing = result.events[0]
                reply_to_event_id = str(raw_intent.get("reply_to_event_id") or "")
                if reply_to_event_id:
                    outgoing.payload["reply_to_event_id"] = reply_to_event_id
                    outgoing.payload["is_player_reply"] = True
                    if self.state.conversations:
                        self.state.conversations[-1].reply_to_event_id = reply_to_event_id
                else:
                    outgoing.payload["awaiting_reply"] = True
                    if progress_callback:
                        target = self.state.agents[player_intent.target_id or ""]
                        progress_callback({
                            "stage": "conversation_reply",
                            "agent_id": target.agent_id,
                            "display_name": target.display_name,
                            "status": "thinking",
                            "completed": 0,
                            "total": 1,
                        })
                    responder = getattr(self.planner, "respond_to_player", None)
                    try:
                        response = responder(
                            self.state,
                            self.loaded.scenario,
                            player_intent.target_id,
                            player_intent.actor_id,
                            player_intent.content,
                        ) if responder else None
                    except Exception:
                        response = None
                    if not response:
                        response = HeuristicIntentPlanner(seed=0).respond_to_player(
                            self.state,
                            self.loaded.scenario,
                            player_intent.target_id,
                            player_intent.actor_id,
                            player_intent.content,
                        )
                    reply_intent = ActionIntent(
                        actor_id=player_intent.target_id or "",
                        action_type=ActionType.TALK,
                        target_id=player_intent.actor_id,
                        content=str(response.get("content") or "我听见了，但现在还不能作答。")[:200],
                        reason="回应玩家的当面交谈",
                        metadata={"planner_source": "conversation_reply"},
                    )
                    shared_belief_id = str(response.get("share_belief_id") or "")
                    if shared_belief_id:
                        reply_intent.metadata["share_belief_id"] = shared_belief_id
                    for key in ("display_object_id", "item_disposition", "_host_item_disposition"):
                        value = response.get(key)
                        if value:
                            reply_intent.metadata[key] = value
                    reply_result = self.engine.resolve_free_action(self.state, reply_intent)
                    if reply_result.events:
                        reply = reply_result.events[0]
                        reply.payload["is_reply"] = True
                        reply.payload["reply_to_event_id"] = outgoing.event_id
                        if self.state.conversations:
                            self.state.conversations[-1].reply_to_event_id = outgoing.event_id
                        result.events.extend(reply_result.events)
                    if progress_callback:
                        target = self.state.agents[player_intent.target_id or ""]
                        progress_callback({
                            "stage": "conversation_reply",
                            "agent_id": target.agent_id,
                            "display_name": target.display_name,
                            "status": "completed",
                            "completed": 1,
                            "total": 1,
                        })
            self._update_beliefs_from_round_events(result.events)
            self._apply_scoring_from_events(result.events)
            self._deliver_unseen_notices()
        else:
            result = self._advance_action_phase(
                player_intent=player_intent,
                progress_callback=progress_callback,
            )
        self.save(round_result=result)
        return result

    def end_player_round(
        self,
        token: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> RoundResult:
        """Let the player stop exploring and resolve every unused major phase."""

        player_id = self.verify_player_token(token)
        if self.state.phase not in {GamePhase.READY, GamePhase.PLAYER_TURN}:
            raise ValueError("当前没有可以结束的行动轮")
        if not self.state.active_event_card:
            raise ValueError("主持人需要先展开本轮事件")
        starting_round = self.state.round_number
        all_events: list[EventRecord] = []
        rejected: list[dict[str, Any]] = []
        last_step = self.state.action_step
        while self.state.round_number == starting_round:
            player = self.state.agents[player_id]
            wait_intent = ActionIntent(
                actor_id=player_id,
                action_type=ActionType.WAIT,
                content="玩家选择结束本轮",
                reason="玩家已完成自由探索",
                metadata={"planner_source": "player", "end_round": True},
            ) if player.can_act else None
            phase_result = self._advance_action_phase(
                player_intent=wait_intent,
                progress_callback=progress_callback,
            )
            all_events.extend(phase_result.events)
            rejected.extend(phase_result.rejected_intents)
            last_step = phase_result.action_step
        result = RoundResult(
            self.state.round_number,
            all_events,
            rejected,
            self.state,
            last_step,
        )
        self.save(round_result=result)
        return result

    def choose_player_host_event(
        self,
        token: str,
        card_id: str,
        *,
        intel_id: str | None = None,
    ) -> dict[str, Any]:
        """Let the role-seat player explicitly make the host's between-round choice."""

        self.verify_player_token(token)
        if self.state.phase not in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}:
            raise ValueError("当前还不能展开下一轮")
        if self.state.active_event_card:
            raise ValueError("本轮事件已经展开")

        card_id = str(card_id).strip()
        if not card_id:
            raise ValueError("请先选择一张事件卡，或选择本轮无事件")
        published_intel: dict[str, Any] | None = None
        intel_event: EventRecord | None = None
        if intel_id:
            published_intel, intel_event = self.publish_public_intel(str(intel_id))
        card_options = [*self.card_suggestions(), self.empty_event_option()]
        picked_card = next(
            (item for item in card_options if item["card_id"] == card_id),
            None,
        )
        if picked_card is None:
            raise ValueError("所选事件不在本轮候选中")
        card_events = self.select_event_card(card_id)
        return {
            "intel": published_intel,
            "intel_event": intel_event.to_dict() if intel_event else None,
            "card": picked_card,
            "events": [event.to_dict() for event in card_events],
        }

    def auto_host_next_round(self, token: str) -> dict[str, Any]:
        """Legacy deterministic fallback; the browser now always asks the host."""

        self.verify_player_token(token)
        card = self.card_suggestions()[0]
        return self.choose_player_host_event(token, card["card_id"])

    def _advance_action_phase(
        self,
        *,
        player_intent: ActionIntent | None,
        override_intents: list[ActionIntent] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> RoundResult:
        if not self.state.active_event_card:
            raise ValueError("Select one of the suggested event cards before advancing")
        trigger_events: list[EventRecord] = []
        if self.state.action_step == 0:
            trigger_events = self.trigger_resolver.apply_due(self.state)
            self._distribute_public_events(trigger_events)
        free_events: list[EventRecord] = []
        free_rejections: list[dict[str, Any]] = []
        if override_intents is not None:
            intents = list(override_intents)
        else:
            excluded = {self.state.player_agent_id} if self.state.player_agent_id else set()
            actor_ids = [
                agent_id for agent_id, agent in self.state.agents.items()
                if agent.can_act and agent_id not in excluded
            ]
            current = self._plan_actor_intents(
                actor_ids,
                progress_callback=progress_callback,
                force_major=False,
            )
            major_by_actor: dict[str, ActionIntent] = {}
            # AI navigation and conversation are free just like the human
            # player's. The bound prevents an autonomous conversation loop; on
            # the final prelude, repeated talk is redirected toward unexplored
            # space so a crowded room cannot starve investigation forever.
            for free_pass in range(3):
                if free_pass == 2 or (
                    free_pass == 0 and not self.state.player_agent_id
                ):
                    current = [
                        self._exploration_intent(intent.actor_id) or intent
                        if intent.action_type == ActionType.TALK
                        else intent
                        for intent in current
                    ]
                free_actor_ids: list[str] = []
                for intent in current:
                    if intent.actor_id in major_by_actor:
                        continue
                    if intent.action_type not in {ActionType.MOVE, ActionType.TALK}:
                        major_by_actor[intent.actor_id] = intent
                        continue
                    free_result = self.engine.resolve_free_action(self.state, intent)
                    free_events.extend(free_result.events)
                    free_rejections.extend(free_result.rejected_intents)
                    if free_result.events:
                        self._update_beliefs_from_round_events(free_result.events)
                        self._apply_scoring_from_events(free_result.events)
                        self._deliver_unseen_notices()
                    free_actor_ids.append(intent.actor_id)
                if not free_actor_ids:
                    break
                current = self._plan_actor_intents(
                    free_actor_ids,
                    progress_callback=None,
                    force_major=False,
                )
            for intent in current:
                if intent.actor_id in major_by_actor:
                    continue
                if intent.action_type in {ActionType.MOVE, ActionType.TALK}:
                    fallback = HeuristicIntentPlanner(seed=0).plan(
                        self.state,
                        self.loaded.scenario,
                        actor_ids=[intent.actor_id],
                        force_major=True,
                    )
                    intent = fallback[0] if fallback else ActionIntent(
                        actor_id=intent.actor_id,
                        action_type=ActionType.WAIT,
                        reason="自由行动预算已经结束，留在原地观察",
                    )
                major_by_actor[intent.actor_id] = intent
            intents = [
                major_by_actor[agent_id]
                for agent_id in actor_ids if agent_id in major_by_actor
            ]
        for index, intent in enumerate(intents):
            if not action_is_authorized(self.state, intent):
                intents[index] = ActionIntent(
                    actor_id=intent.actor_id,
                    action_type=ActionType.WAIT,
                    reason="当前人物没有执行该冲突或治疗行动的能力",
                    metadata={"planner_source": "ability_guard"},
                )
            else:
                apply_ability(self.state, intent)
        if player_intent is not None:
            intents.append(player_intent)
        result = self.engine.resolve_action_phase(self.state, intents)
        major_events = list(result.events)
        result.rejected_intents[0:0] = free_rejections
        if self.state.player_agent_id:
            for event in [*free_events, *result.events]:
                if (
                    event.event_type == "conversation"
                    and event.payload.get("listener_id") == self.state.player_agent_id
                    and event.payload.get("speaker_id") != self.state.player_agent_id
                ):
                    event.payload["player_reply_invited"] = True
        result.events[0:0] = [*trigger_events, *free_events]
        self._materialize_agent_notices(result.events)
        self._commit_strategic_plans(intents, major_events)
        self._update_beliefs_from_round_events(major_events)
        self._apply_scoring_from_events(major_events)
        self._deliver_unseen_notices()
        if self.state.action_step == 0:
            self.state.active_event_card = None
            self.state.active_public_intel = None
            if self.state.phase == GamePhase.ROUND_COMPLETE:
                discussion_events = self._prepare_round_discussion(
                    progress_callback=progress_callback,
                )
                result.events.extend(discussion_events)
                self.state.phase = GamePhase.INTERVENTION
            elif self.state.phase == GamePhase.DISCUSSION:
                discussion_events = self._prepare_round_discussion(
                    progress_callback=progress_callback,
                )
                result.events.extend(discussion_events)
                discussion_events = self._prepare_final_discussion()
                result.events.extend(discussion_events)
                if not self.state.player_agent_id:
                    self.state.phase = GamePhase.VOTING
                    self._run_final_vote(progress_callback=progress_callback)
            elif self.state.phase == GamePhase.VOTING and not self.state.player_agent_id:
                self._run_final_vote(progress_callback=progress_callback)
        self.save(round_result=result)
        if self.state.phase == GamePhase.FINISHED:
            self.save_recap()
        return result

    def _prepare_round_discussion(
        self,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[EventRecord]:
        """Gather active characters and run two grounded discussion waves."""

        round_number = self.state.round_number
        completed_rounds = self.state.flags.setdefault(
            "completed_round_discussions", []
        )
        if round_number in completed_rounds:
            return []
        completed_rounds.append(round_number)

        total_limit = 100
        used = int(self.state.flags.get("round_discussion_turns", 0))
        remaining = max(0, total_limit - used)
        active_ids = [
            agent_id for agent_id, agent in self.state.agents.items()
            if agent.can_act
        ]
        if len(active_ids) < 2 or remaining <= 0:
            return []

        events: list[EventRecord] = []
        for agent_id in active_ids:
            agent = self.state.agents[agent_id]
            if agent.location_id == "lobby":
                continue
            origin_id = agent.location_id
            agent.location_id = "lobby"
            agent.location_state["current_area"] = "lobby"
            move = self._event(
                "move",
                f"第{round_number}轮讨论开始，{agent.display_name}返回客栈大堂。",
                public=False,
                location_id="lobby",
                witnesses=list(active_ids),
                payload={
                    "origin_id": origin_id,
                    "destination_id": "lobby",
                    "round_discussion_gathering": True,
                    "free_action": True,
                },
            )
            move.actors = [agent_id]
            self.state.events.append(move)
            events.append(move)

        start = self._event(
            "round_discussion_started",
            f"第{round_number}轮行动结束，仍能行动的角色回到大堂集中讨论。",
            public=True,
            location_id="lobby",
            witnesses=list(active_ids),
            payload={
                "round_discussion": True,
                "dialogue_limit": total_limit,
                "dialogue_used_before": used,
            },
        )
        self.state.events.append(start)
        events.append(start)

        responder = getattr(self.planner, "respond_to_player", None)
        if not callable(responder):
            responder = HeuristicIntentPlanner(seed=round_number).respond_to_player
        speaker_ids = [
            agent_id for agent_id in active_ids
            if agent_id != self.state.player_agent_id
        ]
        turn_budget = min(remaining, len(speaker_ids) * 2)
        previous_wave: dict[str, tuple[str, str]] = {}
        turns_completed = 0

        for wave in range(2):
            wave_speakers = speaker_ids[
                :max(0, min(len(speaker_ids), turn_budget - turns_completed))
            ]
            if not wave_speakers:
                break
            prompts: dict[str, tuple[str, str]] = {}
            for index, speaker_id in enumerate(wave_speakers):
                listener_id = active_ids[
                    (active_ids.index(speaker_id) + 1 + wave) % len(active_ids)
                ]
                if listener_id == speaker_id:
                    listener_id = active_ids[
                        (active_ids.index(speaker_id) + 1) % len(active_ids)
                    ]
                if wave == 0:
                    message = (
                        f"第{round_number}轮行动已经结束。请根据你亲历的行动、"
                        "新发现和仍未解释的矛盾，向在场众人提出一个具体判断或问题。"
                    )
                else:
                    incoming = previous_wave.get(listener_id)
                    if incoming:
                        listener_id, message = incoming
                    else:
                        message = (
                            "有人已经提出了本轮判断。请回应其中与你记忆相符或冲突的一点，"
                            "不要只复述自己的旧信息。"
                        )
                prompts[speaker_id] = (listener_id, message)

            replies: dict[str, dict[str, Any]] = {}
            with ThreadPoolExecutor(
                max_workers=min(6, len(prompts)),
                thread_name_prefix="round-discussion",
            ) as executor:
                futures = {
                    executor.submit(
                        responder,
                        self.state,
                        self.loaded.scenario,
                        speaker_id,
                        listener_id,
                        message,
                    ): speaker_id
                    for speaker_id, (listener_id, message) in prompts.items()
                }
                for future in as_completed(futures):
                    speaker_id = futures[future]
                    try:
                        replies[speaker_id] = dict(future.result())
                    except Exception as error:
                        replies[speaker_id] = {
                            "content": "这一轮的信息仍有矛盾，我需要先核对时辰与来源。",
                            "share_belief_id": None,
                            "_model_source": "heuristic_fallback",
                            "_model_error": type(error).__name__,
                        }

            for speaker_id in wave_speakers:
                if turns_completed >= turn_budget:
                    break
                listener_id, _ = prompts[speaker_id]
                reply = replies[speaker_id]
                content = str(reply.get("content") or "").strip()[:180]
                if not content:
                    continue
                metadata: dict[str, Any] = {}
                for source_key, target_key in (
                    ("share_belief_id", "share_belief_id"),
                    ("display_object_id", "display_object_id"),
                    ("item_disposition", "item_disposition"),
                ):
                    if reply.get(source_key):
                        metadata[target_key] = reply[source_key]
                intent = ActionIntent(
                    actor_id=speaker_id,
                    action_type=ActionType.TALK,
                    target_id=listener_id,
                    content=content,
                    reason="轮末集中讨论中回应他人的线索与推理",
                    metadata=metadata,
                )
                talk_result = self.engine.resolve_free_action(self.state, intent)
                if not talk_result.events:
                    continue
                event = talk_result.events[0]
                source = str(reply.get("_model_source") or "heuristic_fallback")
                event.payload.update({
                    "round_discussion": True,
                    "discussion_wave": wave + 1,
                    "planner_source": source,
                    "model_error": reply.get("_model_error"),
                })
                self._update_beliefs_from_round_events([event])
                self._apply_scoring_from_events([event])
                events.append(event)
                previous_wave[speaker_id] = (speaker_id, content)
                turns_completed += 1
                self._record_model_usage(
                    speaker_id,
                    stage="round_discussion",
                    actual_source=source,
                    provider_name=str(
                        getattr(self.planner, "provider_name", "heuristic")
                    ),
                )
                if progress_callback:
                    progress_callback({
                        "stage": "round_discussion",
                        "agent_id": speaker_id,
                        "display_name": self.state.agents[speaker_id].display_name,
                        "status": "completed",
                        "completed": turns_completed,
                        "total": turn_budget,
                        "source": source,
                    })

        self.state.flags["round_discussion_turns"] = used + turns_completed
        end = self._event(
            "round_discussion_ended",
            (
                f"第{round_number}轮集中讨论结束，共形成{turns_completed}次发言；"
                f"全局讨论额度已使用{used + turns_completed}/{total_limit}。"
            ),
            public=True,
            location_id="lobby",
            witnesses=list(active_ids),
            payload={
                "round_discussion": True,
                "turns": turns_completed,
                "dialogue_used": used + turns_completed,
                "dialogue_limit": total_limit,
            },
        )
        self.state.events.append(end)
        events.append(end)
        self._deliver_unseen_notices()
        return events

    def _exploration_intent(self, agent_id: str) -> ActionIntent | None:
        """Route an idle conversational loop toward a still-unknown clue."""

        agent = self.state.agents.get(agent_id)
        if agent is None:
            return None
        targets: list[tuple[int, int, str, list[str]]] = []
        for location_id, location in self.state.locations.items():
            if not location.get("searchable"):
                continue
            unknown_count = sum(
                1 for item in self.state.objects.values()
                if item.location_id == location_id
                and agent_id not in item.discovered_by
            )
            if not unknown_count:
                continue
            route = HeuristicIntentPlanner._shortest_path(
                self.state,
                agent.location_id,
                location_id,
            )
            if not route:
                continue
            targets.append((len(route), -unknown_count, location_id, route))
        if not targets:
            return None
        targets.sort(key=lambda item: item[:3])
        nearest_distance = targets[0][0]
        nearest = [item for item in targets if item[0] == nearest_distance]
        agent_order = list(self.state.agents).index(agent_id)
        _, _, destination, route = nearest[agent_order % len(nearest)]
        if len(route) == 1:
            return ActionIntent(
                actor_id=agent_id,
                action_type=ActionType.INVESTIGATE,
                location_id=destination,
                reason="交谈告一段落，当前地点仍有未检查线索",
            )
        return ActionIntent(
            actor_id=agent_id,
            action_type=ActionType.MOVE,
            location_id=route[1],
            reason="交谈告一段落，前往仍有未发现线索的地点",
        )

    def _plan_actor_intents(
        self,
        actor_ids: list[str],
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None,
        force_major: bool,
    ) -> list[ActionIntent]:
        if not actor_ids:
            return []
        actor_set = set(actor_ids)
        try:
            intents = self.planner.plan(
                self.state,
                self.loaded.scenario,
                progress_callback=progress_callback,
                actor_ids=actor_ids,
                force_major=force_major,
            )
        except TypeError:
            intents = [
                intent for intent in self.planner.plan(
                    self.state,
                    self.loaded.scenario,
                    progress_callback=progress_callback,
                )
                if intent.actor_id in actor_set
            ]
        if force_major:
            replacements = {
                intent.actor_id
                for intent in intents
                if intent.action_type in {ActionType.MOVE, ActionType.TALK}
            }
            if replacements:
                fallback = HeuristicIntentPlanner(seed=0).plan(
                    self.state,
                    self.loaded.scenario,
                    actor_ids=sorted(replacements),
                    force_major=True,
                )
                fallback_by_actor = {intent.actor_id: intent for intent in fallback}
                intents = [
                    fallback_by_actor.get(intent.actor_id, intent)
                    if intent.actor_id in replacements else intent
                    for intent in intents
                ]
        for intent in intents:
            source = str(intent.metadata.get("planner_source") or "")
            if not source:
                source = (
                    "heuristic"
                    if self.planner.__class__.__name__ == "HeuristicIntentPlanner"
                    else "llm"
                )
            self._record_model_usage(
                intent.actor_id,
                stage="action",
                actual_source=source,
                succeeded=source not in {"heuristic_fallback", "ability_guard"},
            )
        return intents

    def build_recap(self, *, allow_incomplete: bool = False) -> dict[str, Any]:
        if self.state.phase != GamePhase.FINISHED and not allow_incomplete:
            raise ValueError("Recap is available after the final round")
        return self.recap_builder.build(self.loaded, self.state)

    def build_action_timeline(self) -> dict[str, Any]:
        """Return an analysis-friendly chronology without secret poison attempts."""

        max_rounds = self.state.max_rounds
        actions_per_round = self.state.actions_per_round
        title = f"{max_rounds}轮{max_rounds * actions_per_round}次主要行动事件线"
        rounds: list[dict[str, Any]] = []
        for round_number in range(1, max_rounds + 1):
            items = []
            for event in self.state.events:
                if event.round_number != round_number:
                    continue
                if event.event_type == "poison_queued":
                    continue
                if (
                    event.event_type == "action_failed"
                    and event.payload.get("action") == "下毒"
                ):
                    continue
                if event.payload.get("round_discussion"):
                    stage = "轮末讨论"
                elif event.payload.get("free_action"):
                    stage = "自由行动"
                elif event.action_step:
                    stage = f"主要行动 {event.action_step}"
                else:
                    stage = "局势与公开信息"
                items.append({
                    "event_id": event.event_id,
                    "stage": stage,
                    "event_type": event.event_type,
                    "summary": event.summary,
                    "actors": list(event.actors),
                    "location_id": event.location_id,
                    "action_step": event.action_step,
                    "planner_source": event.payload.get("planner_source"),
                })
            rounds.append({
                "round_number": round_number,
                "events": items,
            })
        return {
            "title": title,
            "game_id": self.state.game_id,
            "scenario_id": self.state.scenario_id,
            "rounds_completed": self.state.round_number,
            "max_rounds": max_rounds,
            "actions_per_round": actions_per_round,
            "discussion_turns": int(
                self.state.flags.get("round_discussion_turns", 0)
            ),
            "discussion_limit": 100,
            "rounds": rounds,
        }

    def action_timeline_text(self) -> str:
        timeline = self.build_action_timeline()
        lines = [
            timeline["title"],
            (
                f"局号：{timeline['game_id']}｜已完成 "
                f"{timeline['rounds_completed']}/{timeline['max_rounds']} 轮｜"
                f"轮末讨论 {timeline['discussion_turns']}/"
                f"{timeline['discussion_limit']} 次"
            ),
            "",
        ]
        for round_data in timeline["rounds"]:
            lines.append(f"第 {round_data['round_number']} 轮")
            if not round_data["events"]:
                lines.append("- 尚无事件")
            for event in round_data["events"]:
                source = (
                    f"｜决策源：{event['planner_source']}"
                    if event.get("planner_source")
                    else ""
                )
                lines.append(
                    f"- [{event['stage']}｜{event['event_type']}{source}] "
                    f"{event['summary']}"
                )
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def save_recap(self) -> tuple[Path, Path]:
        with self._save_lock:
            recap = self.build_recap()
            game_dir = self.results_root / "interactive" / self.state.game_id
            game_dir.mkdir(parents=True, exist_ok=True)
            json_path = game_dir / "recap.json"
            markdown_path = game_dir / "recap.md"
            atomic_write_json(json_path, recap)
            atomic_write_text(markdown_path, self.recap_builder.to_markdown(recap))
            outline = self.story_compiler.compile(recap)
            atomic_write_json(game_dir / "story-outline.json", outline)
            atomic_write_text(game_dir / "story-outline.md", self.story_compiler.to_markdown(outline))
            return json_path, markdown_path

    def build_story_outline(self) -> dict[str, Any]:
        return self.story_compiler.compile(self.build_recap())

    def save(self, *, round_result: RoundResult | None = None) -> Path:
        with self._save_lock:
            game_dir = self.results_root / "interactive" / self.state.game_id
            game_dir.mkdir(parents=True, exist_ok=True)
            state_path = game_dir / "state.json"
            atomic_write_json(state_path, self.state.to_dict(include_private=True))
            if round_result is not None:
                round_path = game_dir / f"round-{round_result.round_number:02d}.json"
                atomic_write_json(round_path, round_result.to_dict())
            metadata_path = game_dir / "metadata.json"
            atomic_write_json(
                metadata_path,
                {
                    "game_id": self.state.game_id,
                    "scenario_id": self.state.scenario_id,
                    "title": self.loaded.scenario["title"],
                    "round_number": self.state.round_number,
                    "max_rounds": self.state.max_rounds,
                    "phase": self.state.phase.value,
                },
            )
            return state_path

    def _deliver_unseen_notices(self) -> None:
        for notice in self.state.notices:
            if notice.expires_after_round is not None and notice.expires_after_round < self.state.round_number:
                continue
            present = self.state.occupants(notice.location_id, include_dead=False)
            unseen = [agent_id for agent_id in present if agent_id not in notice.seen_by]
            if unseen:
                notice.seen_by.extend(unseen)
                self._add_notice_beliefs(notice, list(notice.seen_by))

    _PLAN_ACTION_KEYWORDS = {
        "move": ("前往", "移动", "赶到", "转移", "去往", "去"),
        "investigate": ("调查", "搜查", "搜索", "查看", "勘查", "检查", "搜"),
        "talk": ("交谈", "询问", "试探", "质问", "对话", "打听", "沟通", "求证", "核对"),
        "post_notice": ("公告", "张贴", "布告", "公开"),
        "transfer": ("交给", "交付", "递给", "移交"),
        "poison": ("下毒", "毒"),
        "treat": ("治疗", "救治", "诊治", "包扎"),
        "wait": ("观察", "等待", "静观", "按兵"),
    }

    @classmethod
    def _plan_adherence(cls, planned_step: str, action_type: ActionType) -> str:
        """Advisory check: did the executed action match the planned next step?"""

        step = str(planned_step or "").strip()
        if not step:
            return "unknown"
        keywords = cls._PLAN_ACTION_KEYWORDS.get(action_type.value, ())
        if any(keyword in step for keyword in keywords):
            return "followed"
        return "possibly_deviated"

    def _commit_strategic_plans(
        self,
        intents: list[ActionIntent],
        events: list[EventRecord],
    ) -> None:
        """Persist private plans together with the world outcome they produced."""

        for intent in intents:
            agent = self.state.agents.get(intent.actor_id)
            plan = intent.metadata.get("strategic_plan")
            if agent is None or not isinstance(plan, dict) or not plan:
                continue
            outcome_event = next(
                (
                    event for event in reversed(events)
                    if event.actors and event.actors[0] == intent.actor_id
                ),
                None,
            )
            outcome = (
                outcome_event.summary
                if outcome_event
                else "本轮意图没有形成可识别的世界事件。"
            )
            previous_steps = [
                str(step) for step in (agent.strategic_plan.get("steps") or [])
            ]
            previous_step = previous_steps[0] if previous_steps else ""
            if outcome_event is None:
                execution_status = "no_effect"
            elif outcome_event.event_type == "action_failed":
                execution_status = "failed"
            else:
                execution_status = "executed"
            active_round = outcome_event.round_number if outcome_event else self.state.round_number + 1
            action_step = outcome_event.action_step if outcome_event else self.state.action_step
            committed = dict(plan)
            committed.update({
                "updated_round": active_round,
                "updated_action_step": action_step,
                "last_action": intent.action_type.value,
                "last_outcome": outcome,
                "source": intent.metadata.get(
                    "planner_source", committed.get("source", "unknown")
                ),
            })
            agent.strategic_plan = committed
            agent.plan_history.append({
                "round_number": active_round,
                "action_step": action_step,
                "objective": committed.get("objective", ""),
                "intended_action": intent.action_type.value,
                "outcome": outcome,
                "execution_status": execution_status,
                "planned_step": previous_step,
                "plan_adherence": self._plan_adherence(
                    previous_step, intent.action_type,
                ),
                "revision_reason": committed.get("revision_reason", ""),
                "source": committed.get("source", "unknown"),
            })
            agent.plan_history = agent.plan_history[-24:]

    def _update_beliefs_from_round_events(self, events: list[EventRecord]) -> None:
        for event in events:
            recipients: list[tuple[str, str, float]] = []
            if event.event_type == "discovery" and event.actors:
                recipients.append((event.actors[0], "observed", 1.0))
            elif event.event_type == "conversation":
                speaker = event.payload.get("speaker_id")
                listener = event.payload.get("listener_id")
                content = event.payload.get("content", "")
                if content:
                    recipients.extend((
                        witness,
                        "reported",
                        float(event.payload.get("shared_confidence") or 0.65),
                    ) for witness in event.witnesses if witness != speaker)
                shared_belief_id = event.payload.get("shared_belief_id")
                if speaker and shared_belief_id:
                    speaker_state = self.state.agents.get(speaker)
                    shared = next(
                        (
                            belief for belief in speaker_state.beliefs
                            if belief.belief_id == shared_belief_id
                        ),
                        None,
                    ) if speaker_state else None
                    if shared:
                        shared.shared_with = list(dict.fromkeys([
                            *shared.shared_with,
                            *(
                                witness for witness in event.witnesses
                                if witness != speaker
                            ),
                        ]))
                speaker_state = self.state.agents.get(str(speaker or ""))
                if speaker_state and content:
                    speaker_state.public_story.setdefault(
                        "witnesses_of_each_statement", []
                    ).append({
                        "event_id": event.event_id,
                        "content": content,
                        "location_id": event.location_id,
                        "witnesses": list(event.witnesses),
                    })
            elif event.event_type == "final_discussion":
                speaker = event.payload.get("speaker_id")
                if speaker:
                    recipients.append((speaker, "spoken", 1.0))
                recipients.extend(
                    (witness, "reported", 0.7)
                    for witness in event.witnesses if witness != speaker
                )
            elif event.event_type in {
                "poison_effect", "object_transfer",
                "treatment", "investigation_empty", "wait",
                "object_dropped", "health_changed",
                "life_state_changed",
            }:
                recipients.extend((witness, "observed", 0.95) for witness in event.witnesses)
            elif event.event_type == "action_failed" and event.actors:
                recipients.append((event.actors[0], "observed", 1.0))

            for agent_id, stance, confidence in recipients:
                agent = self.state.agents.get(agent_id)
                if agent is None:
                    continue
                if any(belief.source == event.event_id for belief in agent.beliefs):
                    continue
                if event.event_type in {"conversation", "final_discussion"}:
                    speaker_id = event.payload.get("speaker_id")
                    speaker = self.state.agents.get(speaker_id)
                    listener_id = event.payload.get("listener_id")
                    listener = self.state.agents.get(listener_id)
                    shared_claim = event.payload.get("shared_claim")
                    claim = (
                        f"我曾在终局公议中说：{event.payload.get('content', '')}"
                        if event.event_type == "final_discussion" and agent_id == speaker_id
                        else f"{speaker.display_name if speaker else speaker_id}在终局公议中说：{event.payload.get('content', '')}"
                        if event.event_type == "final_discussion"
                        else
                        str(shared_claim)
                        if shared_claim and agent_id != speaker_id
                        else (
                            f"据{speaker.display_name if speaker else speaker_id}所说："
                            f"{event.payload.get('content', '')}"
                        )
                    )
                    truth_id = (
                        event.payload.get("shared_truth_id")
                        if shared_claim and agent_id != speaker_id
                        else None
                    )
                elif event.event_type == "discovery":
                    claim = str(event.payload.get("clue_claim") or event.summary)
                    revealed_secret = event.payload.get("reveals_secret_id")
                    truth_id = (
                        f"secret:{revealed_secret}"
                        if revealed_secret
                        else event.payload.get("truth_id")
                    )
                else:
                    claim = event.summary
                    truth_id = None
                already_shared_with: list[str] = []
                if event.event_type == "conversation":
                    speaker_id = str(event.payload.get("speaker_id") or "")
                    already_shared_with = [
                        witness for witness in event.witnesses
                        if witness != agent_id
                    ]
                normalized_claim = self._normalize_dialogue_text(claim)
                duplicate = next(
                    (
                        existing for existing in agent.beliefs[-60:]
                        if self._normalize_dialogue_text(existing.claim)
                        == normalized_claim
                    ),
                    None,
                ) if normalized_claim else None
                if duplicate is not None:
                    # Direct observation upgrades earlier hearsay of the same
                    # claim instead of stacking a redundant belief.
                    if confidence > duplicate.confidence:
                        duplicate.confidence = confidence
                        duplicate.stance = stance
                        duplicate.confidence_score = max(
                            duplicate.confidence_score,
                            max(0, min(5, round(confidence * 5))),
                        )
                        if truth_id and not duplicate.truth_id:
                            duplicate.truth_id = truth_id
                    continue
                information_type = (
                    "testimony"
                    if event.event_type in {"conversation", "final_discussion"}
                    else "fact"
                )
                belief = Belief(
                    belief_id=f"belief-{agent_id}-{event.event_id}",
                    claim=claim,
                    source=event.event_id,
                    confidence=confidence,
                    stance=stance,
                    learned_round=event.round_number,
                    truth_id=truth_id,
                    shared_with=already_shared_with,
                    information_type=information_type,
                    source_type=(
                        "direct_statement"
                        if information_type == "testimony"
                        else "observation"
                    ),
                    speaker_id=str(event.payload.get("speaker_id") or "") or None,
                    learned_location=event.location_id,
                    witnesses=list(event.witnesses),
                    confidence_score=max(0, min(5, round(confidence * 5))),
                )
                agent.beliefs.append(belief)
                bucket = {
                    "fact": "facts",
                    "testimony": "testimonies",
                    "hypothesis": "hypotheses",
                }[information_type]
                agent.information_state.setdefault(bucket, []).append(
                    belief.belief_id
                )
        for agent in self.state.agents.values():
            self._consolidate_agent_beliefs(agent)

    def _consolidate_agent_beliefs(self, agent: AgentState) -> None:
        """Deterministic corroboration pass over one agent's beliefs.

        Beliefs pointing at the same authored truth, or carrying the same
        normalized claim from different source events, corroborate each other
        (``supporting_ids``). Testimony that stays uncorroborated gets one
        standing verification question so the planner can act on it.
        Semantic contradictions (``opposing_ids``) are intentionally left to
        the character's own reasoning; rules only link what is decidable.
        """

        groups: dict[str, list[Belief]] = {}
        for belief in agent.beliefs:
            if belief.truth_id:
                groups.setdefault(f"truth:{belief.truth_id}", []).append(belief)
            normalized = self._normalize_dialogue_text(belief.claim)
            if normalized:
                groups.setdefault(f"claim:{normalized[:120]}", []).append(belief)
        for members in groups.values():
            distinct_sources = {member.source for member in members}
            if len(members) < 2 or len(distinct_sources) < 2:
                continue
            member_ids = [member.belief_id for member in members]
            for member in members:
                merged = [
                    belief_id for belief_id in member.supporting_ids
                    if belief_id != member.belief_id
                ]
                for belief_id in member_ids:
                    if belief_id != member.belief_id and belief_id not in merged:
                        merged.append(belief_id)
                member.supporting_ids = merged[:6]
        for belief in agent.beliefs:
            if (
                belief.information_type == "testimony"
                and not belief.supporting_ids
                and not belief.verification_questions
            ):
                belief.verification_questions = [
                    "该说法尚无独立旁证；可通过物证或第三方口供核对后再采信。"
                ]
            elif belief.supporting_ids and belief.verification_questions:
                belief.verification_questions = []

    def _award_score(
        self,
        agent_id: str,
        points: int,
        reason: str,
        *,
        reference_id: str,
        category: str = "official",
    ) -> None:
        agent = self.state.agents[agent_id]
        if any(item.get("reference_id") == reference_id for item in agent.score_breakdown):
            return
        agent.score += int(points)
        agent.score_breakdown.append({
            "round_number": min(self.state.round_number + (1 if self.state.action_step else 0), self.state.max_rounds),
            "points": int(points),
            "reason": reason,
            "reference_id": reference_id,
            "category": category,
        })

    def _expose_secret(self, secret_id: str, discoverer_id: str, source_id: str) -> None:
        secret = self.state.secrets.get(secret_id)
        if secret is None or discoverer_id in secret.exposed_to:
            return
        secret.exposed_to.append(discoverer_id)
        discoverer = self.state.agents[discoverer_id]
        if secret_id not in discoverer.discovered_secret_ids:
            discoverer.discovered_secret_ids.append(secret_id)

    def _apply_scoring_from_events(self, events: list[EventRecord]) -> None:
        for event in events:
            if event.event_type == "discovery" and event.actors:
                discoverer_id = event.actors[0]
                secret_id = event.payload.get("reveals_secret_id")
                if secret_id:
                    self._expose_secret(str(secret_id), discoverer_id, event.event_id)
            elif event.event_type == "conversation":
                speaker_id = str(event.payload.get("speaker_id") or "")
                listener_id = str(event.payload.get("listener_id") or "")
                shared_truth_id = str(event.payload.get("shared_truth_id") or "")
                if shared_truth_id.startswith("secret:") and listener_id:
                    self._expose_secret(
                        shared_truth_id.removeprefix("secret:"),
                        listener_id,
                        event.event_id,
                    )
            elif event.event_type == "object_dropped":
                item = self.state.objects.get(str(event.payload.get("object_id") or ""))
                secret_id = str((item.metadata if item else {}).get("reveals_secret_id") or "")
                if secret_id:
                    for witness_id in event.witnesses:
                        self._expose_secret(secret_id, witness_id, event.event_id)

    def _run_final_vote(
        self,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        player_decision: dict[str, Any] | None = None,
    ) -> None:
        if self.state.flags.get("voting_complete"):
            return
        votes: list[dict[str, Any]] = []
        player_id = self.state.player_agent_id
        voters = [
            voter
            for voter in sorted(self.state.agents.values(), key=lambda item: item.agent_id)
            if voter.agent_id != player_id
        ]
        decisions: dict[str, dict[str, Any]] = {}
        pending_votes = list(self.state.flags.get("pending_ai_votes", []))
        if pending_votes:
            votes = pending_votes
            voters = []
        vote_all_method = getattr(self.planner, "vote_all", None)
        if voters and callable(vote_all_method):
            try:
                decisions = vote_all_method(
                    self.state,
                    self.loaded.scenario,
                    [voter.agent_id for voter in voters],
                    progress_callback=progress_callback,
                )
            except Exception:
                decisions = {}

        for voter in voters:
            vote_method = getattr(self.planner, "vote", None)
            if voter.agent_id in decisions:
                decision = decisions[voter.agent_id]
            elif callable(vote_method):
                try:
                    decision = vote_method(self.state, self.loaded.scenario, voter.agent_id)
                except Exception:
                    decision = HeuristicIntentPlanner(seed=0).vote(
                        self.state, self.loaded.scenario, voter.agent_id
                    )
            else:
                decision = HeuristicIntentPlanner(seed=0).vote(
                    self.state, self.loaded.scenario, voter.agent_id
                )
            suspect_id = str(decision.get("suspect_id", ""))
            if suspect_id not in self.state.agents or suspect_id == voter.agent_id:
                fallback = next(
                    agent_id for agent_id in sorted(self.state.agents)
                    if agent_id != voter.agent_id
                )
                suspect_id = fallback
            reason = str(decision.get("reason", "依据现有记忆作出判断。"))[:240]
            answers = self._clean_final_answers(
                voter.agent_id,
                list(decision.get("answers", [])),
            )
            case_conclusion, personal_task_answers = self._structured_final_submission(
                voter.agent_id,
                suspect_id,
                reason,
                dict(decision.get("case_conclusion") or {}),
                list(decision.get("personal_task_answers") or []),
            )
            model_source = str(decision.get("_model_source", "heuristic"))
            self._record_model_usage(
                voter.agent_id,
                stage="final_submission",
                actual_source=model_source,
                succeeded=model_source != "heuristic_fallback",
            )
            vote = {
                "voter_id": voter.agent_id,
                "voter_name": voter.display_name,
                "suspect_id": suspect_id,
                "suspect_name": self.state.agents[suspect_id].display_name,
                "reason": reason,
                "answers": answers,
                "case_conclusion": case_conclusion,
                "personal_task_answers": personal_task_answers,
            }
            votes.append(vote)

        if player_id and player_decision is None:
            self.state.flags["pending_ai_votes"] = votes
            self.state.phase = GamePhase.VOTING
            self.save()
            return
        if player_id and player_decision is not None:
            player = self.state.agents[player_id]
            suspect_id = str(player_decision.get("suspect_id", ""))
            if suspect_id not in self.state.agents or suspect_id == player_id:
                raise ValueError("请选择一名仍在场的其他角色")
            reason = str(player_decision.get("reason", "依据我的记忆作出判断。"))[:240]
            answers = self._clean_final_answers(
                player_id,
                list(player_decision.get("answers", [])),
            )
            case_conclusion, personal_task_answers = self._structured_final_submission(
                player_id,
                suspect_id,
                reason,
                dict(player_decision.get("case_conclusion") or {}),
                list(player_decision.get("personal_task_answers") or []),
            )
            self._record_model_usage(
                player_id,
                stage="final_submission",
                actual_source="player_input",
                provider_name="human",
            )
            votes.append({
                "voter_id": player_id,
                "voter_name": player.display_name,
                "suspect_id": suspect_id,
                "suspect_name": self.state.agents[suspect_id].display_name,
                "reason": reason,
                "answers": answers,
                "case_conclusion": case_conclusion,
                "personal_task_answers": personal_task_answers,
            })

        for vote in votes:
            self.state.events.append(self._event(
                "vote_cast",
                f"{vote['voter_name']}投票指认{vote['suspect_name']}：{vote['reason']}",
                public=True,
                payload={"voter_id": vote["voter_id"], "suspect_id": vote["suspect_id"]},
            ))

        tally: dict[str, int] = {}
        for vote in votes:
            tally[vote["suspect_id"]] = tally.get(vote["suspect_id"], 0) + 1
        highest = max(tally.values(), default=0)
        leaders = sorted(agent_id for agent_id, count in tally.items() if count == highest)
        killer_id = str(self.state.flags.get("killer_id", ""))
        killer = self.state.agents.get(killer_id)
        killer_found = len(leaders) == 1 and leaders[0] == killer_id
        killer_identified = killer_found
        result = {
            "killer_id": killer_id,
            "killer_name": killer.display_name if killer else killer_id,
            "killer_found": killer_found,
            "killer_identified": killer_identified,
            "leaders": leaders,
            "leader_names": [self.state.agents[item].display_name for item in leaders],
            "tally": tally,
            "votes": votes,
            "outcome": (
                "多数意见命中了凶手，凶手未能从终局投票中脱身。"
                if killer_identified
                else "投票未能准确锁定凶手，凶手成功从指认中脱身。"
            ),
        }
        self.state.votes = votes
        self.state.final_submissions = {
            vote["voter_id"]: {
                "vote": {
                    "suspect_id": vote["suspect_id"],
                    "reason": vote["reason"],
                },
                "answers": list(vote.get("answers", [])),
                "case_conclusion": dict(vote.get("case_conclusion", {})),
                "personal_task_answers": list(
                    vote.get("personal_task_answers", [])
                ),
            }
            for vote in votes
        }
        self.state.flags["voting_result"] = result
        self.state.flags["killer_revealed"] = True
        self.state.flags["voting_complete"] = True
        self.state.flags.pop("pending_ai_votes", None)
        self.state.events.append(self._event(
            "killer_revealed",
            f"终局揭晓：本局凶手是{result['killer_name']}。{result['outcome']}",
            public=True,
            payload={
                "killer_id": killer_id,
                "killer_identified": killer_identified,
            },
        ))
        self.state.phase = GamePhase.FINISHED
        self._finalize_scores(
            votes,
            killer_found=killer_found,
        )

    def _prepare_final_discussion(self) -> list[EventRecord]:
        if self.state.flags.get("final_discussion_done"):
            return []
        events: list[EventRecord] = []
        present_ids: list[str] = []
        for agent in self.state.agents.values():
            if agent.life_state == LifeState.DEAD:
                continue
            present_ids.append(agent.agent_id)
            if agent.location_id != "lobby":
                origin = agent.location_id
                agent.location_id = "lobby"
                events.append(self._event(
                    "move",
                    f"终局钟声响起，{agent.display_name}从{self.state.locations[origin]['name']}返回客栈大堂。",
                    public=True,
                    location_id="lobby",
                    witnesses=list(present_ids),
                    payload={
                        "origin_id": origin,
                        "destination_id": "lobby",
                        "forced_final_gathering": True,
                        "suppress_player_feedback": True,
                    },
                ))
                events[-1].actors = [agent.agent_id]

        for agent_id in present_ids:
            if agent_id == self.state.player_agent_id:
                continue
            agent = self.state.agents[agent_id]
            safe_beliefs = [
                belief for belief in agent.beliefs
                if belief.source not in {"凶手记忆", "个人秘密"}
                and not str(belief.truth_id or "").startswith("secret:")
            ]
            evidence = safe_beliefs[-1].claim if safe_beliefs else "我掌握的事实仍不足以闭合因果链"
            vote_hint = HeuristicIntentPlanner(seed=0).vote(
                self.state, self.loaded.scenario, agent_id
            )
            suspect = self.state.agents.get(vote_hint.get("suspect_id", ""))
            content = (
                f"我能确认的是：{evidence}。"
                f"目前我最想请{suspect.display_name if suspect else '在场众人'}解释自己的行踪，但最终判断仍要看证据能否相互印证。"
            )[:240]
            events.append(self._event(
                "final_discussion",
                f"{agent.display_name}在终局公议中发言：{content}",
                public=True,
                location_id="lobby",
                witnesses=list(present_ids),
                payload={
                    "speaker_id": agent_id,
                    "listener_id": "",
                    "content": content,
                    "final_discussion": True,
                },
            ))
            events[-1].actors = [agent_id]
        self.state.events.extend(events)
        self._update_beliefs_from_round_events(events)
        self._deliver_unseen_notices()
        self.state.flags["final_discussion_done"] = True
        return events

    def open_final_vote(self, token: str) -> None:
        self.verify_player_token(token)
        if self.state.phase != GamePhase.DISCUSSION:
            raise ValueError("当前不是终局公议阶段")
        if not self.state.flags.get("final_discussion_done"):
            self._prepare_final_discussion()
        self.state.phase = GamePhase.VOTING
        self.save()

    def submit_player_vote(
        self,
        token: str,
        suspect_id: str,
        reason: str,
        answers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        player_id = self.verify_player_token(token)
        if self.state.phase != GamePhase.VOTING:
            raise ValueError("当前还没有进入终局投票")
        if suspect_id == player_id:
            raise ValueError("不能把票投给自己")
        cleaned_answers = self._clean_final_answers(player_id, answers)
        if any(not item["answer"] for item in cleaned_answers):
            raise ValueError("请回答全部终局客观题后再提交")
        self._run_final_vote(player_decision={
            "suspect_id": suspect_id,
            "reason": reason.strip() or "依据我的记忆作出判断。",
            "answers": cleaned_answers,
        })
        self.save()
        self.save_recap()
        return dict(self.state.flags.get("voting_result", {}))

    def _finalize_scores(
        self,
        votes: list[dict[str, Any]],
        *,
        killer_found: bool,
    ) -> None:
        if self.state.flags.get("scores_finalized"):
            return
        killer_id = str(self.state.flags.get("killer_id", ""))
        for agent in self.state.agents.values():
            agent.score = 0
            agent.score_breakdown = []

        if not killer_found and killer_id in self.state.agents:
            self._award_score(
                killer_id,
                5,
                "凶手成功从终局投票中脱身",
                reference_id="killer-evaded-vote",
                category="killer_evaded_vote",
            )

        if killer_found:
            for agent_id in self.state.agents:
                if agent_id == killer_id:
                    continue
                self._award_score(
                    agent_id,
                    5,
                    "好人阵营的终局结论正确找到真凶",
                    reference_id="innocent-team-found-killer",
                    category="innocent_team_found_killer",
                )

        for vote in votes:
            voter_id = vote["voter_id"]
            if voter_id == killer_id:
                continue
            if vote["suspect_id"] == killer_id:
                self._award_score(
                    voter_id,
                    3,
                    "个人终局投票正确",
                    reference_id="final-vote-correct",
                    category="correct_vote",
                )

        for agent_id in self.state.agents:
            submission = self.state.final_submissions.setdefault(agent_id, {
                "vote": {},
                "answers": [],
            })
            submitted = {
                str(item.get("question_id", "")): str(item.get("answer", ""))
                for item in submission.get("answers", [])
            }
            answer_results: list[dict[str, Any]] = []
            for question in self.final_questions_for(agent_id):
                question_id = str(question["id"])
                answer = submitted.get(question_id, "")
                correct_answer = self._correct_answer_for(question_id)
                is_correct = bool(answer) and answer == correct_answer
                options = {
                    str(option.get("id", "")): str(option.get("label", ""))
                    for option in question.get("options", [])
                }
                result = {
                    "question_id": question_id,
                    "prompt": str(question.get("prompt", "")),
                    "submitted_answer": answer or None,
                    "submitted_label": options.get(answer, "未作答"),
                    "correct_answer": correct_answer,
                    "correct_label": options.get(correct_answer, correct_answer),
                    "is_correct": is_correct,
                    "points": 1 if is_correct else 0,
                }
                answer_results.append(result)
                if is_correct:
                    self._award_score(
                        agent_id,
                        1,
                        f"客观题回答正确：{question.get('prompt', '')}",
                        reference_id=f"correct-answer:{question_id}",
                        category="correct_answer",
                    )
            submission["answer_results"] = answer_results
        self.state.flags["scores_finalized"] = True
        record_completed_game(self.results_root, self.state, self.loaded.scenario)

    def _add_notice_beliefs(self, notice: Notice, agent_ids: list[str]) -> None:
        confidence = 0.7 if notice.authority == "host" else 0.5
        universally_known = notice.authority == "host"
        all_agent_ids = list(self.state.agents)
        for agent_id in agent_ids:
            agent = self.state.agents[agent_id]
            existing = next(
                (
                    belief for belief in agent.beliefs
                    if belief.source == notice.notice_id
                ),
                None,
            )
            known_readers = [
                other_id for other_id in notice.seen_by
                if other_id != agent_id
            ]
            if existing:
                existing.shared_with = list(dict.fromkeys([
                    *existing.shared_with,
                    *known_readers,
                ]))
                continue
            agent.beliefs.append(Belief(
                belief_id=f"belief-{agent_id}-{notice.notice_id}",
                claim=(
                    f"主持人公开公告：{notice.content}"
                    if universally_known
                    else f"公告板声称：{notice.content}"
                ),
                source=notice.notice_id,
                confidence=confidence,
                stance="reported",
                learned_round=self.state.round_number,
                shared_with=(
                    [other_id for other_id in all_agent_ids if other_id != agent_id]
                    if universally_known
                    else known_readers
                ),
            ))

    def _normalize_universal_public_knowledge(self) -> None:
        """Upgrade persisted host publications to the current public-knowledge rules."""

        active_agent_ids = [
            agent_id for agent_id, agent in self.state.agents.items()
            if agent.can_act
        ]
        all_agent_ids = set(self.state.agents)
        for notice in self.state.notices:
            if notice.authority == "host":
                notice.seen_by = list(dict.fromkeys([
                    *notice.seen_by, *active_agent_ids,
                ]))
            readers = [
                agent_id for agent_id in notice.seen_by
                if agent_id in self.state.agents
            ]
            self._add_notice_beliefs(notice, readers)
            for agent_id in readers:
                for belief in self.state.agents[agent_id].beliefs:
                    if belief.source != notice.notice_id:
                        continue
                    if notice.authority == "host":
                        belief.claim = f"主持人公开公告：{notice.content}"
                    belief.shared_with = sorted(set(readers) - {agent_id})

        universal_event_ids = {
            event.event_id for event in self.state.events
            if event.public and event.event_type in {
                "public_fact", "public_intel", "object_hint", "object_revealed",
                "health_changed", "life_state_changed", "object_dropped",
            }
        }
        for agent_id, agent in self.state.agents.items():
            for belief in agent.beliefs:
                if belief.source in universal_event_ids:
                    belief.shared_with = sorted(all_agent_ids - {agent_id})

    def _distribute_public_events(self, events: list[EventRecord]) -> None:
        for event in events:
            if not event.public or event.event_type == "event_card_selected":
                continue
            all_agent_ids = list(self.state.agents)
            for agent in self.state.agents.values():
                if not agent.can_act:
                    continue
                if any(belief.source == event.event_id for belief in agent.beliefs):
                    continue
                agent.beliefs.append(Belief(
                    belief_id=f"belief-{agent.agent_id}-{event.event_id}",
                    claim=f"局势事件表明：{event.summary}",
                    source=event.event_id,
                    confidence=0.8,
                    stance="reported",
                    learned_round=min(self.state.round_number + 1, self.state.max_rounds),
                    shared_with=[
                        agent_id for agent_id in all_agent_ids
                        if agent_id != agent.agent_id
                    ],
                ))

    def _event(
        self,
        event_type: str,
        summary: str,
        *,
        public: bool,
        location_id: str | None = None,
        witnesses: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EventRecord:
        self._event_sequence += 1
        return EventRecord(
            event_id=f"service-event-{self.state.round_number:02d}-{self._event_sequence:04d}",
            round_number=self.state.round_number,
            event_type=event_type,
            summary=summary,
            location_id=location_id,
            public=public,
            witnesses=witnesses or [],
            payload=payload or {},
        )


class GameService:
    GAME_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

    def __init__(
        self,
        project_root: str | Path,
        *,
        results_root: str | Path | None = None,
        planner_factory: Callable[[int], IntentPlanner] | None = None,
    ):
        self.project_root = Path(project_root)
        self.results_root = Path(results_root) if results_root else self.project_root / "results"
        self.planner_factory = planner_factory
        self.loader = ScenarioLoader(self.project_root)
        self.sessions: dict[str, GameSession] = {}

    def create_game(
        self,
        scenario_id: str = "stormbound_inn",
        *,
        game_id: str | None = None,
        seed: int = 0,
        player_agent_id: str | None = None,
    ) -> GameSession:
        game_id = game_id or f"game-{uuid.uuid4().hex[:12]}"
        if not self.GAME_ID_PATTERN.fullmatch(game_id):
            raise ValueError("game_id may contain only letters, numbers, underscores, and hyphens")
        if game_id in self.sessions:
            raise ValueError(f"Game already exists in this process: {game_id}")
        loaded = self.loader.load(scenario_id)
        participant_ids = {item["id"] for item in loaded.scenario["participants"]}
        if player_agent_id and player_agent_id not in participant_ids:
            raise ValueError("所选角色不属于当前情景")
        state = loaded.create_game_state(
            game_id,
            seed=seed,
            player_agent_id=player_agent_id,
        )
        issued_player_token = None
        if player_agent_id:
            issued_player_token = token_secrets.token_urlsafe(24)
            state.flags["player_token_hash"] = hashlib.sha256(
                issued_player_token.encode("utf-8")
            ).hexdigest()
        session = GameSession(
            loaded,
            state,
            results_root=self.results_root,
            seed=seed,
            planner=self.planner_factory(seed) if self.planner_factory else None,
        )
        session.issued_player_token = issued_player_token
        self.sessions[game_id] = session
        return session

    def get(self, game_id: str) -> GameSession:
        if not self.GAME_ID_PATTERN.fullmatch(game_id):
            raise KeyError("Invalid game id")
        if game_id in self.sessions:
            return self.sessions[game_id]
        return self.load_game(game_id)

    def load_game(self, game_id: str) -> GameSession:
        state_path = self.results_root / "interactive" / game_id / "state.json"
        if not state_path.is_file():
            raise KeyError(f"Unknown game: {game_id}")
        with state_path.open("r", encoding="utf-8") as handle:
            state = game_state_from_dict(json.load(handle))
        if state.game_id != game_id:
            raise ValueError("Saved game id does not match its directory")
        loaded = self.loader.load(state.scenario_id)
        if loaded.scenario.get("killer_setup") and not state.flags.get("killer_id"):
            raise ValueError("This save predates the hidden-killer rules; start a new game")
        session = GameSession(
            loaded,
            state,
            results_root=self.results_root,
            seed=0,
            planner=self.planner_factory(0) if self.planner_factory else None,
        )
        self.sessions[game_id] = session
        return session
