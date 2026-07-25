"""Character-specific action permissions and mechanical modifiers."""

from __future__ import annotations

from typing import Any

from .models import ActionIntent, ActionType, GameState


CHARACTER_ABILITIES: dict[str, dict[str, Any]] = {
    "广陵王": {
        "ability_id": "innkeeper_aid",
        "label": "楼主调度",
        "action_type": "treat",
        "description": "调动绣衣楼随行药物，为自己或同室受伤的角色完成救治，使其恢复健康。",
        "full_restore": True,
    },
    "傅融": {
        "ability_id": "ledger_trace",
        "label": "账痕追索",
        "action_type": "investigate",
        "description": "搜查时优先辨认账页、文书和钱物流向。",
        "search_tags": ["ledger", "document", "financial"],
    },
    "刘辩": {
        "ability_id": "court_appraisal",
        "label": "宫制辨伪",
        "action_type": "investigate",
        "description": "搜查时优先辨认宫制、身份和伪造文书。",
        "search_tags": ["identity", "document", "palace"],
    },
    "左慈": {
        "ability_id": "toxin_diagnosis",
        "label": "辨毒验伤",
        "action_type": "investigate",
        "description": "搜查时优先辨认毒物、药理和尸身痕迹。",
        "search_tags": ["poison", "medical", "body"],
    },
}

KILLER_ABILITY: dict[str, Any] = {
    "ability_id": "killer_poison",
    "label": "秘密下毒",
    "action_type": "poison",
    "description": "凶手专属：每轮至多一次，秘密对同室角色下毒；行动本身无人得知，毒性在下一轮发作。",
    "success_chance": 0.76,
    "first_hit_state": "injured",
    "condition": "中毒",
    "hidden": True,
}


def abilities_for(state: GameState, actor_id: str) -> list[dict[str, Any]]:
    """Return only abilities the actor themself may use."""

    abilities: list[dict[str, Any]] = []
    if actor_id == state.flags.get("killer_id"):
        abilities.append(dict(KILLER_ABILITY))
    character = CHARACTER_ABILITIES.get(actor_id)
    if character and not (
        actor_id == state.flags.get("killer_id")
        and character["action_type"] == KILLER_ABILITY["action_type"]
    ):
        abilities.append(dict(character))
    return abilities


def ability_for_action(
    state: GameState,
    actor_id: str,
    action_type: ActionType,
) -> dict[str, Any] | None:
    return next(
        (
            ability for ability in abilities_for(state, actor_id)
            if ability["action_type"] == action_type.value
        ),
        None,
    )


def ability_by_id(
    state: GameState,
    actor_id: str,
    ability_id: str,
) -> dict[str, Any] | None:
    return next(
        (
            ability for ability in abilities_for(state, actor_id)
            if ability["ability_id"] == ability_id
        ),
        None,
    )


def apply_ability(
    state: GameState,
    intent: ActionIntent,
    ability_id: str | None = None,
) -> dict[str, Any] | None:
    """Attach server-owned modifiers; client/model values never control odds."""

    ability = (
        ability_by_id(state, intent.actor_id, ability_id)
        if ability_id
        else ability_for_action(state, intent.actor_id, intent.action_type)
    )
    if not ability:
        return None
    if ability["action_type"] != intent.action_type.value:
        return None
    intent.metadata.update({
        key: value for key, value in ability.items()
        if key not in {"label", "description", "hidden", "action_type"}
    })
    intent.metadata["ability_id"] = ability["ability_id"]
    intent.metadata["ability_label"] = ability["label"]
    return ability


def action_is_authorized(state: GameState, intent: ActionIntent) -> bool:
    """Poisoning and treatment exist only through a matching character ability."""

    if intent.action_type not in {ActionType.POISON, ActionType.TREAT}:
        return True
    return ability_for_action(state, intent.actor_id, intent.action_type) is not None
