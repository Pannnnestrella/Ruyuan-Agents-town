"""Load and validate reusable world packs and scenario packages."""

from __future__ import annotations

import json
import random
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    AgentState,
    Belief,
    GamePhase,
    GameState,
    ItemHistoryEntry,
    LifeState,
    ObjectState,
    SecretState,
)


class ScenarioValidationError(ValueError):
    """Raised when a world or scenario contains invalid references."""


@dataclass(slots=True)
class LoadedScenario:
    world: dict[str, Any]
    scenario: dict[str, Any]
    world_path: Path
    scenario_path: Path

    def create_game_state(
        self,
        game_id: str | None = None,
        *,
        seed: int = 0,
        player_agent_id: str | None = None,
    ) -> GameState:
        game_id = game_id or f"game-{uuid.uuid4().hex[:12]}"
        locations = {
            location["id"]: dict(location)
            for location in self.world["locations"]
        }
        for location_id, observations in self.scenario.get("search_observations", {}).items():
            if location_id in locations:
                locations[location_id]["search_observations"] = list(observations)
        agents: dict[str, AgentState] = {}
        for participant in self.scenario["participants"]:
            beliefs = [
                Belief(
                    belief_id=f"belief-{participant['id']}-{index + 1}",
                    claim=fact["claim"],
                    source=fact.get("source", "scenario"),
                    confidence=float(fact.get("confidence", 1.0)),
                    stance=fact.get("stance", "believes"),
                    learned_round=0,
                    truth_id=fact.get("truth_id"),
                    information_type=str(fact.get("information_type", "fact")),
                    source_type=str(fact.get("source_type", "authored_memory")),
                    perspective_owner_id=participant["id"],
                    confidence_score=max(
                        0, min(5, round(float(fact.get("confidence", 1.0)) * 5))
                    ),
                )
                for index, fact in enumerate(participant.get("private_facts", []))
            ]
            for index, memory in enumerate(participant.get("background_memories", []), start=1):
                if isinstance(memory, dict):
                    claim = str(memory.get("claim", "")).strip()
                    source = str(memory.get("source", "往事回忆"))
                    confidence = float(memory.get("confidence", 0.9))
                else:
                    claim = str(memory).strip()
                    source = "往事回忆"
                    confidence = 0.9
                if claim:
                    beliefs.append(Belief(
                        belief_id=f"belief-{participant['id']}-background-{index}",
                        claim=claim,
                        source=source,
                        confidence=confidence,
                        stance="believes",
                        learned_round=0,
                        information_type="fact",
                        source_type="memory",
                        perspective_owner_id=participant["id"],
                        confidence_score=max(0, min(5, round(confidence * 5))),
                    ))
            agents[participant["id"]] = AgentState(
                agent_id=participant["id"],
                display_name=participant.get("display_name", participant["id"]),
                location_id=participant["start_location"],
                life_state=LifeState(participant.get("life_state", LifeState.ALIVE.value)),
                inventory=list(participant.get("inventory", [])),
                beliefs=beliefs,
                public_role=participant.get("public_role", ""),
                resources=dict(participant.get("resources", {})),
                strategic_plan={
                    "objective": str((participant.get("goals") or ["观察局势"])[0]),
                    "horizon_rounds": 3,
                    "steps": [str(goal) for goal in participant.get("goals", [])[:3]],
                    "contingencies": [],
                    "suspects": [],
                    "public_posture": "先观察，再根据可靠记忆调整行动。",
                    "revision_reason": "情景开始时形成的初步计划。",
                    "updated_round": 0,
                    "source": "scenario",
                },
                identity_state={
                    "character_name": participant.get("display_name", participant["id"]),
                    "faction": participant.get("faction", ""),
                    "is_killer": False,
                    "known_role_information": list(participant.get("private_facts", [])),
                    "personal_secrets": [],
                },
                location_state={
                    "current_area": participant["start_location"],
                    "previous_area": None,
                    "movement_history": [],
                },
                inventory_state={
                    "held_items": list(participant.get("inventory", [])),
                    "exchanged_items": [],
                    "publicly_revealed_items": [],
                },
                information_state={
                    "facts": [belief.belief_id for belief in beliefs],
                    "testimonies": [],
                    "hypotheses": [],
                    "contradictions": [],
                    "unanswered_questions": [],
                },
                case_model={
                    "victim": self.scenario.get("victim", "陆成"),
                    "suspected_cause_of_death": None,
                    "estimated_time_of_death": None,
                    "body_discovery_time": None,
                    "primary_crime_scene": None,
                    "possible_weapons": [],
                    "possible_methods": [],
                    "suspect_profiles": {},
                    "timeline": {},
                    "current_best_explanation": None,
                },
                social_model={"characters": {}},
                strategy_state={
                    "current_goal": str((participant.get("goals") or ["观察局势"])[0]),
                    "next_action": None,
                    "reason": "情景开始",
                    "risk": None,
                    "expected_information_gain": None,
                },
                personal_tasks=[
                    {
                        "question": str(goal),
                        "known_information": [],
                        "missing_information": [],
                        "related_characters": [],
                        "related_items": [],
                        "related_areas": [],
                        "current_hypothesis": None,
                        "next_action": None,
                        "confidence": 0,
                    }
                    for goal in participant.get("goals", [])
                ],
                public_story={
                    "claimed_timeline": [],
                    "claimed_locations": [],
                    "claimed_contacts": [],
                    "admitted_items": [],
                    "admitted_secrets": [],
                    "denied_actions": [],
                    "witnesses_of_each_statement": [],
                },
            )

        for agent in agents.values():
            for index, claim in enumerate(self.scenario.get("public_facts", []), start=1):
                agent.beliefs.append(Belief(
                    belief_id=f"belief-{agent.agent_id}-public-{index}",
                    claim=str(claim),
                    source=f"public-fact-{index}",
                    confidence=0.95,
                    stance="known",
                    learned_round=0,
                    information_type="fact",
                    source_type="public_fact",
                    confidence_score=5,
                ))
                agent.information_state["facts"].append(
                    f"belief-{agent.agent_id}-public-{index}"
                )

        secrets: dict[str, SecretState] = {}
        for raw_secret in self.scenario.get("secrets", []):
            secret = SecretState(
                secret_id=raw_secret["id"],
                owner_id=raw_secret["owner_id"],
                title=raw_secret["title"],
                claim=raw_secret["claim"],
                category=raw_secret.get("category", "personal"),
                conceal_score=int(raw_secret.get("conceal_score", 3)),
                discovery_score=int(raw_secret.get("discovery_score", 2)),
                exposed_to=[raw_secret["owner_id"]],
            )
            secrets[secret.secret_id] = secret
            owner = agents[secret.owner_id]
            if not any(belief.truth_id == f"secret:{secret.secret_id}" for belief in owner.beliefs):
                owner.beliefs.append(Belief(
                    belief_id=f"belief-{secret.owner_id}-{secret.secret_id}",
                    claim=secret.claim,
                    source="个人秘密",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id=f"secret:{secret.secret_id}",
                    information_type="fact",
                    source_type="private_secret",
                    perspective_owner_id=secret.owner_id,
                    confidence_score=5,
                ))
            owner.identity_state["personal_secrets"].append(secret.secret_id)

        objects: dict[str, ObjectState] = {}
        for item in self.scenario.get("objects", []):
            objects[item["id"]] = ObjectState(
                object_id=item["id"],
                name=item["name"],
                location_id=item.get("location_id"),
                holder_id=item.get("holder_id"),
                hidden=bool(item.get("hidden", False)),
                portable=bool(item.get("portable", True)),
                discovered_by=list(item.get("discovered_by", [])),
                tags=list(item.get("tags", [])),
                metadata=dict(item.get("metadata", {})),
                original_location=item.get("location_id"),
                original_holder=item.get("holder_id"),
                authenticity=str(item.get("metadata", {}).get("authenticity", "unknown")),
                evidential_value=str(item.get("metadata", {}).get("evidential_value", "")),
                secret_value=str(item.get("metadata", {}).get("secret_value", "")),
                history=[ItemHistoryEntry(
                    action="initial",
                    round_number=0,
                    from_location=item.get("location_id"),
                    to_location=item.get("location_id"),
                    from_holder=item.get("holder_id"),
                    to_holder=item.get("holder_id"),
                    hidden_before=bool(item.get("hidden", False)),
                    hidden_after=bool(item.get("hidden", False)),
                    public=not bool(item.get("hidden", False)),
                    witnesses=list(item.get("discovered_by", [])),
                )],
            )

        for agent in agents.values():
            for object_id in agent.inventory:
                objects[object_id].transition(
                    "scenario_assign",
                    round_number=0,
                    actor_id=agent.agent_id,
                    holder_id=agent.agent_id,
                    location_id=None,
                    witnesses=[agent.agent_id],
                    public=False,
                )

        flags = dict(self.scenario.get("initial_flags", {}))
        flags["seed"] = seed
        flags["bulletin_location_id"] = str(
            self.scenario.get("bulletin_location_id")
            or self.world.get("default_notice_location")
            or "lobby"
        )
        killer_setup = self.scenario.get("killer_setup") or {}
        killer_candidates = list(killer_setup.get("candidates", []))
        if killer_candidates:
            killer_profile = deepcopy(random.Random(seed).choice(
                sorted(killer_candidates, key=lambda item: item["agent_id"])
            ))
            killer_id = killer_profile["agent_id"]
            case_manifest = {
                "case_id": killer_profile.get("case_id", f"case-{killer_id}"),
                "killer_id": killer_id,
                "motive": killer_profile.get("motive", ""),
                "method": killer_profile.get("method", ""),
                "cover_plan": killer_profile.get("cover_plan", ""),
                "stolen_item_id": (killer_profile.get("stolen_item") or {}).get("id"),
                "evidence_object_ids": [
                    item["id"] for item in killer_profile.get("evidence_objects", [])
                ],
            }
            flags.update({
                "killer_id": killer_id,
                "killer_profile": killer_profile,
                "case_manifest": case_manifest,
                "killer_revealed": False,
                "voting_complete": False,
                "scores_finalized": False,
            })
            killer = agents[killer_id]
            killer.identity_state["is_killer"] = True
            killer.beliefs.extend([
                Belief(
                    belief_id=f"belief-{killer_id}-killer-role",
                    claim="你就是杀死陆成的凶手。其他五人不知道你的身份；你的唯一核心目标是避免在终局投票中被多数人正确指认。",
                    source="凶手记忆",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id="truth-killer",
                    information_type="fact",
                    source_type="private_killer_memory",
                    perspective_owner_id=killer_id,
                    confidence_score=5,
                ),
                Belief(
                    belief_id=f"belief-{killer_id}-killer-motive",
                    claim=str(killer_profile.get("motive", "你有必须灭口的理由。")),
                    source="凶手记忆",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id="truth-killer",
                    information_type="fact",
                    source_type="private_killer_memory",
                    perspective_owner_id=killer_id,
                    confidence_score=5,
                ),
                Belief(
                    belief_id=f"belief-{killer_id}-killer-method",
                    claim=str(killer_profile.get("method", "你清楚自己如何实施了谋杀。")),
                    source="凶手记忆",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id="truth-killer",
                    information_type="fact",
                    source_type="private_killer_memory",
                    perspective_owner_id=killer_id,
                    confidence_score=5,
                ),
            ])
            crime_secret_id = f"crime-{killer_id}"
            secrets[crime_secret_id] = SecretState(
                secret_id=crime_secret_id,
                owner_id=killer_id,
                title="陆成之死的真相",
                claim=(
                    f"{killer.display_name}杀死了陆成。"
                    f"动机：{killer_profile.get('motive', '')}"
                    f"手段：{killer_profile.get('method', '')}"
                ),
                category="crime",
                conceal_score=0,
                discovery_score=3,
                exposed_to=[killer_id],
            )
            flags["crime_secret_id"] = crime_secret_id
            for index, claim in enumerate(killer_profile.get("private_facts", []), start=1):
                killer.beliefs.append(Belief(
                    belief_id=f"belief-{killer_id}-killer-case-{index}",
                    claim=str(claim),
                    source="凶手记忆",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id="truth-killer",
                    information_type="fact",
                    source_type="private_killer_memory",
                    perspective_owner_id=killer_id,
                    confidence_score=5,
                ))

            for candidate in killer_candidates:
                candidate_id = candidate["agent_id"]
                if candidate_id == killer_id:
                    continue
                explanation = str(candidate.get("innocent_explanation", "")).strip()
                if explanation:
                    agents[candidate_id].beliefs.append(Belief(
                        belief_id=f"belief-{candidate_id}-innocent-context",
                        claim=explanation,
                        source="个人经历",
                        confidence=1.0,
                        stance="knows",
                        learned_round=0,
                        information_type="fact",
                        source_type="personal_experience",
                        perspective_owner_id=candidate_id,
                        confidence_score=5,
                    ))

            variant_objects = [
                killer_profile.get("stolen_item"),
                *killer_profile.get("evidence_objects", []),
            ]
            for item in variant_objects:
                if not item:
                    continue
                object_id = item["id"]
                holder_id = killer_id if item.get("holder_id") == "$killer" else item.get("holder_id")
                discovered_by = [
                    killer_id if agent_id == "$killer" else agent_id
                    for agent_id in item.get("discovered_by", [])
                ]
                objects[object_id] = ObjectState(
                    object_id=object_id,
                    name=item["name"],
                    location_id=item.get("location_id"),
                    holder_id=holder_id,
                    hidden=bool(item.get("hidden", False)),
                    portable=bool(item.get("portable", True)),
                    discovered_by=discovered_by,
                    tags=list(item.get("tags", [])),
                    metadata={
                        **dict(item.get("metadata", {})),
                        **(
                            {"clue_kind": "truth", "truth_id": "truth-killer"}
                            if item in killer_profile.get("evidence_objects", [])
                            else {}
                        ),
                    },
                    original_location=item.get("location_id"),
                    original_holder=holder_id,
                    authenticity=str(
                        item.get("metadata", {}).get("authenticity", "unknown")
                    ),
                    history=[ItemHistoryEntry(
                        action="initial",
                        round_number=0,
                        from_location=item.get("location_id"),
                        to_location=item.get("location_id"),
                        from_holder=holder_id,
                        to_holder=holder_id,
                        hidden_before=bool(item.get("hidden", False)),
                        hidden_after=bool(item.get("hidden", False)),
                        public=not bool(item.get("hidden", False)),
                        witnesses=discovered_by,
                    )],
                )
                if holder_id in agents and object_id not in agents[holder_id].inventory:
                    agents[holder_id].inventory.append(object_id)
            weapon_id = killer_setup.get("weapon_object_id")
            if weapon_id in objects:
                weapon = objects[weapon_id]
                previous_holder = weapon.holder_id
                if previous_holder in agents and weapon_id in agents[previous_holder].inventory:
                    agents[previous_holder].inventory.remove(weapon_id)
                weapon.transition(
                    "scenario_assign",
                    round_number=0,
                    actor_id=killer_id,
                    holder_id=killer_id,
                    location_id=None,
                    hidden=True,
                    witnesses=[killer_id],
                    public=False,
                )
                weapon.discovered_by = [killer_id]
                if weapon_id not in killer.inventory:
                    killer.inventory.append(weapon_id)
            for agent in agents.values():
                agent.inventory_state["held_items"] = list(agent.inventory)
                agent.information_state["facts"] = list(dict.fromkeys([
                    *agent.information_state.get("facts", []),
                    *(
                        belief.belief_id for belief in agent.beliefs
                        if belief.information_type == "fact"
                    ),
                ]))

        character_timelines, objective_timeline = self._materialize_timelines(
            str((flags.get("case_manifest") or {}).get("case_id") or "")
        )
        flags["character_timelines"] = character_timelines
        flags["objective_timeline"] = objective_timeline
        for agent_id, entries in character_timelines.items():
            agent = agents.get(agent_id)
            if agent is None:
                continue
            for entry in entries:
                agent.beliefs.append(Belief(
                    belief_id=f"belief-{agent_id}-timeline-{entry['id']}",
                    claim=str(entry["text"]),
                    source=f"timeline:{entry['id']}",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id=(
                        "truth-killer"
                        if entry.get("kind") == "killer-private" else None
                    ),
                    perspective_owner_id=agent_id,
                ))

        legacy_max_rounds = int(self.scenario.get("max_rounds", 6))
        legacy_action_limit = int(self.scenario.get("actions_per_round", 3))
        raw_schedule = list(self.scenario.get("round_schedule") or [])
        round_schedule = [
            {
                "round": int(rule["round"]),
                "duration_seconds": int(rule.get("duration_seconds", 0)),
                "major_action_limit": int(
                    rule.get("major_action_limit", legacy_action_limit)
                ),
            }
            for rule in raw_schedule
        ] or [
            {
                "round": round_number,
                "duration_seconds": 0,
                "major_action_limit": legacy_action_limit,
            }
            for round_number in range(1, legacy_max_rounds + 1)
        ]

        return GameState(
            game_id=game_id,
            scenario_id=self.scenario["id"],
            world_id=self.world["id"],
            round_number=0,
            max_rounds=len(round_schedule),
            actions_per_round=int(round_schedule[0]["major_action_limit"]),
            round_schedule=round_schedule,
            player_agent_id=player_agent_id,
            phase=GamePhase.INTERVENTION,
            locations=locations,
            agents=agents,
            objects=objects,
            secrets=secrets,
            flags=flags,
        )

    def _materialize_timelines(
        self,
        active_case_id: str,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """Build six matching personal chronologies from one authored event list."""

        timeline = dict(self.scenario.get("timeline", {}))
        participant_ids = [item["id"] for item in self.scenario.get("participants", [])]
        location_names = {
            item["id"]: item.get("name", item["id"])
            for item in self.world.get("locations", [])
        }
        base_events = [deepcopy(item) for item in timeline.get("events", [])]
        selected_variant = dict(
            (timeline.get("killer_variants", {}) or {}).get(active_case_id, {})
        )
        variant_events = [deepcopy(item) for item in selected_variant.get("events", [])]
        all_events = [*base_events, *variant_events]
        for event in all_events:
            event["location_name"] = location_names.get(
                event.get("location_id"), event.get("location_id", "")
            )
            event["case_id"] = active_case_id if event in variant_events else None
            event["private"] = event.get("kind") == "killer-private"
        all_events.sort(key=lambda item: (int(item.get("order", 0)), str(item.get("id", ""))))
        character_timelines = {
            agent_id: [
                deepcopy(event) for event in all_events
                if agent_id in event.get("participants", [])
            ]
            for agent_id in participant_ids
        }
        return character_timelines, all_events


class ScenarioLoader:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)

    def load(self, scenario_id: str) -> LoadedScenario:
        scenario_path = self.project_root / "data" / "scenarios" / scenario_id / "scenario.json"
        if not scenario_path.is_file():
            raise FileNotFoundError(f"Scenario not found: {scenario_path}")
        scenario = self._read_json(scenario_path)
        self._extend_scenario_list(scenario, scenario_path, "event_cards", "event_cards_file")
        self._extend_scenario_list(scenario, scenario_path, "public_intel", "public_intel_file")
        observations_path = scenario.get("search_observations_file")
        if observations_path:
            extra_path = scenario_path.parent / str(observations_path)
            if not extra_path.is_file():
                raise FileNotFoundError(f"Scenario data file not found: {extra_path}")
            raw_observations = self._read_json(extra_path)
            observations = raw_observations.get("search_observations", raw_observations)
            if not isinstance(observations, dict):
                raise ScenarioValidationError("search_observations_file must contain an object")
            scenario["search_observations"] = observations
        guide_path = scenario.get("player_guide_file")
        if guide_path:
            extra_path = scenario_path.parent / str(guide_path)
            if not extra_path.is_file():
                raise FileNotFoundError(f"Scenario data file not found: {extra_path}")
            raw_guide = self._read_json(extra_path)
            guide = raw_guide.get("player_guide", raw_guide)
            if not isinstance(guide, dict):
                raise ScenarioValidationError("player_guide_file must contain an object")
            scenario["player_guide"] = guide
        behavior_path = scenario.get("behavior_guidelines_file")
        if behavior_path:
            extra_path = (scenario_path.parent / str(behavior_path)).resolve()
            rules_root = (self.project_root / "data" / "rules").resolve()
            if rules_root not in extra_path.parents or not extra_path.is_file():
                raise FileNotFoundError(
                    f"Behavior guidelines file not found under data/rules: {extra_path}"
                )
            scenario["behavior_guidelines"] = {
                "version": 2,
                "source": str(behavior_path),
                "text": extra_path.read_text(encoding="utf-8"),
            }
        assessment_path = scenario.get("final_assessment_file")
        if assessment_path:
            extra_path = scenario_path.parent / str(assessment_path)
            if not extra_path.is_file():
                raise FileNotFoundError(f"Scenario data file not found: {extra_path}")
            raw_assessment = self._read_json(extra_path)
            assessment = raw_assessment.get("final_assessment", raw_assessment)
            if not isinstance(assessment, dict):
                raise ScenarioValidationError("final_assessment_file must contain an object")
            scenario["final_assessment"] = assessment
        timeline_path = scenario.get("timeline_file")
        if timeline_path:
            extra_path = scenario_path.parent / str(timeline_path)
            if not extra_path.is_file():
                raise FileNotFoundError(f"Scenario data file not found: {extra_path}")
            raw_timeline = self._read_json(extra_path)
            timeline = raw_timeline.get("timeline", raw_timeline)
            if not isinstance(timeline, dict):
                raise ScenarioValidationError("timeline_file must contain an object")
            scenario["timeline"] = timeline
        world_id = scenario.get("world_id")
        if not world_id:
            raise ScenarioValidationError("scenario.world_id is required")
        world_path = self.project_root / "data" / "worlds" / world_id / "world.json"
        if not world_path.is_file():
            raise FileNotFoundError(f"World not found: {world_path}")
        world = self._read_json(world_path)
        self.validate(world, scenario)
        return LoadedScenario(world, scenario, world_path, scenario_path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @classmethod
    def _extend_scenario_list(
        cls,
        scenario: dict[str, Any],
        scenario_path: Path,
        list_key: str,
        file_key: str,
    ) -> None:
        relative_path = scenario.get(file_key)
        if not relative_path:
            return
        extra_path = scenario_path.parent / str(relative_path)
        if not extra_path.is_file():
            raise FileNotFoundError(f"Scenario data file not found: {extra_path}")
        with extra_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        extra_items = raw.get(list_key, []) if isinstance(raw, dict) else raw
        if not isinstance(extra_items, list):
            raise ScenarioValidationError(f"{file_key} must contain a list")
        scenario[list_key] = list(scenario.get(list_key, [])) + extra_items

    @staticmethod
    def validate(world: dict[str, Any], scenario: dict[str, Any]) -> None:
        errors: list[str] = []
        if world.get("id") != scenario.get("world_id"):
            errors.append("scenario.world_id does not match world.id")

        raw_schedule = scenario.get("round_schedule")
        if raw_schedule is not None:
            if not isinstance(raw_schedule, list) or not raw_schedule:
                errors.append("scenario.round_schedule must be a non-empty list")
            else:
                expected_rounds = list(range(1, len(raw_schedule) + 1))
                actual_rounds: list[int] = []
                for index, rule in enumerate(raw_schedule, start=1):
                    if not isinstance(rule, dict):
                        errors.append(
                            f"round_schedule entry {index} must be an object"
                        )
                        continue
                    try:
                        round_number = int(rule.get("round", 0))
                        duration = int(rule.get("duration_seconds", 0))
                        action_limit = int(rule.get("major_action_limit", 0))
                    except (TypeError, ValueError):
                        errors.append(
                            f"round_schedule entry {index} contains non-integer values"
                        )
                        continue
                    actual_rounds.append(round_number)
                    if duration <= 0:
                        errors.append(
                            f"round {round_number} duration_seconds must be positive"
                        )
                    if action_limit <= 0:
                        errors.append(
                            f"round {round_number} major_action_limit must be positive"
                        )
                if actual_rounds != expected_rounds:
                    errors.append(
                        "round_schedule rounds must be contiguous and start at 1"
                    )
                configured_max = scenario.get("max_rounds")
                if configured_max is not None and int(configured_max) != len(raw_schedule):
                    errors.append(
                        "scenario.max_rounds must match round_schedule length"
                    )

        locations = world.get("locations") or []
        location_ids = {location.get("id") for location in locations}
        if None in location_ids:
            errors.append("every world location requires an id")
        if len(location_ids) != len(locations):
            errors.append("world location ids must be unique")
        for location in locations:
            layout = location.get("layout", {})
            if layout and not all(key in layout for key in ("floor", "x", "y", "w", "h")):
                errors.append(f"location {location.get('id')} has incomplete layout metadata")
            for connected_id in location.get("connections", []):
                if connected_id not in location_ids:
                    errors.append(
                        f"location {location.get('id')} connects to unknown location {connected_id}"
                    )

        participants = scenario.get("participants") or []
        participant_ids = {participant.get("id") for participant in participants}
        if not 4 <= len(participants) <= 8:
            errors.append("interactive scenarios require 4 to 8 participants")
        if len(participant_ids) != len(participants):
            errors.append("participant ids must be unique")
        llm_scope = scenario.get("llm_scope") or {}
        scoped_participant_list = list(llm_scope.get("participant_ids") or [])
        scoped_participant_ids = set(scoped_participant_list)
        if scoped_participant_list:
            if len(scoped_participant_ids) != len(scoped_participant_list):
                errors.append("llm_scope participant ids must be unique")
            if scoped_participant_ids != participant_ids:
                errors.append(
                    "llm_scope participant ids must exactly match scenario participants"
                )
        for participant in participants:
            if participant.get("start_location") not in location_ids:
                errors.append(
                    f"participant {participant.get('id')} has unknown start_location"
                )

        secrets = scenario.get("secrets") or []
        secret_ids = {item.get("id") for item in secrets}
        if len(secret_ids) != len(secrets):
            errors.append("secret ids must be unique")
        for secret in secrets:
            if secret.get("owner_id") not in participant_ids:
                errors.append(f"secret {secret.get('id')} has unknown owner")

        objects = scenario.get("objects") or []
        object_ids = {item.get("id") for item in objects}
        if len(object_ids) != len(objects):
            errors.append("object ids must be unique")
        for item in objects:
            location_id = item.get("location_id")
            holder_id = item.get("holder_id")
            if bool(location_id) == bool(holder_id):
                errors.append(
                    f"object {item.get('id')} requires exactly one location_id or holder_id"
                )
            if location_id and location_id not in location_ids:
                errors.append(f"object {item.get('id')} has unknown location_id")
            if holder_id and holder_id not in participant_ids:
                errors.append(f"object {item.get('id')} has unknown holder_id")
            secret_id = item.get("metadata", {}).get("reveals_secret_id")
            if secret_id and secret_id not in secret_ids:
                errors.append(f"object {item.get('id')} reveals unknown secret {secret_id}")

        for participant in participants:
            for object_id in participant.get("inventory", []):
                if object_id not in object_ids:
                    errors.append(
                        f"participant {participant.get('id')} carries unknown object {object_id}"
                    )

        cards = scenario.get("event_cards") or []
        card_ids = {card.get("id") for card in cards}
        if len(card_ids) != len(cards):
            errors.append("event card ids must be unique")
        categories = {card.get("category") for card in cards}
        required_categories = {"pressure", "information", "relationship"}
        if not required_categories.issubset(categories):
            errors.append(
                "event cards require pressure, information, and relationship categories"
            )
        for card in cards:
            for effect in card.get("effects", []):
                if effect.get("location_id") and effect["location_id"] not in location_ids:
                    errors.append(f"event card {card.get('id')} references unknown location")
                if effect.get("agent_id") and effect["agent_id"] not in participant_ids:
                    errors.append(f"event card {card.get('id')} references unknown agent")
                if effect.get("object_id") and effect["object_id"] not in object_ids:
                    errors.append(f"event card {card.get('id')} references unknown object")

        public_intel = scenario.get("public_intel") or []
        intel_ids = {item.get("id") for item in public_intel}
        if len(intel_ids) != len(public_intel):
            errors.append("public intel ids must be unique")

        timeline = scenario.get("timeline") or {}
        timeline_events = list(timeline.get("events", []))
        timeline_event_ids: set[str] = set()
        for event in timeline_events:
            event_id = str(event.get("id") or "")
            if not event_id or event_id in timeline_event_ids:
                errors.append("timeline event ids must be present and unique")
            timeline_event_ids.add(event_id)
            if event.get("location_id") not in location_ids:
                errors.append(f"timeline event {event_id} references unknown location")
            event_participants = list(event.get("participants", []))
            if not event_participants or any(
                agent_id not in participant_ids for agent_id in event_participants
            ):
                errors.append(f"timeline event {event_id} has unknown participants")
            if not str(event.get("time") or "").strip() or not str(event.get("text") or "").strip():
                errors.append(f"timeline event {event_id} requires time and text")

        candidates_by_case = {
            str(candidate.get("case_id")): candidate
            for candidate in (scenario.get("killer_setup") or {}).get("candidates", [])
        }
        variants = timeline.get("killer_variants", {}) or {}
        if timeline and set(variants) != set(candidates_by_case):
            errors.append("timeline killer variants must cover every killer case exactly once")
        for case_id, variant in variants.items():
            candidate = candidates_by_case.get(str(case_id), {})
            if variant.get("killer_id") != candidate.get("agent_id"):
                errors.append(f"timeline variant {case_id} has the wrong killer_id")
            for event in variant.get("events", []):
                event_id = str(event.get("id") or "")
                if not event_id or event_id in timeline_event_ids:
                    errors.append("timeline event ids must be present and unique")
                timeline_event_ids.add(event_id)
                if event.get("kind") != "killer-private":
                    errors.append(f"timeline variant {case_id} must contain private killer events")
                if event.get("participants") != [variant.get("killer_id")]:
                    errors.append(f"timeline variant {case_id} may only be visible to its killer")
                if event.get("location_id") not in location_ids:
                    errors.append(f"timeline event {event_id} references unknown location")

        for location_id, observations in scenario.get("search_observations", {}).items():
            if location_id not in location_ids:
                errors.append(f"search observations reference unknown location {location_id}")
            if not isinstance(observations, list) or len(observations) < 3:
                errors.append(f"search observations for {location_id} require at least three entries")

        killer_setup = scenario.get("killer_setup") or {}
        candidates = killer_setup.get("candidates", [])
        candidate_ids = {item.get("agent_id") for item in candidates}
        if candidate_ids and not candidate_ids.issubset(participant_ids):
            errors.append("killer candidates must reference participants")
        weapon_id = killer_setup.get("weapon_object_id")
        if weapon_id and weapon_id not in object_ids:
            errors.append("killer weapon must reference an existing object")
        variant_object_ids: set[str] = set()
        for candidate in candidates:
            case_id = candidate.get("case_id")
            if not case_id:
                errors.append(f"killer candidate {candidate.get('agent_id')} requires case_id")
            variant_objects = [candidate.get("stolen_item"), *candidate.get("evidence_objects", [])]
            for item in variant_objects:
                if not item:
                    continue
                variant_id = item.get("id")
                if not variant_id:
                    errors.append(f"killer case {case_id} contains an object without id")
                    continue
                if variant_id in object_ids or variant_id in variant_object_ids:
                    errors.append(f"killer case object id must be globally unique: {variant_id}")
                variant_object_ids.add(variant_id)
                location_id = item.get("location_id")
                holder_id = item.get("holder_id")
                if bool(location_id) == bool(holder_id):
                    errors.append(
                        f"killer case object {variant_id} requires exactly one location_id or holder_id"
                    )
                if location_id and location_id not in location_ids:
                    errors.append(f"killer case object {variant_id} has unknown location_id")
                if holder_id and holder_id != "$killer" and holder_id not in participant_ids:
                    errors.append(f"killer case object {variant_id} has unknown holder_id")

        triggers = scenario.get("round_triggers") or []
        trigger_ids = {trigger.get("id") for trigger in triggers}
        if len(trigger_ids) != len(triggers):
            errors.append("round trigger ids must be unique")
        for trigger in triggers:
            object_id = trigger.get("conditions", {}).get("object_undiscovered")
            if object_id and object_id not in object_ids:
                errors.append(f"round trigger {trigger.get('id')} references unknown object")
            for effect in trigger.get("effects", []):
                if effect.get("object_id") and effect["object_id"] not in object_ids:
                    errors.append(f"round trigger {trigger.get('id')} references unknown object")
                if effect.get("location_id") and effect["location_id"] not in location_ids:
                    errors.append(f"round trigger {trigger.get('id')} references unknown location")

        if errors:
            raise ScenarioValidationError("Invalid scenario:\n- " + "\n- ".join(errors))
