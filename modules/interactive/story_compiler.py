"""Compile a factual three-act story outline from an evidence recap."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


class StoryCompiler:
    ACTS = (
        ("第一幕·封锁与试探", 0.0, 0.34),
        ("第二幕·秘密与误判", 0.34, 0.7),
        ("第三幕·逼近与决断", 0.7, 1.01),
    )
    STORY_EVENT_TYPES = {
        "event_card_selected",
        "world_trigger",
        "public_fact",
        "notice_posted",
        "discovery",
        "conversation",
        "object_transfer",
        "evidence_lost",
        "poison_effect",
        "treatment",
        "move",
        "public_intel",
        "vote_cast",
        "killer_revealed",
    }

    def compile(self, recap: dict[str, Any]) -> dict[str, Any]:
        max_rounds = max(1, int(recap["rounds_completed"]))
        all_events = [
            event
            for events in recap["timeline"].values()
            for event in events
        ]
        story_events = [
            event for event in all_events
            if event["event_type"] in self.STORY_EVENT_TYPES
        ]
        acts = []
        for title, start_ratio, end_ratio in self.ACTS:
            start_round = 0 if start_ratio == 0 else int(max_rounds * start_ratio) + 1
            end_round = max(start_round, int(max_rounds * end_ratio))
            if end_ratio > 1:
                end_round = max_rounds
            events = [
                self._event_reference(event)
                for event in story_events
                if start_round <= int(event["round_number"]) <= end_round
            ]
            acts.append({
                "title": title,
                "start_round": start_round,
                "end_round": end_round,
                "events": events,
            })

        threads: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in story_events:
            for actor_id in event.get("actors", []):
                threads[actor_id].append(self._event_reference(event))
        character_names = {
            character["agent_id"]: character["display_name"]
            for character in recap["characters"]
        }
        character_threads = [
            {
                "agent_id": agent_id,
                "display_name": character_names.get(agent_id, agent_id),
                "events": events,
                "final_state": next(
                    character for character in recap["characters"]
                    if character["agent_id"] == agent_id
                ),
            }
            for agent_id, events in sorted(threads.items())
        ]
        # Characters who never entered a story event are still represented so
        # the absence itself is visible to the author during balancing.
        threaded_ids = {thread["agent_id"] for thread in character_threads}
        for character in recap["characters"]:
            if character["agent_id"] not in threaded_ids:
                character_threads.append({
                    "agent_id": character["agent_id"],
                    "display_name": character["display_name"],
                    "events": [],
                    "final_state": character,
                })

        return {
            "game_id": recap["game_id"],
            "title": recap["title"],
            "logline": recap["premise"],
            "acts": acts,
            "character_threads": character_threads,
            "player_interventions": [
                {
                    "notice_id": notice["notice_id"],
                    "round_number": notice["round_number"],
                    "content": notice["content"],
                    "reach": notice["reach"],
                }
                for notice in recap["player_notices"]
            ],
            "unresolved_questions": recap["ending_questions"],
            "source_event_ids": [event["event_id"] for event in story_events],
        }

    @staticmethod
    def _event_reference(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event["event_id"],
            "round_number": event["round_number"],
            "event_type": event["event_type"],
            "summary": event["summary"],
            "actors": list(event.get("actors", [])),
            "public": bool(event.get("public", False)),
        }

    def to_markdown(self, outline: dict[str, Any]) -> str:
        lines = [
            f"# {outline['title']}·故事编排",
            "",
            f"> {outline['logline']}",
            "",
            "本编排只重组模拟中实际记录的事件，不补写新的事实。每个条目保留来源事件 ID，供作者返回复盘核对。",
            "",
        ]
        for act in outline["acts"]:
            lines.extend([
                f"## {act['title']}",
                "",
                f"覆盖第 {act['start_round']}—{act['end_round']} 轮。",
                "",
            ])
            if act["events"]:
                for event in act["events"]:
                    lines.append(
                        f"- 第 {event['round_number']} 轮：{event['summary']} `[{event['event_id']}]`"
                    )
            else:
                lines.append("- 这一幕没有形成可识别的关键事件，需要检查节奏或角色参与度。")
            lines.append("")

        lines.extend(["## 人物行动线", ""])
        for thread in outline["character_threads"]:
            final_state = thread["final_state"]
            lines.extend([
                f"### {thread['display_name']}",
                "",
                f"结局：{final_state['life_state']}，位于{final_state['final_location']}。",
                "",
            ])
            if thread["events"]:
                for event in thread["events"]:
                    lines.append(
                        f"- 第 {event['round_number']} 轮：{event['summary']} `[{event['event_id']}]`"
                    )
            else:
                lines.append("- 没有进入关键事件线；这通常意味着角色参与度不足。")
            lines.append("")

        lines.extend(["## 玩家留下的推动力", ""])
        if outline["player_interventions"]:
            for notice in outline["player_interventions"]:
                lines.append(
                    f"- 第 {notice['round_number']} 轮公告：“{notice['content']}”"
                    f"（触达 {notice['reach']} 人）"
                )
        else:
            lines.append("- 玩家没有发布公告。")
        lines.extend(["", "## 尚未闭合的故事问题", ""])
        for question in outline["unresolved_questions"]:
            lines.append(f"- {question}")
        lines.append("")
        return "\n".join(lines)
