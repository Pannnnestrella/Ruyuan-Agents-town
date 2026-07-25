"""Turn-based interactive simulation primitives.

This package is intentionally isolated from the legacy batch simulator while the
interactive engine is developed.  Public imports live here so callers do not
need to depend on internal module layout.
"""

from .models import (
    ActionIntent,
    ActionType,
    AgentState,
    Belief,
    ConversationRecord,
    EventCard,
    EventRecord,
    GamePhase,
    GameState,
    LifeState,
    ItemHistoryEntry,
    Notice,
    ObjectState,
    RoundResult,
    SecretState,
)
from .event_director import EventDirector
from .round_engine import RoundEngine
from .recap import RecapBuilder
from .persistence import game_state_from_dict
from .llm_planner import LLMIntentPlanner
from .trigger_resolver import TriggerResolver
from .story_compiler import StoryCompiler
from .scenario_loader import LoadedScenario, ScenarioLoader, ScenarioValidationError
from .service import GameService, GameSession, HeuristicIntentPlanner, IntentPlanner

__all__ = [
    "ActionIntent",
    "ActionType",
    "AgentState",
    "Belief",
    "ConversationRecord",
    "EventCard",
    "EventDirector",
    "EventRecord",
    "GamePhase",
    "GameService",
    "GameSession",
    "GameState",
    "game_state_from_dict",
    "LifeState",
    "ItemHistoryEntry",
    "LLMIntentPlanner",
    "LoadedScenario",
    "Notice",
    "ObjectState",
    "RoundEngine",
    "RecapBuilder",
    "RoundResult",
    "SecretState",
    "ScenarioLoader",
    "ScenarioValidationError",
    "TriggerResolver",
    "StoryCompiler",
    "HeuristicIntentPlanner",
    "IntentPlanner",
]
