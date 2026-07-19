"""Game-session orchestration for the interactive simulation."""

from __future__ import annotations

import json
import hashlib
import random
import re
import secrets as token_secrets
import uuid
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
from .persistence import game_state_from_dict
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

    def plan(
        self,
        state: GameState,
        scenario: dict[str, Any],
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        actor_ids: list[str] | None = None,
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
                if "poison_needle" in agent.inventory:
                    intents.append(ActionIntent(
                        agent_id,
                        ActionType.HIDE,
                        object_id="poison_needle",
                        reason="必须先处理可能暴露作案手段的细针",
                    ))
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue
                possible_targets = [
                    other for other in state.agents.values()
                    if other.agent_id != agent_id
                    and other.location_id == agent.location_id
                    and other.can_act
                ]
                if possible_targets and state.round_number >= 1 and self.random.random() < 0.34:
                    target = self.random.choice(sorted(possible_targets, key=lambda item: item.agent_id))
                    intent = ActionIntent(
                        agent_id,
                        ActionType.ATTACK,
                        target_id=target.agent_id,
                        reason="趁同室混乱，用暗针削弱可能揭穿自己的人",
                    )
                    apply_ability(state, intent)
                    intents.append(intent)
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue
                if agent.location_id == "stable" and (
                    state.flags.get("stable_in_disarray")
                    or state.flags.get("back_exit_open")
                ):
                    intents.append(ActionIntent(
                        agent_id,
                        ActionType.ESCAPE,
                        reason="马厩后方出现机会，必须在终局投票前脱身",
                    ))
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue
                route = self._shortest_path(state, agent.location_id, "stable")
                if len(route) > 1 and state.round_number >= 2:
                    intents.append(ActionIntent(
                        agent_id,
                        ActionType.MOVE,
                        location_id=route[1],
                        reason="一边伪装调查，一边靠近预定的逃离路线",
                    ))
                    completed = self._report_progress(
                        progress_callback, agent, completed, active_total
                    )
                    continue

            # Treatment belongs to the innkeeper's character ability.
            if agent_id == "广陵王":
                wounded = [
                    other for other in state.agents.values()
                    if other.location_id == agent.location_id
                    and other.life_state in {LifeState.INJURED, LifeState.INCAPACITATED, LifeState.DYING}
                ]
                if wounded:
                    target = min(wounded, key=lambda item: item.health)
                    intent = ActionIntent(agent_id, ActionType.TREAT, target_id=target.agent_id)
                    apply_ability(state, intent)
                    intents.append(intent)
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
            exchange_options: list[tuple[Any, Belief]] = []
            for target in others:
                for belief in reversed(agent.beliefs):
                    if (
                        belief.source not in {"凶手记忆", "个人秘密"}
                        and not str(belief.truth_id or "").startswith("secret:")
                        and target.agent_id not in belief.shared_with
                    ):
                        exchange_options.append((target, belief))
                        break
            if exchange_options:
                target, shared = self.random.choice(exchange_options)
                talk_intent = ActionIntent(
                    agent_id,
                    ActionType.TALK,
                    target_id=target.agent_id,
                    content=f"我把这条情报告诉你：{shared.claim}。你是否有能相互印证的线索？"[:180],
                    reason="把尚未告诉对方的情报用于交换，并要求交叉验证",
                    metadata={"share_belief_id": shared.belief_id},
                )
                intents.append(talk_intent)
                completed = self._report_progress(
                    progress_callback, agent, completed, active_total
                )
                continue

            if agent.location_id == "lobby":
                existing_posts = {notice.content for notice in state.notices}
                publishable = next((
                    belief for belief in reversed(agent.beliefs)
                    if belief.confidence >= 0.75
                    and belief.source not in {"凶手记忆", "个人秘密"}
                    and not str(belief.truth_id or "").startswith("secret:")
                    and belief.claim not in existing_posts
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
                        reason="先检查当前地点是否留有异常痕迹",
                    )
                )
                completed = self._report_progress(
                    progress_callback, agent, completed, active_total
                )
                continue

            connections = list(location.get("connections", []))
            if connections:
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
    ) -> dict[str, str]:
        voter = state.agents[voter_id]
        candidates = [
            agent for agent in state.agents.values()
            if agent.agent_id != voter_id and agent.life_state != LifeState.DEAD
        ]
        if not candidates:
            return {"suspect_id": voter_id, "reason": "已经没有其他可指认的人。"}

        suspicion_words = ("凶手", "毒", "藏", "逃", "攻击", "异常", "伪造", "指控", "说谎", "失踪")
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
                "object_hidden": 2.6,
                "escape_failed": 4.2,
                "escape": 5.0,
                "attack": 3.0,
                "attack_failed": 2.0,
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
        return {"suspect_id": suspect.agent_id, "reason": reason[:180]}

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
        shareable = [
            belief for belief in speaker.beliefs
            if belief.source not in {"凶手记忆", "个人秘密"}
            and player_id not in belief.shared_with
        ]
        shared = shareable[-1] if shareable else None
        if speaker_id == state.flags.get("killer_id"):
            text = "这件事我也只听到零碎说法。你若有确切时辰或物证，我们可以当面核对。"
            shared = None
        elif shared:
            text = f"我能确认的一点是：{shared.claim}。至于你刚才问的事，我还不敢把猜测当成结论。"
        elif "?" in player_message or "？" in player_message:
            text = "我现在没有足够证据回答。若你愿意说出依据，我会把它和自己的行踪重新核对。"
        else:
            text = "我记住了你的话，但在看到相互印证的线索前，我不会贸然下结论。"
        return {
            "content": text[:180],
            "share_belief_id": shared.belief_id if shared else None,
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
        self.engine._event_sequence = len(state.events)
        self.director._event_sequence = len(state.events)
        self.trigger_resolver._event_sequence = len(state.events)
        self.issued_player_token: str | None = None
        self._discard_legacy_movement_beliefs()
        self.save()

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

    def public_state(self) -> dict[str, Any]:
        data = self.state.public_view()
        data["title"] = self.loaded.scenario["title"]
        data["premise"] = self.loaded.scenario["premise"]
        data["planner"] = self.planner.__class__.__name__
        data["planner_provider"] = getattr(self.planner, "provider_name", "heuristic")
        data["public_facts"] = self.loaded.scenario.get("public_facts", [])
        data["ending_questions"] = self.loaded.scenario.get("ending_questions", [])
        data["game_rules"] = self.loaded.scenario.get("game_rules", [])
        data["controlled_agent_id"] = self.state.player_agent_id
        if self.state.phase == GamePhase.FINISHED:
            data["voting_result"] = dict(self.state.flags.get("voting_result", {}))
            data["scoreboard"] = self.scoreboard()
        return data

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
                "stage": "脱身预案",
                "title": "封锁期间仍在寻找逃脱或转移怀疑的机会",
                "detail": str(profile.get("escape_plan", "")),
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
            "escape_plan": str(profile.get("escape_plan", "")),
            "weapon": weapon.to_dict(reveal_hidden=True, reveal_metadata=True)
            if weapon else None,
            "stolen_item": stolen.to_dict(reveal_hidden=True, reveal_metadata=True)
            if stolen else None,
            "evidence": evidence,
            "murder_chain": murder_chain,
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
            situation = "客栈暂时陷入压抑的安静。现在由你决定何时让下一轮局势展开，也可以等待真人主持人介入。"
            objective = "准备好后点击“自动主持·展开下一轮”；系统会随机发布相关情报并抽取事件卡。"
            suggestions = ["回想陆成临终时的异常", "检查自己的秘密与任务", "留意地图上与你同处一室的人"]
        elif phase in {GamePhase.READY, GamePhase.PLAYER_TURN}:
            title = f"第 {display_round} 轮 · 主要行动 {self.state.action_step}/{self.state.actions_per_round}"
            situation = card_description or recent or f"你此刻位于{location_name}，所有人都在根据刚刚发生的事重新打算。"
            if player_id == killer_id:
                objective = "选择一个能推进表面目标、又不会暴露作案事实的行动。别人会记住你做过和说过的一切。"
            else:
                objective = "自由移动和交谈以探索现场；确认目标后再使用有限的搜查、交付、藏匿、治疗或冲突行动。"
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
            "object_hint", "evidence_lost", "killer_revealed", "vote_cast",
        }
        known_events = [
            event.to_dict() for event in self.state.events
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
                "health": other.health,
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
            "public_intel_history": list(self.state.public_intel_history),
            "opening_dispatch": dict(self.loaded.scenario.get("opening_dispatch", {})),
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
            },
            "known_secrets": known_secrets,
            "conversations": conversation_history,
            "story_guide": self._build_story_guide(player_id, known_events),
            "available_actions": self.available_player_actions(player_id),
            "requires_vote": self.state.phase == GamePhase.VOTING,
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
            "move", "investigate", "talk", "transfer", "hide", "escape",
        ]
        for ability in special_actions:
            action_type = str(ability["action_type"])
            if action_type in {"attack", "treat"} and action_type not in action_types:
                action_types.append(action_type)
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
            "can_investigate": bool(self.state.locations[actor.location_id].get("searchable")),
            "can_escape": actor.location_id in {"front_gate", "stable"},
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
            raise ValueError("你的角色没有执行这项冲突或治疗行动的能力")
        selected_ability_id = str(raw.get("ability_id") or "")
        if selected_ability_id:
            ability = apply_ability(self.state, intent, selected_ability_id)
            if not ability:
                raise ValueError("这项专属技能不属于你的角色，或不能用于当前行动")
        elif action_type in {ActionType.ATTACK, ActionType.TREAT}:
            apply_ability(self.state, intent)
        share_belief_id = str(raw.get("share_belief_id") or "")
        if share_belief_id:
            actor = self.state.agents[player_id]
            if not any(belief.belief_id == share_belief_id for belief in actor.beliefs):
                raise ValueError("只能交换自己记忆中真实存在的情报")
            intent.metadata["share_belief_id"] = share_belief_id
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
        notice = Notice(
            notice_id=f"notice-{self._notice_sequence:04d}",
            round_number=self.state.round_number,
            publisher=publisher,
            display_author=display_author,
            content=content,
            location_id=location_id,
            authority=authority,
            seen_by=list(present),
        )
        self.state.notices.append(notice)
        self._add_notice_beliefs(notice, present)
        event = self._event(
            "notice_posted",
            f"{display_author}在{self.state.locations[location_id]['name']}公告板发布：{content}",
            public=True,
            location_id=location_id,
            witnesses=present,
            payload={"notice_id": notice.notice_id},
        )
        self.state.events.append(event)
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
        if player_intent.action_type in {ActionType.MOVE, ActionType.TALK}:
            result = self.engine.resolve_free_action(self.state, player_intent)
            if player_intent.action_type == ActionType.TALK and result.events:
                outgoing = result.events[0]
                reply_to_event_id = str(raw_intent.get("reply_to_event_id") or "")
                if reply_to_event_id:
                    outgoing.payload["reply_to_event_id"] = reply_to_event_id
                    outgoing.payload["is_player_reply"] = True
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
                    reply_result = self.engine.resolve_free_action(self.state, reply_intent)
                    if reply_result.events:
                        reply = reply_result.events[0]
                        reply.payload["is_reply"] = True
                        reply.payload["reply_to_event_id"] = outgoing.event_id
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

    def auto_host_next_round(self, token: str) -> dict[str, Any]:
        """Choose a seeded random clue and event when no human host is present."""

        self.verify_player_token(token)
        if self.state.phase not in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}:
            raise ValueError("当前还不能展开下一轮")
        if self.state.active_event_card:
            raise ValueError("本轮事件已经展开")

        published_intel: dict[str, Any] | None = None
        intel_event: EventRecord | None = None
        intel_options = self.intel_suggestions()
        if intel_options and not self.state.active_public_intel:
            picked_intel = self.random.choice(intel_options)
            published_intel, intel_event = self.publish_public_intel(picked_intel["id"])

        card_options = self.card_suggestions()
        quiet = self.empty_event_option()
        picked_card = self.random.choice([*card_options, quiet])
        card_events = self.select_event_card(picked_card["card_id"])
        return {
            "intel": published_intel,
            "intel_event": intel_event.to_dict() if intel_event else None,
            "card": picked_card,
            "events": [event.to_dict() for event in card_events],
        }

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
        if override_intents is not None:
            intents = list(override_intents)
        else:
            excluded = {self.state.player_agent_id} if self.state.player_agent_id else set()
            actor_ids = [
                agent_id for agent_id, agent in self.state.agents.items()
                if agent.can_act and agent_id not in excluded
            ]
            try:
                intents = self.planner.plan(
                    self.state,
                    self.loaded.scenario,
                    progress_callback=progress_callback,
                    actor_ids=actor_ids,
                )
            except TypeError:
                intents = [
                    intent for intent in self.planner.plan(
                        self.state,
                        self.loaded.scenario,
                        progress_callback=progress_callback,
                    )
                    if intent.actor_id in actor_ids
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
        if self.state.player_agent_id:
            for event in result.events:
                if (
                    event.event_type == "conversation"
                    and event.payload.get("listener_id") == self.state.player_agent_id
                    and event.payload.get("speaker_id") != self.state.player_agent_id
                ):
                    event.payload["player_reply_invited"] = True
        result.events[0:0] = trigger_events
        self._materialize_agent_notices(result.events)
        self._commit_strategic_plans(intents, result.events)
        self._update_beliefs_from_round_events(result.events)
        self._apply_scoring_from_events(result.events)
        self._deliver_unseen_notices()
        if self.state.action_step == 0:
            self.state.active_event_card = None
            self.state.active_public_intel = None
            if self.state.phase == GamePhase.ROUND_COMPLETE:
                self.state.phase = GamePhase.INTERVENTION
            elif self.state.phase == GamePhase.DISCUSSION:
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

    def build_recap(self, *, allow_incomplete: bool = False) -> dict[str, Any]:
        if self.state.phase != GamePhase.FINISHED and not allow_incomplete:
            raise ValueError("Recap is available after the final round")
        return self.recap_builder.build(self.loaded, self.state)

    def save_recap(self) -> tuple[Path, Path]:
        recap = self.build_recap()
        game_dir = self.results_root / "interactive" / self.state.game_id
        game_dir.mkdir(parents=True, exist_ok=True)
        json_path = game_dir / "recap.json"
        markdown_path = game_dir / "recap.md"
        json_path.write_text(
            json.dumps(recap, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(
            self.recap_builder.to_markdown(recap),
            encoding="utf-8",
        )
        outline = self.story_compiler.compile(recap)
        (game_dir / "story-outline.json").write_text(
            json.dumps(outline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (game_dir / "story-outline.md").write_text(
            self.story_compiler.to_markdown(outline),
            encoding="utf-8",
        )
        return json_path, markdown_path

    def build_story_outline(self) -> dict[str, Any]:
        return self.story_compiler.compile(self.build_recap())

    def save(self, *, round_result: RoundResult | None = None) -> Path:
        game_dir = self.results_root / "interactive" / self.state.game_id
        game_dir.mkdir(parents=True, exist_ok=True)
        state_path = game_dir / "state.json"
        state_path.write_text(
            json.dumps(self.state.to_dict(include_private=True), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if round_result is not None:
            round_path = game_dir / f"round-{round_result.round_number:02d}.json"
            round_path.write_text(
                json.dumps(round_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        metadata_path = game_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps({
                "game_id": self.state.game_id,
                "scenario_id": self.state.scenario_id,
                "title": self.loaded.scenario["title"],
                "round_number": self.state.round_number,
                "max_rounds": self.state.max_rounds,
                "phase": self.state.phase.value,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
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
                self._add_notice_beliefs(notice, unseen)

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
                    event for event in events
                    if event.actors and event.actors[0] == intent.actor_id
                ),
                None,
            )
            outcome = (
                outcome_event.summary
                if outcome_event
                else "本轮意图没有形成可识别的世界事件。"
            )
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
                if speaker and content:
                    recipients.append((speaker, "spoken", 1.0))
                if listener and content:
                    recipients.append((
                        listener,
                        "reported",
                        float(event.payload.get("shared_confidence") or 0.65),
                    ))
                shared_belief_id = event.payload.get("shared_belief_id")
                if speaker and listener and shared_belief_id:
                    speaker_state = self.state.agents.get(speaker)
                    shared = next(
                        (
                            belief for belief in speaker_state.beliefs
                            if belief.belief_id == shared_belief_id
                        ),
                        None,
                    ) if speaker_state else None
                    if shared and listener not in shared.shared_with:
                        shared.shared_with.append(listener)
                for witness in event.witnesses:
                    if witness not in {speaker, listener}:
                        recipients.append((witness, "overheard", 0.45))
            elif event.event_type == "final_discussion":
                speaker = event.payload.get("speaker_id")
                if speaker:
                    recipients.append((speaker, "spoken", 1.0))
                recipients.extend(
                    (witness, "reported", 0.7)
                    for witness in event.witnesses if witness != speaker
                )
            elif event.event_type in {
                "attack", "attack_failed", "object_transfer", "object_hidden",
                "treatment", "investigation_empty", "wait", "escape",
                "escape_failed"
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
                        f"我曾对{listener.display_name if listener else listener_id}说：{event.payload.get('content', '')}"
                        if agent_id == speaker_id
                        else
                        f"{speaker.display_name if speaker else speaker_id}分享情报：{shared_claim}"
                        if shared_claim and agent_id == event.payload.get("listener_id")
                        else (
                            f"{speaker.display_name if speaker else speaker_id}声称："
                            f"{event.payload.get('content', '')}"
                        )
                    )
                    truth_id = (
                        event.payload.get("shared_truth_id")
                        if shared_claim and agent_id == event.payload.get("listener_id")
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
                    listener_id = str(event.payload.get("listener_id") or "")
                    if agent_id == speaker_id and listener_id:
                        already_shared_with = [listener_id]
                    elif agent_id == listener_id and speaker_id:
                        already_shared_with = [speaker_id]
                agent.beliefs.append(Belief(
                    belief_id=f"belief-{agent_id}-{event.event_id}",
                    claim=claim,
                    source=event.event_id,
                    confidence=confidence,
                    stance=stance,
                    learned_round=event.round_number,
                    truth_id=truth_id,
                    shared_with=already_shared_with,
                ))

    def _award_score(
        self,
        agent_id: str,
        points: int,
        reason: str,
        *,
        reference_id: str,
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
        })

    def _expose_secret(self, secret_id: str, discoverer_id: str, source_id: str) -> None:
        secret = self.state.secrets.get(secret_id)
        if secret is None or discoverer_id in secret.exposed_to:
            return
        secret.exposed_to.append(discoverer_id)
        discoverer = self.state.agents[discoverer_id]
        if secret_id not in discoverer.discovered_secret_ids:
            discoverer.discovered_secret_ids.append(secret_id)
        if discoverer_id != secret.owner_id:
            self._award_score(
                discoverer_id,
                secret.discovery_score,
                f"发现了{self.state.agents[secret.owner_id].display_name}隐藏的秘密“{secret.title}”",
                reference_id=f"secret-discovery:{secret_id}:{discoverer_id}",
            )

    def _apply_scoring_from_events(self, events: list[EventRecord]) -> None:
        for event in events:
            if event.event_type == "discovery" and event.actors:
                discoverer_id = event.actors[0]
                secret_id = event.payload.get("reveals_secret_id")
                if secret_id:
                    self._expose_secret(str(secret_id), discoverer_id, event.event_id)
                if event.payload.get("clue_kind") == "truth":
                    self._award_score(
                        discoverer_id,
                        1,
                        "找到了一块可拼合案件真相的线索",
                        reference_id=f"truth-clue:{event.payload.get('object_id')}:{discoverer_id}",
                    )
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
                if speaker_id and listener_id and shared_truth_id:
                    listener = self.state.agents[listener_id]
                    matching_before = [
                        belief for belief in listener.beliefs
                        if belief.truth_id == shared_truth_id and belief.source != event.event_id
                    ]
                    if not matching_before:
                        self._award_score(
                            speaker_id,
                            1,
                            f"向{listener.display_name}交换了一条对方尚未知晓的有效情报",
                            reference_id=f"exchange:{event.event_id}:{speaker_id}",
                        )

    def _run_final_vote(
        self,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        player_decision: dict[str, str] | None = None,
    ) -> None:
        if self.state.flags.get("voting_complete"):
            return
        votes: list[dict[str, Any]] = []
        player_id = self.state.player_agent_id
        voters = [
            voter
            for voter in sorted(self.state.agents.values(), key=lambda item: item.agent_id)
            if voter.life_state != LifeState.DEAD and voter.agent_id != player_id
        ]
        decisions: dict[str, dict[str, str]] = {}
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
            vote = {
                "voter_id": voter.agent_id,
                "voter_name": voter.display_name,
                "suspect_id": suspect_id,
                "suspect_name": self.state.agents[suspect_id].display_name,
                "reason": reason,
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
            votes.append({
                "voter_id": player_id,
                "voter_name": player.display_name,
                "suspect_id": suspect_id,
                "suspect_name": self.state.agents[suspect_id].display_name,
                "reason": reason,
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
        killer_escaped = bool(self.state.flags.get("killer_escaped"))
        killer_identified = killer_id in leaders and not killer_escaped
        result = {
            "killer_id": killer_id,
            "killer_name": killer.display_name if killer else killer_id,
            "killer_escaped": killer_escaped,
            "killer_identified": killer_identified,
            "leaders": leaders,
            "leader_names": [self.state.agents[item].display_name for item in leaders],
            "tally": tally,
            "votes": votes,
            "outcome": (
                "凶手已经逃离，指认来得太迟。"
                if killer_escaped
                else "多数意见命中了凶手，众人将其控制在客栈内。"
                if killer_identified
                else "投票未能准确锁定凶手，真相直到复盘才被揭开。"
            ),
        }
        self.state.votes = votes
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
                "killer_escaped": killer_escaped,
                "killer_identified": killer_identified,
            },
        ))
        self.state.phase = GamePhase.FINISHED
        self._finalize_scores(votes, killer_identified=killer_identified)

    def _prepare_final_discussion(self) -> list[EventRecord]:
        if self.state.flags.get("final_discussion_done"):
            return []
        events: list[EventRecord] = []
        present_ids: list[str] = []
        for agent in self.state.agents.values():
            if agent.life_state == LifeState.DEAD or "escaped" in agent.conditions:
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
    ) -> dict[str, Any]:
        player_id = self.verify_player_token(token)
        if self.state.phase != GamePhase.VOTING:
            raise ValueError("当前还没有进入终局投票")
        if suspect_id == player_id:
            raise ValueError("不能把票投给自己")
        self._run_final_vote(player_decision={
            "suspect_id": suspect_id,
            "reason": reason.strip() or "依据我的记忆作出判断。",
        })
        self.save()
        self.save_recap()
        return dict(self.state.flags.get("voting_result", {}))

    def _finalize_scores(
        self,
        votes: list[dict[str, Any]],
        *,
        killer_identified: bool,
    ) -> None:
        if self.state.flags.get("scores_finalized"):
            return
        killer_id = str(self.state.flags.get("killer_id", ""))
        for vote in votes:
            voter_id = vote["voter_id"]
            if voter_id == killer_id:
                continue
            if vote["suspect_id"] == killer_id:
                self._award_score(
                    voter_id, 5, "终局投票正确找出凶手", reference_id="final-vote-correct"
                )
            else:
                self._award_score(
                    voter_id, -2, "终局被误导，未能投中凶手", reference_id="final-vote-wrong"
                )
        if killer_id in self.state.agents:
            self._award_score(
                killer_id,
                -5 if killer_identified else 6,
                "身份被多数票锁定" if killer_identified else "成功隐藏身份直到终局",
                reference_id="killer-outcome",
            )
        for secret in self.state.secrets.values():
            if secret.category != "personal" or secret.owner_id not in self.state.agents:
                continue
            outsiders = [item for item in secret.exposed_to if item != secret.owner_id]
            points = secret.conceal_score if not outsiders else 1 if len(outsiders) == 1 else -2
            reason = (
                f"秘密“{secret.title}”无人发现"
                if not outsiders
                else f"秘密“{secret.title}”仅被一人知晓"
                if len(outsiders) == 1
                else f"秘密“{secret.title}”已被多人识破"
            )
            self._award_score(
                secret.owner_id,
                points,
                reason,
                reference_id=f"secret-conceal:{secret.secret_id}",
            )
        self.state.flags["scores_finalized"] = True

    def _add_notice_beliefs(self, notice: Notice, agent_ids: list[str]) -> None:
        confidence = 0.7 if notice.authority == "host" else 0.5
        for agent_id in agent_ids:
            agent = self.state.agents[agent_id]
            if any(belief.source == notice.notice_id for belief in agent.beliefs):
                continue
            agent.beliefs.append(Belief(
                belief_id=f"belief-{agent_id}-{notice.notice_id}",
                claim=f"公告板声称：{notice.content}",
                source=notice.notice_id,
                confidence=confidence,
                stance="reported",
                learned_round=self.state.round_number,
            ))

    def _distribute_public_events(self, events: list[EventRecord]) -> None:
        for event in events:
            if event.event_type != "public_fact":
                continue
            for agent in self.state.agents.values():
                if not agent.can_act:
                    continue
                agent.beliefs.append(Belief(
                    belief_id=f"belief-{agent.agent_id}-{event.event_id}",
                    claim=f"局势事件表明：{event.summary}",
                    source=event.event_id,
                    confidence=0.8,
                    stance="reported",
                    learned_round=min(self.state.round_number + 1, self.state.max_rounds),
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
