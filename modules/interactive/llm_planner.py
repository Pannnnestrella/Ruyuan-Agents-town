"""LLM-backed character intent planning without access to objective truths."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from modules.model.llm_model import create_llm_model

from .models import ActionIntent, ActionType, GameState
from .abilities import abilities_for, action_is_authorized
from .service import HeuristicIntentPlanner


class OpenAICompatibleChatModel:
    """Small adapter for OpenAI-compatible chat endpoints.

    It is used only when the legacy provider SDK is unavailable.  The adapter
    deliberately has short timeouts so a failed provider cannot block all six
    characters for several minutes.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = float(timeout_seconds)
        self.client = None
        try:
            from openai import OpenAI

            sdk_base_url = re.sub(r"/chat/completions/?$", "", self.base_url)
            self.client = OpenAI(
                api_key=api_key,
                base_url=sdk_base_url,
                timeout=self.timeout_seconds,
                max_retries=1,
            )
        except (ImportError, ModuleNotFoundError):
            pass

    def completion(self, prompt: str, **kwargs: Any) -> str | None:
        temperature = float(kwargs.get("temperature", 0.72))
        max_tokens = int(kwargs.get("max_tokens", 700))
        timeout_seconds = float(getattr(self, "timeout_seconds", 20.0))
        if self.client is not None:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if not response.choices:
                return None
            return response.choices[0].message.content

        import requests

        endpoint = (
            self.base_url
            if self.base_url.endswith("/chat/completions")
            else f"{self.base_url}/chat/completions"
        )
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout_seconds,
        )
        if not response.ok:
            raise RuntimeError(f"LLM endpoint returned HTTP {response.status_code}")
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        return choices[0].get("message", {}).get("content")


