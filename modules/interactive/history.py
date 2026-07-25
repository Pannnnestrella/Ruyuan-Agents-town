"""Durable cross-game scoring and model-usage history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import GameState


SCHEMA = """
CREATE TABLE IF NOT EXISTS game_runs (
    game_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    seed INTEGER NOT NULL,
    killer_id TEXT NOT NULL,
    killer_evaded_vote INTEGER NOT NULL DEFAULT 0,
    killer_found INTEGER NOT NULL,
    started_at TEXT,
    finished_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS participant_runs (
    game_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    controller_type TEXT NOT NULL,
    final_score INTEGER NOT NULL,
    rank INTEGER NOT NULL,
    models_json TEXT NOT NULL,
    PRIMARY KEY (game_id, agent_id)
);
CREATE TABLE IF NOT EXISTS final_answers (
    game_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    submitted_answer TEXT,
    correct_answer TEXT NOT NULL,
    is_correct INTEGER NOT NULL,
    points INTEGER NOT NULL,
    PRIMARY KEY (game_id, agent_id, question_id)
);
CREATE TABLE IF NOT EXISTS score_entries (
    game_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    category TEXT NOT NULL,
    points INTEGER NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (game_id, agent_id, reference_id)
);
CREATE TABLE IF NOT EXISTS model_usage (
    usage_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    action_step INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    actual_source TEXT NOT NULL,
    succeeded INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_participant_agent ON participant_runs(agent_id);
CREATE INDEX IF NOT EXISTS idx_model_usage_agent ON model_usage(agent_id);
CREATE INDEX IF NOT EXISTS idx_answers_question ON final_answers(question_id);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_parts(provider_name: str) -> tuple[str, str]:
    provider, separator, model = str(provider_name or "heuristic").partition(":")
    return provider, model if separator else provider


def record_completed_game(
    results_root: str | Path,
    state: GameState,
    scenario: dict[str, Any],
) -> Path:
    """Upsert one completed game and its audit records in a single transaction."""

    history_dir = Path(results_root) / "interactive" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    database_path = history_dir / "score_history.sqlite3"
    voting_result = dict(state.flags.get("voting_result", {}))
    ranked = sorted(state.agents.values(), key=lambda item: (-item.score, item.agent_id))
    ranks = {agent.agent_id: index + 1 for index, agent in enumerate(ranked)}

    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(SCHEMA)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(game_runs)")
        }
        if "killer_evaded_vote" not in columns:
            connection.execute(
                "ALTER TABLE game_runs ADD COLUMN killer_evaded_vote INTEGER NOT NULL DEFAULT 0"
            )
        values = (
            state.game_id,
            state.scenario_id,
            int(state.flags.get("seed", 0)),
            str(state.flags.get("killer_id", "")),
            int(not bool(voting_result.get("killer_found"))),
            int(bool(voting_result.get("killer_found"))),
            str(state.flags.get("created_at", "")) or None,
            _utc_now(),
        )
        if "killer_escaped" in columns:
            # Compatibility with databases created before physical escape was removed.
            connection.execute(
                """
                INSERT OR REPLACE INTO game_runs
                (game_id, scenario_id, seed, killer_id, killer_evaded_vote,
                 killer_found, started_at, finished_at, killer_escaped)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                values,
            )
        else:
            connection.execute(
                """
                INSERT OR REPLACE INTO game_runs
                (game_id, scenario_id, seed, killer_id, killer_evaded_vote,
                 killer_found, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        for agent in ranked:
            usage = [
                item for item in state.model_usage
                if item.get("agent_id") == agent.agent_id
            ]
            models = sorted({
                str(item.get("provider_name", "heuristic"))
                for item in usage
            }) or ["human" if state.player_agent_id == agent.agent_id else "heuristic"]
            connection.execute(
                """
                INSERT OR REPLACE INTO participant_runs
                (game_id, agent_id, controller_type, final_score, rank, models_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    state.game_id,
                    agent.agent_id,
                    "human" if state.player_agent_id == agent.agent_id else "ai",
                    int(agent.score),
                    ranks[agent.agent_id],
                    json.dumps(models, ensure_ascii=False),
                ),
            )
            for score in agent.score_breakdown:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO score_entries
                    (game_id, agent_id, reference_id, category, points, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.game_id,
                        agent.agent_id,
                        str(score.get("reference_id", "")),
                        str(score.get("category", "")),
                        int(score.get("points", 0)),
                        str(score.get("reason", "")),
                    ),
                )
        for agent_id, submission in state.final_submissions.items():
            for answer in submission.get("answer_results", []):
                connection.execute(
                    """
                    INSERT OR REPLACE INTO final_answers
                    (game_id, agent_id, question_id, submitted_answer, correct_answer, is_correct, points)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.game_id,
                        agent_id,
                        str(answer.get("question_id", "")),
                        None if answer.get("submitted_answer") is None else str(answer.get("submitted_answer")),
                        str(answer.get("correct_answer", "")),
                        int(bool(answer.get("is_correct"))),
                        int(answer.get("points", 0)),
                    ),
                )
        for usage in state.model_usage:
            provider, model = _provider_parts(str(usage.get("provider_name", "heuristic")))
            connection.execute(
                """
                INSERT OR REPLACE INTO model_usage
                (usage_id, game_id, agent_id, stage, round_number, action_step,
                 provider, model, actual_source, succeeded)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(usage.get("usage_id")),
                    state.game_id,
                    str(usage.get("agent_id", "")),
                    str(usage.get("stage", "")),
                    int(usage.get("round_number", 0)),
                    int(usage.get("action_step", 0)),
                    provider,
                    model,
                    str(usage.get("actual_source", "")),
                    int(bool(usage.get("succeeded", True))),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return database_path
