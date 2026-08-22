"""Game-session registry for the interactive application."""

from __future__ import annotations

import json
import hashlib
import re
import secrets as token_secrets
import uuid
from pathlib import Path
from typing import Callable

from ..infrastructure.persistence import game_state_from_dict
from ..infrastructure.scenario_loader import ScenarioLoader
from ..planning.heuristic import IntentPlanner
from .service import GameSession

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
        session.start_quiet_player_round()
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
        session.start_quiet_player_round()
        self.sessions[game_id] = session
        return session