class LLMIntentPlanner:
    def __init__(
        self,
        model: Any,
        *,
        fallback: HeuristicIntentPlanner | None = None,
        max_workers: int = 6,
        provider_name: str = "configured",
    ):
        self.model = model
        self.fallback = fallback or HeuristicIntentPlanner(seed=0)
        self.max_workers = max(1, min(8, int(max_workers)))
        self.provider_name = provider_name

    @classmethod
    def from_project_config(
        cls,
        project_root: str | Path,
        *,
        fallback: HeuristicIntentPlanner | None = None,
    ) -> "LLMIntentPlanner":
        config_path = Path(project_root) / "data" / "config.json"
        with config_path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        llm_config = dict(config["agent_base"]["think"]["llm"])
        # Prefer the small adapter for interactive rounds. Some legacy wrappers
        # keep mutable response accounting and print full completions, which is
        # unsafe when six character requests run concurrently.
        model = cls._openai_compatible_fallback(llm_config, config["api_keys"])
        if model is None:
            try:
                model = create_llm_model(**llm_config, keys=config["api_keys"])
            except (ImportError, ModuleNotFoundError):
                model = None
        if model is None:
            raise ValueError(f"No registered LLM backend supports model {llm_config.get('model')}")
        return cls(
            model,
            fallback=fallback,
            provider_name=f"project:{llm_config.get('model', 'unknown')}",
        )

    @classmethod
    def from_ollama(
        cls,
        model_name: str,
        *,
        base_url: str = "http://127.0.0.1:11434/v1",
        fallback: HeuristicIntentPlanner | None = None,
    ) -> "LLMIntentPlanner":
        model_name = model_name.strip()
        if not model_name:
            raise ValueError("Ollama model name cannot be empty")
        return cls(
            OpenAICompatibleChatModel(
                base_url=base_url,
                model=model_name,
                api_key="ollama-local",
                timeout_seconds=90.0,
            ),
            fallback=fallback,
            max_workers=2,
            provider_name=f"ollama:{model_name}",
        )

    @staticmethod
    def _openai_compatible_fallback(
        llm_config: dict[str, Any],
        api_keys: dict[str, Any],
    ) -> OpenAICompatibleChatModel | None:
        model_name = str(llm_config.get("model", ""))
        model_lower = model_name.lower()
        if "glm" in model_lower:
            key_name = "ZHIPUAI_API_KEY"
        elif "gemini" in model_lower:
            key_name = "GEMINI_API_KEY"
        else:
            key_name = "OPENAI_API_KEY"
        api_key = str(api_keys.get(key_name, "")).strip()
        base_url = str(llm_config.get("base_url", "")).strip()
        if not api_key or not base_url or not model_name:
            return None
        return OpenAICompatibleChatModel(
            base_url=base_url,
            model=model_name,
            api_key=api_key,
        )

    def plan(
        self,
        state: GameState,
        scenario: dict[str, Any],
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        actor_ids: list[str] | None = None,
        force_major: bool = False,
    ) -> list[ActionIntent]:
        requested = set(actor_ids) if actor_ids is not None else set(state.agents)
        fallback_by_agent = {
            intent.actor_id: intent
            for intent in self.fallback.plan(
                state, scenario, actor_ids=list(requested), force_major=force_major
            )
        }
        participants = {item["id"]: item for item in scenario["participants"]}
        active_agent_ids = [
            agent_id for agent_id in sorted(state.agents)
            if agent_id in requested and state.agents[agent_id].can_act
        ]
        # Freeze all six scoped contexts before starting any request. No model
        # completion can influence the prompt another character receives.
        prompts = {
            agent_id: self._build_prompt(
                state, scenario, participants[agent_id], force_major=force_major
            )
            for agent_id in active_agent_ids
        }
        intents_by_agent: dict[str, ActionIntent] = {}
        total = len(active_agent_ids)

        def decide(agent_id: str) -> tuple[ActionIntent, str]:
            try:
                response = self.model.completion(
                    prompts[agent_id],
                    retry=2,
                    failsafe=None,
                    caller="interactive_intent",
                    temperature=0.72,
                )
                intent = self._parse_intent(agent_id, response)
            except Exception:
                intent = None
            if intent is not None and not self._intent_is_grounded(state, intent):
                intent = None
            if intent is None:
                fallback = fallback_by_agent[agent_id]
                fallback.metadata["planner_source"] = "heuristic_fallback"
                return fallback, "heuristic_fallback"
            if not intent.metadata.get("strategic_plan"):
                carried = dict(state.agents[agent_id].strategic_plan)
                carried["revision_reason"] = "模型没有返回计划修订，暂时延续上一版计划。"
                intent.metadata["strategic_plan"] = carried
            intent.metadata["planner_source"] = "llm"
            return intent, "llm"

        completed = 0
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, total or 1),
            thread_name_prefix="character-intent",
        ) as executor:
            futures = {
                executor.submit(decide, agent_id): agent_id
                for agent_id in active_agent_ids
            }
            for future in as_completed(futures):
                agent_id = futures[future]
                try:
                    intent, source = future.result()
                except Exception:
                    intent, source = fallback_by_agent[agent_id], "heuristic_fallback"
                intents_by_agent[agent_id] = intent
                completed += 1
                if progress_callback:
                    progress_callback({
                        "stage": "intent",
                        "agent_id": agent_id,
                        "display_name": state.agents[agent_id].display_name,
                        "status": "completed",
                        "source": source,
                        "completed": completed,
                        "total": total,
                    })
        return [intents_by_agent[agent_id] for agent_id in active_agent_ids]

    def vote_all(
        self,
        state: GameState,
        scenario: dict[str, Any],
        voter_ids: list[str],
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, dict[str, str]]:
        decisions: dict[str, dict[str, str]] = {}
        ordered_voters = sorted(voter_ids)
        total = len(ordered_voters)
        completed = 0
        with ThreadPoolExecutor(
            max_workers=min(self.max_workers, total or 1),
            thread_name_prefix="character-vote",
        ) as executor:
            futures = {
                executor.submit(self.vote, state, scenario, voter_id): voter_id
                for voter_id in ordered_voters
            }
            for future in as_completed(futures):
                voter_id = futures[future]
                try:
                    decisions[voter_id] = future.result()
                    source = "llm"
                except Exception:
                    decisions[voter_id] = self.fallback.vote(state, scenario, voter_id)
                    source = "heuristic_fallback"
                completed += 1
                if progress_callback:
                    progress_callback({
                        "stage": "vote",
                        "agent_id": voter_id,
                        "display_name": state.agents[voter_id].display_name,
                        "status": "completed",
                        "source": source,
                        "completed": completed,
                        "total": total,
                    })
        return decisions

    def respond_to_player(
        self,
        state: GameState,
        scenario: dict[str, Any],
        speaker_id: str,
        player_id: str,
        player_message: str,
    ) -> dict[str, str | None]:
        """Generate one grounded reply without exposing objective truth."""

        speaker = state.agents[speaker_id]
        participant = next(
            item for item in scenario["participants"] if item["id"] == speaker_id
        )
        memories = [
            {
                "belief_id": belief.belief_id,
                "claim": belief.claim,
                "confidence": belief.confidence,
                "stance": belief.stance,
                "shared_with": list(belief.shared_with),
                "origin_type": "conversation" if str(belief.source).startswith("event-") else "authored_or_observed",
            }
            for belief in speaker.beliefs[-20:]
        ]
        context: dict[str, Any] = {
            "speaker": {
                "id": speaker_id,
                "name": speaker.display_name,
                "role": speaker.public_role,
                "goals": participant.get("goals", []),
                "decision_rules": participant.get("decision_rules", []),
            },
            "player": {
                "id": player_id,
                "name": state.agents[player_id].display_name,
                "message": player_message,
            },
            "private_memories": memories,
            "player_guide": scenario.get("player_guide", {}),
            "carried_items": [
                {
                    "object_id": object_id,
                    "name": state.objects[object_id].name,
                    "description": state.objects[object_id].metadata.get("description", ""),
                }
                for object_id in speaker.inventory if object_id in state.objects
            ],
            "secrets_to_protect": [
                {"title": secret.title, "claim": secret.claim}
                for secret in state.secrets.values()
                if secret.owner_id == speaker_id
            ],
            "current_plan": speaker.strategic_plan,
            "recent_dialogue_with_player": [
                {
                    "speaker_id": event.payload.get("speaker_id"),
                    "content": event.payload.get("content", ""),
                    "shared_claim": event.payload.get("shared_claim"),
                }
                for event in state.events
                if event.event_type == "conversation"
                and {event.payload.get("speaker_id"), event.payload.get("listener_id")}
                == {speaker_id, player_id}
            ][-8:],
        }
        if speaker_id == state.flags.get("killer_id"):
            context["private_killer_rule"] = (
                "你是隐藏凶手。回应必须自然，但绝不能承认身份、作案方法或只有凶手知道的事实。"
            )
        prompt = f"""你正在扮演密探“{speaker.display_name}”，玩家刚刚与你当面交谈。
只依据 JSON 中属于你的记忆、目标和秘密作出一句自然回应。你可以回避、反问、撒谎或交换情报，但不得知道客观真相，也不得替玩家行动。若愿意交出一条真实记忆，只能填写 private_memories 中存在、且此前没有交给该玩家的 belief_id；否则为 null。不要逐字重复 recent_dialogue_with_player 中已经说过的话。

如果玩家在对话中要求查看随身物品，你可以根据目标选择：自愿出示 carried_items 中真实存在的一件（item_disposition="show" 并填写 display_object_id）、明确拒绝（"refuse"）、或在台词中撒谎（"lie"，但不得填写不存在的 display_object_id）。这仍然只是交谈，不是强制检查；不得自动夺取、交付物品。

{json.dumps(context, ensure_ascii=False, indent=2)}

只输出 JSON：{{"content":"不超过一百八十字的当面回应","share_belief_id":null,"item_disposition":"none|show|refuse|lie","display_object_id":null}}"""
        try:
            response = self.model.completion(
                prompt,
                retry=2,
                failsafe=None,
                caller="interactive_conversation_reply",
                temperature=0.78,
                max_tokens=260,
            )
            text = str(response or "").strip()
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            content = str(data.get("content") or "").strip()[:180]
            belief_id = str(data.get("share_belief_id") or "")[:160]
            disposition = str(data.get("item_disposition") or "none")
            object_id = str(data.get("display_object_id") or "")[:160]
            valid_object_ids = set(speaker.inventory)
            if disposition != "show" or object_id not in valid_object_ids:
                object_id = ""
            if disposition not in {"none", "show", "refuse", "lie"}:
                disposition = "none"
            valid_ids = {
                belief.belief_id for belief in speaker.beliefs
                if player_id not in belief.shared_with
            }
            if not content:
                raise ValueError("empty reply")
            return {
                "content": content,
                "share_belief_id": belief_id if belief_id in valid_ids else None,
                "display_object_id": object_id or None,
                "item_disposition": "show" if object_id else (
                    disposition if disposition in {"refuse", "lie"} else "none"
                ),
                "_host_item_disposition": disposition,
            }
        except Exception:
            return self.fallback.respond_to_player(
                state, scenario, speaker_id, player_id, player_message
            )

    @staticmethod
    def _intent_is_grounded(state: GameState, intent: ActionIntent) -> bool:
        """Reject references outside the actor's scoped, currently usable world."""

        actor = state.agents.get(intent.actor_id)
        if actor is None or not actor.can_act:
            return False
        if not action_is_authorized(state, intent):
            return False
        location = state.locations[actor.location_id]
        target = state.agents.get(intent.target_id) if intent.target_id else None
        item = state.objects.get(intent.object_id) if intent.object_id else None

        if intent.action_type == ActionType.MOVE:
            return bool(
                intent.location_id
                and intent.location_id in location.get("connections", [])
            )
        if intent.action_type == ActionType.INVESTIGATE:
            if intent.location_id not in {None, actor.location_id}:
                return False
            has_new_object = any(
                item.location_id == actor.location_id
                and actor.agent_id not in item.discovered_by
                for item in state.objects.values()
            )
            already_exhausted = any(
                event.event_type == "investigation_empty"
                and event.actors[:1] == [actor.agent_id]
                and event.location_id == actor.location_id
                for event in state.events
            )
            return has_new_object or not already_exhausted
        if intent.action_type in {ActionType.TALK, ActionType.ATTACK}:
            grounded = bool(
                target
                and target.agent_id != actor.agent_id
                and target.can_act
                and target.location_id == actor.location_id
            )
            if not grounded or intent.action_type != ActionType.TALK:
                if grounded and intent.action_type == ActionType.ATTACK:
                    return actor.agent_id not in state.flags.get(
                        "attacks_by_round", {}
                    ).get(str(state.round_number + 1), [])
                return grounded
            display_id = str(intent.metadata.get("display_object_id") or "")
            if display_id and display_id not in actor.inventory:
                return False
            shared_id = str(intent.metadata.get("share_belief_id") or "")
            if not shared_id:
                return True
            shared = next(
                (belief for belief in actor.beliefs if belief.belief_id == shared_id),
                None,
            )
            return bool(
                shared
                and target.agent_id not in shared.shared_with
                and not any(
                    LLMIntentPlanner._dialogue_fingerprint(known.claim)
                    == LLMIntentPlanner._dialogue_fingerprint(shared.claim)
                    for known in target.beliefs[-60:]
                )
            )
        if intent.action_type == ActionType.POST_NOTICE:
            return bool(
                actor.location_id == "lobby"
                and intent.content.strip()
                and intent.content.strip() not in {notice.content for notice in state.notices}
            )
        if intent.action_type == ActionType.TRANSFER:
            return bool(
                target
                and target.agent_id != actor.agent_id
                and target.can_act
                and target.location_id == actor.location_id
                and item
                and item.holder_id == actor.agent_id
            )
        if intent.action_type == ActionType.HIDE:
            return bool(item and item.holder_id == actor.agent_id)
        if intent.action_type == ActionType.TREAT:
            return bool(
                target
                and target.can_act
                and (
                    target.agent_id == actor.agent_id
                    or target.location_id == actor.location_id
                )
            )
        if intent.action_type == ActionType.ESCAPE:
            return actor.location_id in {"front_gate", "stable"}
        return intent.action_type == ActionType.WAIT

    @staticmethod
    def _dialogue_fingerprint(value: str) -> str:
        text = str(value)
        for prefix in (
            "我把这条情报告诉你：", "我愿意把这条情报告诉你：",
            "我愿意分享一条尚未与你核对的信息：",
        ):
            text = text.replace(prefix, "")
        text = re.split(r"你(?:是否)?有能相互印证的线索", text, maxsplit=1)[0]
        return re.sub(r"[\s，。！？；：“”‘’、,.!?;:]", "", text)[:240]

    def vote(
        self,
        state: GameState,
        scenario: dict[str, Any],
        voter_id: str,
    ) -> dict[str, Any]:
        voter = state.agents[voter_id]
        candidates = [
            {"id": agent.agent_id, "name": agent.display_name, "role": agent.public_role}
            for agent in state.agents.values()
            if agent.agent_id != voter_id and agent.life_state.value != "dead"
        ]
        context: dict[str, Any] = {
            "voter": {"id": voter.agent_id, "name": voter.display_name},
            "candidates": candidates,
            "personal_memories": [belief.to_dict() for belief in voter.beliefs[-32:]],
            "rules": scenario.get("game_rules", []),
            "personal_goals": next(
                (
                    item.get("goals", []) for item in scenario.get("participants", [])
                    if item["id"] == voter_id
                ),
                [],
            ),
        }
        if voter_id == state.flags.get("killer_id"):
            context["private_role"] = "你是隐藏凶手。为了避免被多数票指认，你可以把票投给最容易被怀疑的其他人。"
        prompt = f"""你正在扮演“{voter.display_name}”，现在必须独立投票指认凶手。

只能依据 personal_memories 中属于你的记忆判断，不得读取作者真相。即使证据不足也必须从 candidates 中选择一人；理由必须引用你记得的行动、对话或情报，不得编造新事件。投票前，主持人还会逐项询问你的 personal_goals 是否完成：请根据自己的记忆诚实回答 achieved，并给出可核对的简短依据；没有依据就回答 false。

{json.dumps(context, ensure_ascii=False, indent=2)}

只输出 JSON：
{{"suspect_id":"候选人id","reason":"不超过一百二十字的记忆依据","goal_assessments":[{{"goal":"逐字复制 personal_goals 中一项","achieved":true,"reason":"不超过一百字的自述依据"}}]}}"""
        try:
            response = self.model.completion(
                prompt,
                retry=2,
                failsafe=None,
                caller="interactive_vote",
                temperature=0.35,
            )
            text = str(response or "").strip()
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)
            suspect_id = str(data.get("suspect_id", ""))
            if suspect_id not in {item["id"] for item in candidates}:
                raise ValueError("invalid vote target")
            authored_goals = {str(goal) for goal in context["personal_goals"]}
            assessments = []
            for item in data.get("goal_assessments", []):
                if not isinstance(item, dict) or str(item.get("goal", "")) not in authored_goals:
                    continue
                assessments.append({
                    "goal": str(item["goal"]),
                    "achieved": bool(item.get("achieved")),
                    "reason": str(item.get("reason", ""))[:180],
                })
            return {
                "suspect_id": suspect_id,
                "reason": str(data.get("reason", "依据现有记忆作出判断。"))[:180],
                "goal_assessments": assessments,
            }
        except Exception:
            return self.fallback.vote(state, scenario, voter_id)

    def _build_prompt(
        self,
        state: GameState,
        scenario: dict[str, Any],
        participant: dict[str, Any],
        *,
        force_major: bool = False,
    ) -> str:
        agent = state.agents[participant["id"]]
        location = state.locations[agent.location_id]
        visible_people = [
            {
                "id": other.agent_id,
                "name": other.display_name,
                "role": other.public_role,
                "life_state": other.life_state.value,
            }
            for other in state.agents.values()
            if other.agent_id != agent.agent_id and other.location_id == agent.location_id
        ]
        visible_objects = []
        for item in state.objects.values():
            if item.holder_id == agent.agent_id:
                visible_objects.append({"id": item.object_id, "name": item.name, "relation": "持有"})
            elif item.location_id == agent.location_id:
                visible = item.to_dict(viewer_id=agent.agent_id)
                if visible is not None:
                    visible_objects.append({"id": item.object_id, "name": item.name, "relation": "同地点可见"})

        global_event_types = {
            "event_card_selected", "public_fact", "public_intel", "world_trigger",
            "object_hint", "evidence_lost", "bulletin_updated",
        }
        recent_known_events = [
            event.summary for event in state.events
            if event.event_type != "move" and (
                agent.agent_id in event.actors
                or agent.agent_id in event.witnesses
                or event.event_type in global_event_types
            )
        ][-12:]
        private_beliefs = [
            {
                "belief_id": belief.belief_id,
                "claim": belief.claim,
                "source": belief.source,
                "confidence": belief.confidence,
                "stance": belief.stance,
            }
            for belief in agent.beliefs[-32:]
        ]
        exhausted_locations = sorted({
            event.location_id for event in state.events
            if event.event_type == "investigation_empty"
            and event.actors[:1] == [agent.agent_id]
            and event.location_id
        })
        prior_exchanges = [
            {
                "listener_id": event.payload.get("listener_id"),
                "shared_belief_id": event.payload.get("shared_belief_id"),
                "content": event.payload.get("content", ""),
            }
            for event in state.events
            if event.event_type == "conversation"
            and event.payload.get("speaker_id") == agent.agent_id
        ][-12:]
        can_attack_this_round = agent.agent_id not in state.flags.get(
            "attacks_by_round", {}
        ).get(str(state.round_number + 1), [])
        context = {
            "scenario": scenario["premise"],
            "public_facts": scenario.get("public_facts", []),
            "game_rules": scenario.get("game_rules", []),
            "player_guide": scenario.get("player_guide", {}),
            "round": state.round_number + 1,
            "action_step": state.action_step + 1,
            "actions_per_round": state.actions_per_round,
            "max_rounds": state.max_rounds,
            "character": {
                "id": participant["id"],
                "public_role": participant.get("public_role", ""),
                "goals": participant.get("goals", []),
                "decision_rules": participant.get("decision_rules", []),
                "health": agent.health,
                "life_state": agent.life_state.value,
                "conditions": agent.conditions,
            },
            "private_beliefs": private_beliefs,
            "private_secrets_to_protect": [
                {
                    "secret_id": secret.secret_id,
                    "title": secret.title,
                    "claim": secret.claim,
                    "known_by_others": len([
                        other_id for other_id in secret.exposed_to
                        if other_id != agent.agent_id
                    ]),
                }
                for secret in state.secrets.values()
                if secret.owner_id == agent.agent_id
            ],
            "score": agent.score,
            "current_strategic_plan": dict(agent.strategic_plan),
            "recent_plan_outcomes": list(agent.plan_history[-3:]),
            "current_location": {
                "id": location["id"],
                "name": location["name"],
                "description": location["description"],
                "connected_locations": [
                    {"id": location_id, "name": state.locations[location_id]["name"]}
                    for location_id in location.get("connections", [])
                ],
            },
            "visible_people": visible_people,
            "visible_objects": visible_objects,
            "recent_known_events": recent_known_events,
            "exhausted_locations": exhausted_locations,
            "prior_exchanges": prior_exchanges,
            "bulletin_posts": [
                {"author": notice.display_author, "content": notice.content}
                for notice in state.notices
                if agent.agent_id in notice.seen_by
            ],
            "bulletin_has_unread": any(
                agent.agent_id not in notice.seen_by for notice in state.notices
            ),
            "special_abilities": abilities_for(state, agent.agent_id),
            "can_attack_this_round": can_attack_this_round,
            "action_budget": (
                "本次必须选择会消耗次数的主要行动；移动和交谈已在此前作为自由行动完成。"
                if force_major
                else "本次可以先选择一次自由移动或自由交谈；它不会消耗主要行动次数，之后仍会再次决策主要行动。"
            ),
            "pregame_timeline": list(
                state.flags.get("character_timelines", {}).get(agent.agent_id, [])
            ),
        }
        if agent.agent_id == state.flags.get("killer_id"):
            profile = state.flags.get("killer_profile", {})
            context["private_killer_directive"] = {
                "identity": "你是本局隐藏凶手，绝不能把这一身份直接写进公开发言。",
                "motive": profile.get("motive", ""),
                "method": profile.get("method", ""),
                "escape_plan": profile.get("escape_plan", ""),
            }
        special_abilities = abilities_for(state, agent.agent_id)
        special_lines = "\n".join(
            f"- {ability['action_type']}（{ability['label']}）：{ability['description']}"
            for ability in special_abilities
            if ability["action_type"] in {"attack", "treat"}
            and not (ability["action_type"] == "attack" and not can_attack_this_round)
        )
        allowed_types = ["investigate", "transfer", "hide", "escape", "wait"]
        if not force_major and location.get("connections") and agent.life_state.value not in {
            "severely_injured", "incapacitated", "dying"
        }:
            allowed_types.insert(0, "move")
        if not force_major and visible_people:
            allowed_types.insert(1 if "move" in allowed_types else 0, "talk")
        if agent.location_id == "lobby":
            allowed_types.append("post_notice")
        for ability in special_abilities:
            if ability["action_type"] == "attack" and not can_attack_this_round:
                continue
            if ability["action_type"] not in allowed_types:
                allowed_types.append(ability["action_type"])
        allowed_type_text = "|".join(allowed_types)
        return f"""你正在扮演互动推演中的角色“{agent.display_name}”。

只根据下面 JSON 中提供给你的信息决定一步。每轮共有 actions_per_round 个会消耗次数的主要行动阶段；移动和交谈是自由行动，不占主要行动次数。系统会在自由行动后让你重新观察现场并继续选择主要行动。严格服从 action_budget：当它要求主要行动时，不得再选择 move 或 talk。你不知道剧本的客观真相，也不得假定未提供的信息为真。公告、流言和他人陈述只是有来源的说法，不是自动成立的事实。

你还要维护一个持续 2—3 轮的私人计划。先检查 current_strategic_plan 与 recent_plan_outcomes：仍然合理的步骤应保留，已经完成、失败或被新情报推翻的部分才修订。计划不是预言，不能宣布尚未发生的结果；它应包含下一步、后续步骤以及至少一种局势变化时的备选方案。角色可以改变怀疑对象，但 revision_reason 必须说明依据。pregame_timeline 是你亲历的入店与案发前时间线，可用于核对口供。不要在已经确认搜空且没有新物品的地点重复搜查；不要把 prior_exchanges 中已经告诉同一人的同一情报再次复述，也不要把“我曾告诉某人……”这样的对话记录再次包装成新情报。

把 player_guide 视为所有密探都知道的通用玩法指引，而不是人物性格或强制脚本。你可以依局势自由取舍，但应理解：搜查、交叉核对时辰与物证、主动交谈、共享不涉及自身秘密的可靠情报，都有助于拼合真相；当公开自己的秘密能解释嫌疑时，也可以权衡后坦白。查看随身物品只通过谈话提出，对方可以出示、拒绝或撒谎。bulletin_has_unread 为真只代表大堂有新张贴，未到大堂前不得知道正文。

{json.dumps(context, ensure_ascii=False, indent=2)}

可用行动：
- move：前往 connected_locations 中一个相邻地点，填写 location_id。
- investigate：调查当前地点，location_id 必须是当前地点。
- talk：与 visible_people 中一人交谈，填写 target_id，并在 content 中填写准备说出的具体信息或问题（不超过一百字）。若要交换一条自己确实知道的记忆，可把 private_beliefs 中的 belief_id 填入 share_belief_id；这会把该记忆连同来源交给对方。若你在台词中明确自愿出示 visible_objects 中由自己“持有”的一件物品，可填写 display_object_id 并令 item_disposition="show"；也可以在被要求时拒绝或撒谎，但不得凭空出示物品。
- post_notice：仅在大堂可用。把一条你愿意实名公开、且 bulletin_posts 中尚未出现的可靠情报写入 content；不得公开自己的秘密或凶手身份。
- transfer：把自己持有的物品交给同地点角色，填写 target_id 与 object_id。
- hide：在当前地点藏起自己持有的物品，填写 object_id。
- escape：只有当你决定违反禁令、且已身处客栈正门或马厩时，尝试离开客栈；世界规则决定出口是否可用。
- wait：留在原地观察。
{special_lines or '- 你没有冲突或治疗能力；不得选择 attack 或 treat。'}

请让选择符合人物目标、决策规则、已知信息和当前局势。不得一次执行多个行动，不得替世界宣布调查结论、伤害结果或他人反应。

只输出一个 JSON 对象，不要 Markdown，不要解释：
{{
  "action_type": "{allowed_type_text}",
  "target_id": null,
  "location_id": null,
  "object_id": null,
  "content": "",
  "share_belief_id": null,
  "item_disposition": "none|show|refuse|lie",
  "display_object_id": null,
  "reason": "角色作出这个选择的简短内在理由",
  "plan": {{
    "objective": "未来二至三轮最重要的私人目标",
    "horizon_rounds": 3,
    "steps": ["本轮步骤", "下一轮倾向", "随后要验证的事情"],
    "contingencies": ["如果关键前提改变，准备如何调整"],
    "suspects": [{{"agent_id": "人物id", "confidence": 0.5, "basis": "只引用自己的记忆"}}],
    "public_posture": "准备让其他人看到的态度",
    "revision_reason": "相对上一版计划保留或修改了什么，以及原因"
  }}
}}"""

    @staticmethod
    def _parse_intent(actor_id: str, response: Any) -> ActionIntent | None:
        if not isinstance(response, str) or not response.strip():
            return None
        text = response.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        if not isinstance(data, dict):
            return None
        try:
            action_type = ActionType(data["action_type"])
        except (KeyError, ValueError):
            return None
        intent = ActionIntent(
            actor_id=actor_id,
            action_type=action_type,
            target_id=data.get("target_id") or None,
            location_id=data.get("location_id") or None,
            object_id=data.get("object_id") or None,
            content=str(data.get("content") or "")[:500],
            reason=str(data.get("reason") or "")[:500],
        )
        share_belief_id = str(data.get("share_belief_id") or "")[:160]
        if share_belief_id:
            intent.metadata["share_belief_id"] = share_belief_id
        display_object_id = str(data.get("display_object_id") or "")[:160]
        item_disposition = str(data.get("item_disposition") or "")[:20]
        if display_object_id:
            intent.metadata["display_object_id"] = display_object_id
        if item_disposition in {"none", "show", "refuse", "lie"}:
            intent.metadata["item_disposition"] = item_disposition
        plan = LLMIntentPlanner._sanitize_plan(data.get("plan"))
        if plan:
            intent.metadata["strategic_plan"] = plan
        return intent

    @staticmethod
    def _sanitize_plan(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        try:
            horizon = max(1, min(3, int(raw.get("horizon_rounds", 3))))
        except (TypeError, ValueError):
            horizon = 3
        steps = [str(item)[:180] for item in raw.get("steps", []) if str(item).strip()][:3]
        contingencies = [
            str(item)[:180]
            for item in raw.get("contingencies", [])
            if str(item).strip()
        ][:2]
        suspects = []
        for item in raw.get("suspects", [])[:4]:
            if not isinstance(item, dict) or not str(item.get("agent_id", "")).strip():
                continue
            try:
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
            except (TypeError, ValueError):
                confidence = 0.5
            suspects.append({
                "agent_id": str(item["agent_id"])[:80],
                "confidence": confidence,
                "basis": str(item.get("basis", ""))[:180],
            })
        objective = str(raw.get("objective", "")).strip()[:180]
        if not objective and not steps:
            return {}
        return {
            "objective": objective or steps[0],
            "horizon_rounds": horizon,
            "steps": steps,
            "contingencies": contingencies,
            "suspects": suspects,
            "public_posture": str(raw.get("public_posture", ""))[:180],
            "revision_reason": str(raw.get("revision_reason", ""))[:240],
        }
