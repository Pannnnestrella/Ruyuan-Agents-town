"""Agent plan persistence and belief consolidation."""

from __future__ import annotations

from typing import Any

from ..domain.models import ActionIntent, ActionType, AgentState, Belief, EventRecord


PLAN_ACTION_KEYWORDS = {
    "move": ("前往", "移动", "去", "赶往", "到"),
    "investigate": ("调查", "搜查", "搜索", "查看", "勘查", "检查", "搜"),
    "talk": ("交谈", "询问", "试探", "质问", "对话", "打听", "沟通", "求证", "核对"),
    "post_notice": ("公告", "张贴", "布告", "公开"),
    "transfer": ("交给", "交付", "递给", "移交"),
    "poison": ("下毒", "毒"), "treat": ("治疗", "救治", "诊治", "包扎"),
    "wait": ("观察", "等待", "静观", "按兵"),
}


class CognitionService:
    def __init__(self, session: Any):
        self.session = session

    @staticmethod
    def plan_adherence(planned_step: str, action_type: ActionType) -> str:
        step = str(planned_step or "").strip()
        if not step:
            return "unknown"
        if any(keyword in step for keyword in PLAN_ACTION_KEYWORDS.get(action_type.value, ())):
            return "followed"
        return "possibly_deviated"

    def commit_strategic_plans(
        self, intents: list[ActionIntent], events: list[EventRecord],
    ) -> None:
        state = self.session.state
        for intent in intents:
            agent = state.agents.get(intent.actor_id)
            plan = intent.metadata.get("strategic_plan")
            if agent is None or not isinstance(plan, dict) or not plan:
                continue
            outcome_event = next(
                (event for event in reversed(events) if event.actors and event.actors[0] == intent.actor_id),
                None,
            )
            outcome = outcome_event.summary if outcome_event else "本轮意图没有形成可识别的世界事件。"
            previous_steps = [str(step) for step in (agent.strategic_plan.get("steps") or [])]
            previous_step = previous_steps[0] if previous_steps else ""
            execution_status = (
                "no_effect" if outcome_event is None
                else "failed" if outcome_event.event_type == "action_failed"
                else "executed"
            )
            active_round = outcome_event.round_number if outcome_event else state.round_number + 1
            action_step = outcome_event.action_step if outcome_event else state.action_step
            committed = dict(plan)
            committed.update({
                "updated_round": active_round, "updated_action_step": action_step,
                "last_action": intent.action_type.value, "last_outcome": outcome,
                "source": intent.metadata.get("planner_source", committed.get("source", "unknown")),
            })
            agent.strategic_plan = committed
            agent.strategy_state.update({
                "current_goal": committed.get("objective", ""),
                "next_action": (committed.get("steps") or [None])[0],
                "reason": committed.get("revision_reason", ""),
            })
            agent.plan_history.append({
                "round_number": active_round, "action_step": action_step,
                "objective": committed.get("objective", ""),
                "intended_action": intent.action_type.value, "outcome": outcome,
                "execution_status": execution_status, "planned_step": previous_step,
                "plan_adherence": self.plan_adherence(previous_step, intent.action_type),
                "revision_reason": committed.get("revision_reason", ""),
                "source": committed.get("source", "unknown"),
            })
            agent.plan_history = agent.plan_history[-24:]

    def update_beliefs_from_events(self, events: list[EventRecord]) -> None:
        state = self.session.state
        normalize = self.session._normalize_dialogue_text
        for event in events:
            recipients: list[tuple[str, str, float]] = []
            if event.event_type == "discovery" and event.actors:
                recipients.append((event.actors[0], "observed", 1.0))
            elif event.event_type == "conversation":
                speaker = event.payload.get("speaker_id")
                content = event.payload.get("content", "")
                if content:
                    recipients.extend(
                        (witness, "reported", float(event.payload.get("shared_confidence") or 0.65))
                        for witness in event.witnesses if witness != speaker
                    )
                shared_belief_id = event.payload.get("shared_belief_id")
                speaker_state = state.agents.get(speaker)
                shared = next(
                    (belief for belief in speaker_state.beliefs if belief.belief_id == shared_belief_id), None,
                ) if speaker_state and shared_belief_id else None
                if shared:
                    shared.shared_with = list(dict.fromkeys([
                        *shared.shared_with, *(witness for witness in event.witnesses if witness != speaker),
                    ]))
                if speaker_state and content:
                    speaker_state.public_story.setdefault("witnesses_of_each_statement", []).append({
                        "event_id": event.event_id, "content": content,
                        "location_id": event.location_id, "witnesses": list(event.witnesses),
                    })
            elif event.event_type == "final_discussion":
                speaker = event.payload.get("speaker_id")
                if speaker:
                    recipients.append((speaker, "spoken", 1.0))
                recipients.extend((witness, "reported", 0.7) for witness in event.witnesses if witness != speaker)
            elif event.event_type in {
                "poison_effect", "object_transfer", "treatment", "investigation_empty", "wait",
                "object_dropped", "health_changed", "life_state_changed",
                "commitment_fulfilled", "commitment_broken",
            }:
                recipients.extend((witness, "observed", 0.95) for witness in event.witnesses)
            elif event.event_type == "action_failed" and event.actors:
                recipients.append((event.actors[0], "observed", 1.0))

            for agent_id, stance, confidence in recipients:
                agent = state.agents.get(agent_id)
                if agent is None or any(belief.source == event.event_id for belief in agent.beliefs):
                    continue
                speaker_id = event.payload.get("speaker_id")
                if event.event_type in {"conversation", "final_discussion"}:
                    speaker_state = state.agents.get(speaker_id)
                    shared_claim = event.payload.get("shared_claim")
                    claim = (
                        f"我曾在终局公议中说：{event.payload.get('content', '')}"
                        if event.event_type == "final_discussion" and agent_id == speaker_id
                        else f"{speaker_state.display_name if speaker_state else speaker_id}在终局公议中说：{event.payload.get('content', '')}"
                        if event.event_type == "final_discussion"
                        else str(shared_claim)
                        if shared_claim and agent_id != speaker_id
                        else f"据{speaker_state.display_name if speaker_state else speaker_id}所说：{event.payload.get('content', '')}"
                    )
                    truth_id = event.payload.get("shared_truth_id") if shared_claim and agent_id != speaker_id else None
                elif event.event_type == "discovery":
                    claim = str(event.payload.get("clue_claim") or event.summary)
                    revealed_secret = event.payload.get("reveals_secret_id")
                    truth_id = f"secret:{revealed_secret}" if revealed_secret else event.payload.get("truth_id")
                else:
                    claim, truth_id = event.summary, None
                already_shared_with = (
                    [witness for witness in event.witnesses if witness != agent_id]
                    if event.event_type == "conversation" else []
                )
                normalized_claim = normalize(claim)
                duplicate = next(
                    (existing for existing in agent.beliefs[-60:] if normalize(existing.claim) == normalized_claim), None,
                ) if normalized_claim else None
                if duplicate is not None:
                    if confidence > duplicate.confidence:
                        duplicate.confidence = confidence
                        duplicate.stance = stance
                        duplicate.confidence_score = max(
                            duplicate.confidence_score, max(0, min(5, round(confidence * 5))),
                        )
                        if truth_id and not duplicate.truth_id:
                            duplicate.truth_id = truth_id
                    continue
                information_type = "testimony" if event.event_type in {"conversation", "final_discussion"} else "fact"
                belief = Belief(
                    belief_id=f"belief-{agent_id}-{event.event_id}", claim=claim,
                    source=event.event_id, confidence=confidence, stance=stance,
                    learned_round=event.round_number, truth_id=truth_id,
                    shared_with=already_shared_with, information_type=information_type,
                    source_type="direct_statement" if information_type == "testimony" else "observation",
                    speaker_id=str(speaker_id or "") or None, learned_location=event.location_id,
                    witnesses=list(event.witnesses), confidence_score=max(0, min(5, round(confidence * 5))),
                )
                agent.beliefs.append(belief)
                bucket = {"fact": "facts", "testimony": "testimonies", "hypothesis": "hypotheses"}[information_type]
                agent.information_state.setdefault(bucket, []).append(belief.belief_id)
        for agent in state.agents.values():
            self.consolidate_agent_beliefs(agent)

    def consolidate_agent_beliefs(self, agent: AgentState) -> None:
        normalize = self.session._normalize_dialogue_text
        groups: dict[str, list[Belief]] = {}
        for belief in agent.beliefs:
            if belief.truth_id:
                groups.setdefault(f"truth:{belief.truth_id}", []).append(belief)
            normalized = normalize(belief.claim)
            if normalized:
                groups.setdefault(f"claim:{normalized[:120]}", []).append(belief)
        for members in groups.values():
            if len(members) < 2 or len({member.source for member in members}) < 2:
                continue
            member_ids = [member.belief_id for member in members]
            for member in members:
                member.supporting_ids = list(dict.fromkeys([
                    *(belief_id for belief_id in member.supporting_ids if belief_id != member.belief_id),
                    *(belief_id for belief_id in member_ids if belief_id != member.belief_id),
                ]))[:6]
        for belief in agent.beliefs:
            if belief.information_type == "testimony" and not belief.supporting_ids and not belief.verification_questions:
                belief.verification_questions = ["该说法尚无独立旁证；可通过物证或第三方口供核对后再采信。"]
            elif belief.supporting_ids and belief.verification_questions:
                belief.verification_questions = []
