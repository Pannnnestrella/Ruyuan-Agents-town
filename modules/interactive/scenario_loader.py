"""Load and validate reusable world packs and scenario packages."""

from __future__ import annotations

import json
import random
import uuid
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import AgentState, Belief, GamePhase, GameState, ObjectState, SecretState


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
                    ))
            agents[participant["id"]] = AgentState(
                agent_id=participant["id"],
                display_name=participant.get("display_name", participant["id"]),
                location_id=participant["start_location"],
                health=int(participant.get("health", 100)),
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
                ))

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
                ))

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
            )

        for agent in agents.values():
            for object_id in agent.inventory:
                objects[object_id].holder_id = agent.agent_id
                objects[object_id].location_id = None

        flags = dict(self.scenario.get("initial_flags", {}))
        flags["seed"] = seed
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
                "escape_plan": killer_profile.get("escape_plan", ""),
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
                "killer_escaped": False,
                "voting_complete": False,
                "scores_finalized": False,
            })
            killer = agents[killer_id]
            killer.beliefs.extend([
                Belief(
                    belief_id=f"belief-{killer_id}-killer-role",
                    claim="你就是杀死陆成的凶手。其他五人不知道你的身份，你必须隐藏作案信息并设法逃离客栈。",
                    source="凶手记忆",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id="truth-killer",
                ),
                Belief(
                    belief_id=f"belief-{killer_id}-killer-motive",
                    claim=str(killer_profile.get("motive", "你有必须灭口的理由。")),
                    source="凶手记忆",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id="truth-killer",
                ),
                Belief(
                    belief_id=f"belief-{killer_id}-killer-method",
                    claim=str(killer_profile.get("method", "你清楚自己如何实施了谋杀。")),
                    source="凶手记忆",
                    confidence=1.0,
                    stance="knows",
                    learned_round=0,
                    truth_id="truth-killer",
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
                )
                if holder_id in agents and object_id not in agents[holder_id].inventory:
                    agents[holder_id].inventory.append(object_id)
            weapon_id = killer_setup.get("weapon_object_id")
            if weapon_id in objects:
                weapon = objects[weapon_id]
                previous_holder = weapon.holder_id
                if previous_holder in agents and weapon_id in agents[previous_holder].inventory:
                    agents[previous_holder].inventory.remove(weapon_id)
                weapon.holder_id = killer_id
                weapon.location_id = None
                weapon.hidden = True
                weapon.discovered_by = [killer_id]
                if weapon_id not in killer.inventory:
                    killer.inventory.append(weapon_id)

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
                ))

        return GameState(
            game_id=game_id,
            scenario_id=self.scenario["id"],
            world_id=self.world["id"],
            round_number=0,
            max_rounds=int(self.scenario.get("max_rounds", 6)),
            actions_per_round=int(self.scenario.get("actions_per_round", 3)),
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
