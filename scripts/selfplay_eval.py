"""Batch self-play evaluation for the interactive inn scenario.

Runs N full headless games (heuristic planner by default, or a real LLM
provider), then summarizes the durable history database: killer-found rate,
score distributions, planner fallback rate, answer accuracy, token cost.

Usage:
    python scripts/selfplay_eval.py --games 10
    python scripts/selfplay_eval.py --games 3 --planner deepseek
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.interactive import (
    GamePhase,
    GameService,
    HeuristicIntentPlanner,
    LLMIntentPlanner,
)


def build_planner_factory(provider: str, results_root: Path):
    provider = provider.lower().strip()
    if provider == "heuristic":
        return lambda seed: HeuristicIntentPlanner(seed=seed)
    if provider == "deepseek":
        api_key = (
            os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("DEEPSEEK_API", "")
        )
        return lambda seed: LLMIntentPlanner.from_deepseek(
            api_key,
            fallback=HeuristicIntentPlanner(seed=seed),
            trace_root=results_root,
        )
    if provider == "ollama":
        model = os.environ.get("GA_INTERACTIVE_OLLAMA_MODEL", "qwen2.5:7b-instruct")
        return lambda seed: LLMIntentPlanner.from_ollama(
            model,
            fallback=HeuristicIntentPlanner(seed=seed),
            trace_root=results_root,
        )
    if provider == "project":
        return lambda seed: LLMIntentPlanner.from_project_config(
            ROOT,
            fallback=HeuristicIntentPlanner(seed=seed),
            trace_root=results_root,
        )
    raise ValueError(f"未知 planner:{provider}")


def run_one_game(
    service: GameService,
    *,
    scenario_id: str,
    game_id: str,
    seed: int,
    card_random: random.Random,
) -> dict:
    session = service.create_game(scenario_id, game_id=game_id, seed=seed)
    started = time.time()
    guard = session.state.max_rounds * 4 + 8
    while session.state.phase != GamePhase.FINISHED:
        guard -= 1
        if guard <= 0:
            raise RuntimeError(f"{game_id}: 推进次数超出上限,疑似卡死")
        if not session.state.active_event_card:
            options = list(session.card_suggestions())
            options.append(session.empty_event_option())
            chosen = card_random.choice(options)
            session.select_event_card(chosen["card_id"])
            continue
        session.advance_round()
    voting = dict(session.state.flags.get("voting_result", {}))
    return {
        "game_id": game_id,
        "seed": seed,
        "rounds": session.state.round_number,
        "killer_id": session.state.flags.get("killer_id"),
        "killer_found": bool(voting.get("killer_found")),
        "duration_seconds": round(time.time() - started, 2),
    }


def summarize(database_path: Path, run_game_ids: list[str]) -> dict:
    placeholders = ",".join("?" for _ in run_game_ids)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        games = [
            dict(row) for row in connection.execute(
                f"SELECT * FROM game_runs WHERE game_id IN ({placeholders})",
                run_game_ids,
            )
        ]
        agent_scores = [
            dict(row) for row in connection.execute(
                f"""
                SELECT agent_id,
                       COUNT(*) AS games,
                       AVG(final_score) AS avg_score,
                       SUM(CASE WHEN rank = 1 THEN 1 ELSE 0 END) AS wins
                FROM participant_runs WHERE game_id IN ({placeholders})
                GROUP BY agent_id ORDER BY avg_score DESC
                """,
                run_game_ids,
            )
        ]
        usage = [
            dict(row) for row in connection.execute(
                f"""
                SELECT actual_source, COUNT(*) AS calls
                FROM model_usage WHERE game_id IN ({placeholders})
                GROUP BY actual_source
                """,
                run_game_ids,
            )
        ]
        answers = [
            dict(row) for row in connection.execute(
                f"""
                SELECT question_id,
                       COUNT(*) AS asked,
                       SUM(is_correct) AS correct
                FROM final_answers WHERE game_id IN ({placeholders})
                GROUP BY question_id ORDER BY question_id
                """,
                run_game_ids,
            )
        ]
    finally:
        connection.close()

    total = len(games)
    found = sum(1 for game in games if game.get("killer_found"))
    killers = {}
    for game in games:
        killers[game["killer_id"]] = killers.get(game["killer_id"], 0) + 1
    return {
        "games": total,
        "killer_found": found,
        "killer_found_rate": round(found / total, 3) if total else None,
        "killer_distribution": killers,
        "token_totals": {
            "prompt_tokens": sum(int(g.get("prompt_tokens") or 0) for g in games),
            "completion_tokens": sum(
                int(g.get("completion_tokens") or 0) for g in games
            ),
        },
        "planner_source_calls": {
            row["actual_source"]: row["calls"] for row in usage
        },
        "agent_scores": [
            {
                "agent_id": row["agent_id"],
                "games": row["games"],
                "avg_score": round(float(row["avg_score"]), 2),
                "wins": row["wins"],
            }
            for row in agent_scores
        ],
        "final_answer_accuracy": [
            {
                "question_id": row["question_id"],
                "asked": row["asked"],
                "correct": row["correct"],
                "accuracy": round(row["correct"] / row["asked"], 3),
            }
            for row in answers if row["asked"]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--scenario", default="stormbound_inn")
    parser.add_argument(
        "--planner", default="heuristic",
        choices=["heuristic", "deepseek", "ollama", "project"],
    )
    parser.add_argument("--seed-base", type=int, default=1000)
    parser.add_argument(
        "--results-root", default=str(Path(ROOT) / "results" / "selfplay_eval"),
    )
    args = parser.parse_args()

    results_root = Path(args.results_root)
    results_root.mkdir(parents=True, exist_ok=True)
    service = GameService(
        ROOT,
        results_root=results_root,
        planner_factory=build_planner_factory(args.planner, results_root),
    )
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_game_ids: list[str] = []
    runs: list[dict] = []
    for index in range(args.games):
        seed = args.seed_base + index
        game_id = f"eval-{stamp}-{index:03d}"
        print(f"[{index + 1}/{args.games}] running {game_id} (seed={seed}) ...")
        run = run_one_game(
            service,
            scenario_id=args.scenario,
            game_id=game_id,
            seed=seed,
            card_random=random.Random(seed),
        )
        runs.append(run)
        run_game_ids.append(game_id)
        print(
            f"    done in {run['duration_seconds']}s, "
            f"killer={run['killer_id']}, found={run['killer_found']}"
        )

    database_path = results_root / "interactive" / "history" / "score_history.sqlite3"
    report = {
        "generated_at": stamp,
        "planner": args.planner,
        "scenario": args.scenario,
        "runs": runs,
        "summary": summarize(database_path, run_game_ids),
    }
    report_path = results_root / f"eval-report-{stamp}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print("\n===== 评估摘要 =====")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\n报表已写入 {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
