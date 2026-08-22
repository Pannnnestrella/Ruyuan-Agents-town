"""Heuristic intent planning for the interactive simulation."""

from __future__ import annotations

import random
import re
from typing import Any, Callable, Protocol

from ..domain.abilities import apply_ability
from ..domain.models import ActionIntent, ActionType, GameState, LifeState
from ..domain.round_engine import bulletin_location

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

    @classmethod
    def _normalize_dialogue_text(cls, value: str) -> str:
        extracted = cls._extract_information_claim(value)
        text = re.sub(r"[\s，。！？；：“”‘’、,.!?;:]", "", extracted)
        return text[:240]

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
            board_location = bulletin_location(state)
            if unseen_notices and agent.location_id != board_location and not force_major and self.random.random() < 0.45:
                route = self._shortest_path(state, agent.location_id, board_location)
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
                                self._normalize_dialogue_text(known.claim)
                                == self._normalize_dialogue_text(belief.claim)
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

            if agent.location_id == bulletin_location(state):
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
                    self._normalize_dialogue_text(known.claim)
                    == self._normalize_dialogue_text(belief.claim)
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
