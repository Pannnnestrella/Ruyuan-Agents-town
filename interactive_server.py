"""Web entry point for the turn-based interactive simulation prototype."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from modules.interactive import GamePhase, GameService, HeuristicIntentPlanner, LLMIntentPlanner


PROJECT_ROOT = Path(__file__).resolve().parent


def create_app(
    project_root: str | Path = PROJECT_ROOT,
    *,
    results_root: str | Path | None = None,
    planner_mode: str | None = None,
) -> Flask:
    root = Path(project_root)
    app = Flask(
        __name__,
        template_folder=str(root / "frontend" / "templates"),
        static_folder=str(root / "frontend" / "static"),
        static_url_path="/static",
    )
    # This is a local authoring prototype: HTML/CSS/JS change frequently while the
    # server stays open.  Always revalidate assets and templates so the browser
    # cannot combine an older page with a newer script.
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    planner_mode = (planner_mode or os.environ.get("GA_INTERACTIVE_PLANNER", "auto")).lower()
    llm_provider = os.environ.get("GA_INTERACTIVE_LLM_PROVIDER", "deepseek").lower()
    host_notifications: deque[dict[str, Any]] = deque(maxlen=200)
    notification_lock = threading.Lock()
    notification_sequence = 0

    def record_host_notification(
        error: Exception | str,
        *,
        source: str,
        game_id: str | None = None,
        provider: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Record a safe, host-only diagnostic without interrupting fallback."""

        nonlocal notification_sequence
        message = str(error).strip() or type(error).__name__
        status_code = getattr(error, "status_code", None)
        if status_code is None:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)
        is_rate_limit = status_code == 429 or "429" in message or "rate limit" in message.lower()
        safe_context = {
            str(key)[:80]: str(value)[:240]
            for key, value in (context or {}).items()
            if key not in {"api_key", "authorization", "prompt"}
        }
        signature = (source, game_id, provider, status_code, type(error).__name__, message[:240])
        now = time.time()
        with notification_lock:
            if host_notifications:
                latest = host_notifications[-1]
                if latest.get("_signature") == signature and now - latest["_created_epoch"] < 10:
                    latest["count"] += 1
                    latest["created_at"] = datetime.now(timezone.utc).isoformat()
                    latest["_created_epoch"] = now
                    return
            notification_sequence += 1
            host_notifications.append({
                "id": notification_sequence,
                "level": "error",
                "kind": "rate_limit" if is_rate_limit else "exception",
                "title": "模型接口限流（HTTP 429）" if is_rate_limit else "系统异常",
                "message": message[:800],
                "exception_type": type(error).__name__,
                "status_code": status_code,
                "source": source,
                "provider": provider or "",
                "game_id": game_id or "",
                "context": safe_context,
                "count": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "_created_epoch": now,
                "_signature": signature,
            })

    def planner_error_callback(error: Exception, context: dict[str, Any]) -> None:
        record_host_notification(
            error,
            source="llm_planner",
            provider=str(context.get("provider", "")),
            context=context,
        )

    # Raw prompt/response audit trail per game; set GA_INTERACTIVE_LLM_TRACE=0
    # to disable.
    llm_trace_root = (
        Path(results_root) if results_root else root / "results"
    ) if os.environ.get("GA_INTERACTIVE_LLM_TRACE", "1") != "0" else None

    def build_planner(seed: int, provider: str, model: str = ""):
        fallback = HeuristicIntentPlanner(seed=seed)
        provider = provider.lower().strip()
        if provider == "heuristic":
            return fallback
        if provider == "ollama":
            return LLMIntentPlanner.from_ollama(
                model.strip() or os.environ.get(
                    "GA_INTERACTIVE_OLLAMA_MODEL", "qwen2.5:7b-instruct"
                ),
                fallback=fallback,
                error_callback=planner_error_callback,
                trace_root=llm_trace_root,
            )
        if provider == "deepseek":
            return LLMIntentPlanner.from_deepseek(
                # DEEPSEEK_API_KEY is the name used in DeepSeek's official
                # OpenAI-compatible SDK examples. Keep the historical project
                # variable as a fallback so existing local installations work.
                os.environ.get("DEEPSEEK_API_KEY")
                or os.environ.get("DEEPSEEK_API", ""),
                model_name=model.strip() or os.environ.get(
                    "GA_INTERACTIVE_DEEPSEEK_MODEL", "deepseek-v4-flash"
                ),
                base_url=os.environ.get(
                    "GA_INTERACTIVE_DEEPSEEK_BASE_URL", "https://api.deepseek.com"
                ),
                fallback=fallback,
                error_callback=planner_error_callback,
                trace_root=llm_trace_root,
            )
        if provider == "project":
            return LLMIntentPlanner.from_project_config(
                root,
                fallback=fallback,
                error_callback=planner_error_callback,
                trace_root=llm_trace_root,
            )
        raise ValueError("未知决策接口；请选择 heuristic、ollama、deepseek 或 project")

    def planner_factory(seed: int):
        fallback = HeuristicIntentPlanner(seed=seed)
        if planner_mode in {"auto", "llm"}:
            try:
                return build_planner(seed, llm_provider)
            except Exception as error:
                if planner_mode == "llm":
                    raise
                record_host_notification(
                    error,
                    source="planner_initialization",
                    provider=llm_provider,
                )
                print(f"[interactive] LLM planner unavailable, using heuristic planner: {error}")
        return fallback

    service = GameService(
        root,
        results_root=results_root,
        planner_factory=planner_factory,
    )
    app.config["INTERACTIVE_GAME_SERVICE"] = service
    app.config["INTERACTIVE_HOST_NOTIFY"] = record_host_notification
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="interactive-round")
    tasks: dict[str, dict[str, Any]] = {}
    active_game_tasks: dict[str, str] = {}
    task_lock = threading.Lock()
    app.config["INTERACTIVE_ROUND_TASKS"] = tasks

    def game_service() -> GameService:
        return app.config["INTERACTIVE_GAME_SERVICE"]

    def payload() -> dict[str, Any]:
        return request.get_json(silent=True) or {}

    def queue_game_operation(
        game_id: str,
        *,
        initial_message: str,
        total: int,
        operation: Any,
    ):
        with task_lock:
            if game_id in active_game_tasks:
                raise ValueError("A simulation step is already being resolved for this game")
            task_id = f"player-task-{uuid.uuid4().hex[:12]}"
            tasks[task_id] = {
                "task_id": task_id,
                "game_id": game_id,
                "status": "queued",
                "message": initial_message,
                "progress": {
                    "stage": "queued",
                    "completed": 0,
                    "total": total,
                    "agents": {},
                },
                "result": None,
                "error": None,
            }
            active_game_tasks[game_id] = task_id

        def run_operation():
            with task_lock:
                tasks[task_id]["status"] = "running"
                tasks[task_id]["message"] = initial_message

            def report_progress(update: dict[str, Any]):
                with task_lock:
                    progress = tasks[task_id]["progress"]
                    progress["stage"] = update.get("stage", "intent")
                    progress["completed"] = int(update.get("completed", 0))
                    progress["total"] = int(update.get("total", progress.get("total", 0)))
                    progress["agents"][str(update.get("agent_id", ""))] = {
                        "display_name": update.get("display_name", update.get("agent_id", "")),
                        "status": update.get("status", "completed"),
                        "source": update.get("source", "unknown"),
                    }
                    stage = (
                        "终局投票" if progress["stage"] == "vote"
                        else "对方正在回应" if progress["stage"] == "conversation_reply"
                        else "其他密探决策"
                    )
                    tasks[task_id]["message"] = (
                        f"{stage}：{progress['completed']}/{progress['total']} 已完成"
                    )
            try:
                result = operation(report_progress)
                with task_lock:
                    tasks[task_id]["status"] = "succeeded"
                    tasks[task_id]["message"] = "角色行动已经写入世界"
                    tasks[task_id]["result"] = result
            except Exception as error:
                record_host_notification(
                    error,
                    source="background_game_operation",
                    game_id=game_id,
                )
                with task_lock:
                    tasks[task_id]["status"] = "failed"
                    tasks[task_id]["message"] = "角色行动结算失败"
                    tasks[task_id]["error"] = str(error)
            finally:
                with task_lock:
                    active_game_tasks.pop(game_id, None)

        executor.submit(run_operation)
        return jsonify({"task_id": task_id, "status": "queued"}), 202

    @app.get("/")
    @app.get("/interactive")
    def interactive_live_page():
        return render_template("interactive_live.html")

    @app.get("/interactive/director")
    def interactive_director_page():
        return render_template("interactive.html")

    @app.get("/api/interactive/scenarios")
    def list_scenarios():
        scenarios_root = root / "data" / "scenarios"
        scenarios = []
        if scenarios_root.is_dir():
            for path in sorted(scenarios_root.iterdir()):
                try:
                    loaded = game_service().loader.load(path.name)
                except (FileNotFoundError, ValueError):
                    continue
                scenarios.append({
                    "id": loaded.scenario["id"],
                    "title": loaded.scenario["title"],
                    "premise": loaded.scenario["premise"],
                    "participant_count": len(loaded.scenario["participants"]),
                    "max_rounds": loaded.scenario.get("max_rounds", 6),
                    "actions_per_round": loaded.scenario.get("actions_per_round", 3),
                    "participants": [
                        {
                            "id": item["id"],
                            "name": item.get("display_name", item["id"]),
                            "public_role": item.get("public_role", ""),
                        }
                        for item in loaded.scenario["participants"]
                    ],
                })
        return jsonify({"scenarios": scenarios})

    @app.get("/api/interactive/host-notifications")
    def get_host_notifications():
        after = request.args.get("after", "0")
        try:
            after_id = max(0, int(after))
        except ValueError:
            after_id = 0
        with notification_lock:
            items = [
                {
                    key: value for key, value in item.items()
                    if not key.startswith("_")
                }
                for item in host_notifications
                if item["id"] > after_id
            ]
        return jsonify({"notifications": items})

    @app.delete("/api/interactive/host-notifications")
    def clear_host_notifications():
        with notification_lock:
            cleared = len(host_notifications)
            host_notifications.clear()
        return jsonify({"cleared": cleared})

    @app.post("/api/interactive/games")
    def create_game():
        data = payload()
        session = game_service().create_game(
            data.get("scenario_id", "stormbound_inn"),
            game_id=data.get("game_id"),
            seed=int(data.get("seed", 0)),
            player_agent_id=str(data.get("player_agent_id") or "") or None,
        )
        if session.state.player_agent_id:
            player_token = str(session.issued_player_token or "")
            return jsonify({
                "mode": "player",
                "player_token": player_token,
                "player": session.player_state(player_token),
            }), 201
        return jsonify({
            "mode": "director",
            "state": session.observer_state(),
            "cards": session.card_suggestions(),
            "empty_event": session.empty_event_option(),
            "intel": session.intel_suggestions(),
            "planner": session.planner.__class__.__name__,
        }), 201

    @app.get("/api/interactive/games/<game_id>/player")
    def get_player_game(game_id: str):
        session = game_service().get(game_id)
        return jsonify({
            "player": session.player_state(request.headers.get("X-Player-Token", "")),
        })

    @app.get("/api/interactive/games/<game_id>")
    def get_game(game_id: str):
        session = game_service().get(game_id)
        return jsonify({
            "state": session.public_state(),
            "cards": session.card_suggestions()
            if not session.state.active_event_card
            and session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
            else [],
            "empty_event": session.empty_event_option()
            if not session.state.active_event_card
            and session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
            else None,
            "intel": session.intel_suggestions()
            if session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
            else [],
        })

    @app.get("/api/interactive/games/<game_id>/observer")
    def get_observer_game(game_id: str):
        """Live-map view with trackable actions but without private case truth."""

        session = game_service().get(game_id)
        return jsonify({
            "state": session.observer_state(),
        })

    @app.get("/api/interactive/games/<game_id>/director")
    def get_director_game(game_id: str):
        """Local host-only view containing the seeded truth and private case files."""

        session = game_service().get(game_id)
        return jsonify({
            "state": session.director_state(),
            "cards": session.card_suggestions()
            if not session.state.active_event_card
            and session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
            else [],
            "empty_event": session.empty_event_option()
            if not session.state.active_event_card
            and session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
            else None,
            "intel": session.intel_suggestions()
            if session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
            else [],
        })

    @app.post("/api/interactive/games/<game_id>/notices")
    def post_notice(game_id: str):
        data = payload()
        notice = game_service().get(game_id).post_notice(
            str(data.get("content", "")),
            display_author=str(data.get("display_author", "临时掌柜")),
        )
        return jsonify({"notice": notice.to_dict()}), 201

    @app.post("/api/interactive/games/<game_id>/planner")
    def switch_planner(game_id: str):
        data = payload()
        session = game_service().get(game_id)
        provider = str(data.get("provider", "heuristic"))
        model = str(data.get("model", ""))
        planner = build_planner(
            int(session.state.flags.get("seed", 0)), provider, model
        )
        return jsonify(session.set_planner(planner))

    @app.post("/api/interactive/games/<game_id>/player/notices")
    def post_player_notice(game_id: str):
        data = payload()
        session = game_service().get(game_id)
        token = request.headers.get("X-Player-Token", "")
        notice = session.post_player_notice(token, str(data.get("content", "")))
        return jsonify({
            "notice": notice.to_dict(),
            "player": session.player_state(token),
        }), 201

    @app.post("/api/interactive/games/<game_id>/event-card")
    def select_event_card(game_id: str):
        data = payload()
        events = game_service().get(game_id).select_event_card(str(data.get("card_id", "")))
        return jsonify({
            "events": [event.to_dict() for event in events if event.public],
            "state": game_service().get(game_id).public_state(),
        })

    @app.post("/api/interactive/games/<game_id>/public-intel")
    def publish_public_intel(game_id: str):
        data = payload()
        intel, event = game_service().get(game_id).publish_public_intel(
            str(data.get("intel_id", ""))
        )
        return jsonify({
            "intel": intel,
            "event": event.to_dict(),
            "state": game_service().get(game_id).public_state(),
        }), 201

    @app.post("/api/interactive/games/<game_id>/rounds/advance")
    def advance_round(game_id: str):
        session = game_service().get(game_id)
        with task_lock:
            if game_id in active_game_tasks:
                raise ValueError("A round is already being resolved for this game")
            task_id = f"round-task-{uuid.uuid4().hex[:12]}"
            tasks[task_id] = {
                "task_id": task_id,
                "game_id": game_id,
                "status": "queued",
                "message": "等待角色开始思考",
                "progress": {
                    "stage": "queued",
                    "completed": 0,
                    "total": sum(1 for agent in session.state.agents.values() if agent.can_act),
                    "agents": {},
                },
                "result": None,
                "error": None,
            }
            active_game_tasks[game_id] = task_id

        def run_round_task():
            with task_lock:
                tasks[task_id]["status"] = "running"
                tasks[task_id]["message"] = "角色正在同时形成行动意图"

            def report_progress(update: dict[str, Any]):
                with task_lock:
                    progress = tasks[task_id]["progress"]
                    progress["stage"] = update.get("stage", "intent")
                    progress["completed"] = int(update.get("completed", 0))
                    progress["total"] = int(update.get("total", progress.get("total", 0)))
                    progress["agents"][str(update.get("agent_id", ""))] = {
                        "display_name": update.get("display_name", update.get("agent_id", "")),
                        "status": update.get("status", "completed"),
                        "source": update.get("source", "unknown"),
                    }
                    stage_name = "终局投票" if progress["stage"] == "vote" else "角色决策"
                    action_step = update.get("action_step")
                    if action_step and progress["stage"] != "vote":
                        stage_name += f"（行动 {action_step}/{session.state.actions_per_round}）"
                    tasks[task_id]["message"] = (
                        f"{stage_name}：{progress['completed']}/{progress['total']} 已完成"
                    )
            try:
                result = session.advance_round(progress_callback=report_progress)
                response_data = {
                    "round_number": result.round_number,
                    "events": [event.to_dict() for event in result.events if event.public],
                    "rejected_intents": result.rejected_intents,
                    "state": session.public_state(),
                    "cards": session.card_suggestions()
                    if session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
                    else [],
                    "empty_event": session.empty_event_option()
                    if session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
                    else None,
                    "intel": session.intel_suggestions()
                    if session.state.phase in {GamePhase.INTERVENTION, GamePhase.ROUND_COMPLETE}
                    else [],
                }
                with task_lock:
                    tasks[task_id]["status"] = "succeeded"
                    tasks[task_id]["message"] = "本轮推演完成"
                    tasks[task_id]["result"] = response_data
            except Exception as error:
                record_host_notification(
                    error,
                    source="background_round",
                    game_id=game_id,
                    provider=str(getattr(session.planner, "provider_name", "")),
                )
                with task_lock:
                    tasks[task_id]["status"] = "failed"
                    tasks[task_id]["message"] = "本轮推演失败"
                    tasks[task_id]["error"] = str(error)
            finally:
                with task_lock:
                    active_game_tasks.pop(game_id, None)

        executor.submit(run_round_task)
        return jsonify({
            "task_id": task_id,
            "status": "queued",
            "state": session.public_state(),
        }), 202

    @app.post("/api/interactive/games/<game_id>/player/actions")
    def player_action(game_id: str):
        session = game_service().get(game_id)
        token = request.headers.get("X-Player-Token", "")
        action_data = payload()
        # Validate synchronously so a malformed choice is returned immediately
        # instead of consuming a long-running LLM task slot.
        session.build_player_intent(token, action_data)
        is_free_action = str(action_data.get("action_type", "")) in {"move", "talk"}
        is_conversation = str(action_data.get("action_type", "")) == "talk"
        total = (1 if is_conversation else 0) if is_free_action else sum(
            1 for agent_id, agent in session.state.agents.items()
            if agent.can_act and agent_id != session.state.player_agent_id
        )

        def resolve_player_action(report_progress):
            result = session.advance_player_action(
                token,
                action_data,
                progress_callback=report_progress,
            )
            return {
                "round_number": result.round_number,
                "action_step": result.action_step,
                "player": session.player_state(token),
            }

        return queue_game_operation(
            game_id,
            initial_message=(
                "对方正在斟酌如何回应你"
                if is_conversation
                else "正在处理你的自由探索"
                if is_free_action
                else "其他角色正在根据你的选择形成行动"
            ),
            total=total,
            operation=resolve_player_action,
        )

    @app.post("/api/interactive/games/<game_id>/player/end-round")
    def player_end_round(game_id: str):
        session = game_service().get(game_id)
        token = request.headers.get("X-Player-Token", "")
        session.verify_player_token(token)
        remaining = max(1, session.state.actions_per_round - session.state.action_step)
        ai_count = sum(
            1 for agent_id, agent in session.state.agents.items()
            if agent.can_act and agent_id != session.state.player_agent_id
        )

        def resolve_end_round(report_progress):
            result = session.end_player_round(token, progress_callback=report_progress)
            return {
                "round_number": result.round_number,
                "action_step": result.action_step,
                "player": session.player_state(token),
            }

        return queue_game_operation(
            game_id,
            initial_message="正在收束本轮，其余角色将完成尚未使用的主要行动",
            total=remaining * ai_count,
            operation=resolve_end_round,
        )

    @app.post("/api/interactive/games/<game_id>/player/auto-host")
    def player_auto_host(game_id: str):
        session = game_service().get(game_id)
        token = request.headers.get("X-Player-Token", "")
        with task_lock:
            if game_id in active_game_tasks:
                raise ValueError("当前仍有行动正在结算")
        selection = session.auto_host_next_round(token)
        return jsonify({
            **selection,
            "player": session.player_state(token),
        })

    @app.post("/api/interactive/games/<game_id>/player/host-choice")
    def player_host_choice(game_id: str):
        session = game_service().get(game_id)
        token = request.headers.get("X-Player-Token", "")
        data = payload()
        with task_lock:
            if game_id in active_game_tasks:
                raise ValueError("当前仍有行动正在结算")
        selection = session.choose_player_host_event(
            token,
            str(data.get("card_id", "")),
            intel_id=str(data.get("intel_id") or "") or None,
        )
        return jsonify({
            **selection,
            "player": session.player_state(token),
        })

    @app.post("/api/interactive/games/<game_id>/player/open-voting")
    def open_player_voting(game_id: str):
        session = game_service().get(game_id)
        token = request.headers.get("X-Player-Token", "")
        session.open_final_vote(token)
        return jsonify({"player": session.player_state(token)})

    @app.post("/api/interactive/games/<game_id>/player/vote")
    def player_vote(game_id: str):
        session = game_service().get(game_id)
        token = request.headers.get("X-Player-Token", "")
        session.verify_player_token(token)
        data = payload()
        suspect_id = str(data.get("suspect_id", ""))
        reason = str(data.get("reason", ""))
        answers = data.get("answers", [])
        if not isinstance(answers, list):
            raise ValueError("终局答卷格式无效")
        if session.state.phase != GamePhase.VOTING:
            raise ValueError("当前还没有进入终局投票")
        total = sum(
            1 for agent in session.state.agents.values()
            if agent.agent_id != session.state.player_agent_id
        )

        def resolve_player_vote(report_progress):
            session.submit_player_vote(
                token, suspect_id, reason, answers=answers
            )
            return {"player": session.player_state(token)}

        return queue_game_operation(
            game_id,
            initial_message="其他角色正在依据各自记忆独立投票",
            total=total,
            operation=resolve_player_vote,
        )

    @app.get("/api/interactive/tasks/<task_id>")
    def get_round_task(task_id: str):
        with task_lock:
            task = tasks.get(task_id)
            if task is None:
                raise KeyError(f"Unknown round task: {task_id}")
            return jsonify(dict(task))

    @app.get("/api/interactive/games/<game_id>/recap")
    def get_recap(game_id: str):
        session = game_service().get(game_id)
        return jsonify({
            "recap": session.build_recap(),
            "story_outline": session.build_story_outline(),
        })

    @app.get("/api/interactive/games/<game_id>/timeline")
    def get_action_timeline(game_id: str):
        session = game_service().get(game_id)
        return jsonify({"timeline": session.build_action_timeline()})

    @app.get("/api/interactive/games/<game_id>/timeline.txt")
    def download_action_timeline(game_id: str):
        session = game_service().get(game_id)
        return Response(
            session.action_timeline_text(),
            mimetype="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{game_id}-action-timeline.txt"'
                ),
            },
        )

    @app.errorhandler(KeyError)
    def handle_key_error(error: KeyError):
        record_host_notification(error, source=f"http:{request.path}")
        return jsonify({"error": str(error)}), 404

    @app.errorhandler(ValueError)
    def handle_value_error(error: ValueError):
        record_host_notification(error, source=f"http:{request.path}")
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        if isinstance(error, HTTPException):
            return error
        record_host_notification(error, source=f"http:{request.path}")
        return jsonify({"error": "服务器内部异常；详细信息已发送到主持台"}), 500

    @app.after_request
    def prevent_prototype_asset_cache(response):
        if request.path.startswith("/interactive") or request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    try:
        port = int(os.environ.get("GA_INTERACTIVE_PORT", "5001"))
    except ValueError:
        port = 5001
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
