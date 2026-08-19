"""Read-only public, observer, and director state projections."""

from __future__ import annotations

from typing import Any

from .models import GamePhase


class StateProjectionService:
    """Build API views without owning or mutating the game session."""

    def __init__(self, session: Any):
        self.session = session

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)

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
