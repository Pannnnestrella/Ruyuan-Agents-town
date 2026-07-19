"""Evidence-based recap artifacts for completed interactive games."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import GameState
from .scenario_loader import LoadedScenario


class RecapBuilder:
    IMPORTANT_EVENT_TYPES = {
        "attack",
        "attack_failed",
        "discovery",
        "object_transfer",
        "object_hidden",
        "treatment",
        "public_fact",
        "event_card_selected",
        "notice_posted",
        "public_intel",
        "escape",
        "escape_failed",
        "vote_cast",
        "killer_revealed",
        "conversation",
        "move",
    }

    def build(self, loaded: LoadedScenario, state: GameState) -> dict[str, Any]:
        timeline: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for event in state.events:
            timeline[event.round_number].append(event.to_dict())

        characters = []
        for agent in state.agents.values():
            characters.append({
                "agent_id": agent.agent_id,
                "display_name": agent.display_name,
                "life_state": agent.life_state.value,
                "health": agent.health,
                "final_location": state.locations[agent.location_id]["name"],
                "conditions": list(agent.conditions),
                "inventory": [state.objects[item_id].name for item_id in agent.inventory],
                "belief_count": len(agent.beliefs),
                "final_beliefs": [belief.to_dict() for belief in agent.beliefs[-8:]],
                "strategic_plan": dict(agent.strategic_plan),
                "plan_history": list(agent.plan_history),
                "score": agent.score,
                "score_breakdown": list(agent.score_breakdown),
                "discovered_secrets": [
                    state.secrets[secret_id].title
                    for secret_id in agent.discovered_secret_ids
                    if secret_id in state.secrets
                ],
                "owned_secrets": [
                    {
                        "title": secret.title,
                        "exposed_to": [
                            state.agents[agent_id].display_name
                            for agent_id in secret.exposed_to
                            if agent_id != secret.owner_id and agent_id in state.agents
                        ],
                    }
                    for secret in state.secrets.values()
                    if secret.owner_id == agent.agent_id and secret.category == "personal"
                ],
            })

        notices = []
        for notice in state.notices:
            notices.append({
                **notice.to_dict(),
                "reach": len(notice.seen_by),
                "participant_count": len(state.agents),
            })

        key_events = [
            event.to_dict()
            for event in state.events
            if event.event_type in self.IMPORTANT_EVENT_TYPES
        ]
        objective_truths = list(loaded.scenario.get("truths", []))
        killer_id = state.flags.get("killer_id")
        killer = state.agents.get(killer_id) if killer_id else None
        if killer:
            profile = state.flags.get("killer_profile", {})
            manifest = state.flags.get("case_manifest", {})
            stolen_id = manifest.get("stolen_item_id")
            stolen = state.objects.get(stolen_id) if stolen_id else None
            evidence_names = [
                state.objects[object_id].name
                for object_id in manifest.get("evidence_object_ids", [])
                if object_id in state.objects
            ]
            case_details = []
            if stolen:
                case_details.append(f"失踪关键物是{stolen.name}")
            if evidence_names:
                case_details.append(f"本变体专属痕迹为{'、'.join(evidence_names)}")
            objective_truths.append({
                "id": "truth-killer-reveal",
                "case_id": manifest.get("case_id"),
                "claim": (
                    f"本局凶手是{killer.display_name}。"
                    f"{profile.get('motive', '')} {profile.get('method', '')} "
                    f"{'；'.join(case_details)}。"
                ).strip(),
                "author_only": True,
            })
        return {
            "game_id": state.game_id,
            "scenario_id": state.scenario_id,
            "title": loaded.scenario["title"],
            "premise": loaded.scenario["premise"],
            "rounds_completed": state.round_number,
            "actions_per_round": state.actions_per_round,
            "objective_truths": objective_truths,
            "timeline": {str(round_number): events for round_number, events in sorted(timeline.items())},
            "key_events": key_events,
            "characters": characters,
            "player_notices": notices,
            "event_cards_used": list(state.used_event_cards),
            "public_intel": list(state.public_intel_history),
            "voting_result": dict(state.flags.get("voting_result", {})),
            "ending_questions": list(loaded.scenario.get("ending_questions", [])),
        }

    def to_markdown(self, recap: dict[str, Any]) -> str:
        lines = [
            f"# {recap['title']}·推演复盘",
            "",
            recap["premise"],
            "",
            f"- 游戏编号：`{recap['game_id']}`",
            f"- 完成轮数：{recap['rounds_completed']}",
            f"- 事件卡：{len(recap['event_cards_used'])} 张",
            "",
            "## 客观真相",
            "",
        ]
        for truth in recap["objective_truths"]:
            lines.append(f"- {truth['claim']}")

        lines.extend(["", "## 玩家干预", ""])
        if recap["player_notices"]:
            for notice in recap["player_notices"]:
                lines.append(
                    f"- 第 {notice['round_number']} 轮，{notice['display_author']}发布“{notice['content']}”"
                    f"（{notice['reach']}/{notice['participant_count']} 名角色看到）"
                )
        else:
            lines.append("- 玩家没有发布公告。")

        lines.extend(["", "## 全局公开情报", ""])
        if recap.get("public_intel"):
            for intel in recap["public_intel"]:
                lines.append(
                    f"- 第 {intel['round_number']} 轮，“{intel['title']}”（{intel['source']}）：{intel['claim']}"
                )
        else:
            lines.append("- 本局没有广播公开情报。")

        lines.extend(["", "## 六轮十八次行动时间线", ""])
        for round_number, events in recap["timeline"].items():
            lines.append(f"### 第 {round_number} 轮")
            lines.append("")
            important = [event for event in events if event["event_type"] in self.IMPORTANT_EVENT_TYPES]
            selected = important or events
            for event in selected:
                visibility = "公开" if event["public"] else "隐秘"
                step = f"行动 {event.get('action_step')} · " if event.get("action_step") else ""
                lines.append(f"- [{visibility}] {step}{event['summary']}")
            lines.append("")

        voting = recap.get("voting_result", {})
        lines.extend(["## 终局投票", ""])
        if voting.get("votes"):
            for vote in voting["votes"]:
                lines.append(
                    f"- {vote['voter_name']} → {vote['suspect_name']}：{vote['reason']}"
                )
            lines.extend([
                "",
                f"- 真实凶手：{voting.get('killer_name', '未知')}",
                f"- 结果：{voting.get('outcome', '')}",
            ])
        else:
            lines.append("- 本局没有形成投票结果。")

        lines.extend(["", "## 人物结局", ""])
        for character in recap["characters"]:
            conditions = "、".join(character["conditions"]) or "无"
            inventory = "、".join(character["inventory"]) or "无"
            lines.extend([
                f"### {character['display_name']}",
                "",
                f"- 生命状态：{character['life_state']}（体力 {character['health']}）",
                f"- 最终地点：{character['final_location']}",
                f"- 状态影响：{conditions}",
                f"- 最终持有：{inventory}",
                f"- 最终得分：{character.get('score', 0)}",
            ])
            for score in character.get("score_breakdown", []):
                sign = "+" if score.get("points", 0) >= 0 else ""
                lines.append(f"  - {sign}{score.get('points', 0)}：{score.get('reason', '')}")
            if character.get("plan_history"):
                objectives = []
                for item in character["plan_history"]:
                    objective = item.get("objective", "")
                    if objective and objective not in objectives:
                        objectives.append(objective)
                lines.append(f"- 计划演变：{' → '.join(objectives[-4:]) or '无明确变化'}")
            lines.append("")

        lines.extend(["## 尚待回答", ""])
        for question in recap["ending_questions"]:
            lines.append(f"- {question}")
        lines.append("")
        lines.append("> 本文档严格依据结构化事件生成，不补写模拟中没有发生的行为。")
        lines.append("")
        return "\n".join(lines)
