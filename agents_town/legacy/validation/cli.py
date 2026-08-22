"""Validation and local bootstrap commands for the legacy simulation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from agents_town.common import (
    find_secret_fields,
    load_local_config,
    redact_text,
    resolve_credentials,
)
from agents_town.common.paths import RuntimePaths, discover_runtime_paths
from agents_town.legacy.launcher.commands import scoped_subprocess_environment


TEXT_MODEL = "qwen2.5:7b-instruct"
EMBEDDING_MODEL = "embeddinggemma"
TEMPLATE_NAMES = ("如鸢密探", "如鸢密探·袁基")


def _paths() -> RuntimePaths:
    return discover_runtime_paths()


def _ollama_json(path: str, timeout: float = 3.0) -> dict[str, Any]:
    with urlopen(f"http://127.0.0.1:11434{path}", timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    return value if isinstance(value, dict) else {}


def preflight() -> tuple[bool, dict[str, Any]]:
    runtime = _paths()
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    record(
        "python",
        (3, 10) <= sys.version_info[:2] <= (3, 11),
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
    modules = {
        "flask": "flask",
        "Pillow": "PIL",
        "PySide6": "PySide6",
        "llama-index": "llama_index",
        "llama-index-embeddings-ollama": "llama_index.embeddings.ollama",
    }
    for label, module in modules.items():
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ModuleNotFoundError):
            available = False
        record(label, available, module)

    legacy = runtime.legacy_resources
    record("maze", (legacy / "frontend/static/assets/village/maze.json").is_file(), "maze.json")
    templates = legacy / "character_templates/agents"
    for name in TEMPLATE_NAMES:
        template = templates / name
        record(
            f"template:{name}",
            all((template / filename).is_file() for filename in ("agent.json", "portrait.png", "texture.png")),
            os.fspath(template),
        )

    config = load_local_config(runtime)
    record("local-config", bool(config.get("agent_base")), "agent_base")
    try:
        version = _ollama_json("/api/version").get("version", "unknown")
        record("ollama-service", True, str(version))
        tags = _ollama_json("/api/tags").get("models", [])
        names = {
            str(item.get("name") or item.get("model"))
            for item in tags
            if isinstance(item, dict)
        }
        record("ollama-text-model", TEXT_MODEL in names, TEXT_MODEL)
        record(
            "ollama-embedding-model",
            EMBEDDING_MODEL in names or f"{EMBEDDING_MODEL}:latest" in names,
            EMBEDDING_MODEL,
        )
    except Exception as error:
        record("ollama-service", False, redact_text(error)[:240])

    return all(item["ok"] for item in checks), {"checks": checks}


def bootstrap() -> dict[str, Any]:
    runtime = _paths()
    created: list[str] = []
    preserved: list[str] = []
    templates = runtime.legacy_resources / "character_templates/agents"
    target_root = runtime.legacy_resources / "frontend/static/assets/village/agents"
    target_root.mkdir(parents=True, exist_ok=True)
    for name in TEMPLATE_NAMES:
        source = templates / name
        target = target_root / name
        if target.exists():
            preserved.append(os.fspath(target))
            continue
        shutil.copytree(source, target)
        created.append(os.fspath(target))

    config_target = runtime.project_root / "data/config.json"
    config_source = runtime.legacy_resources / "config.example.json"
    if config_target.exists():
        preserved.append(os.fspath(config_target))
    else:
        config_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config_source, config_target)
        created.append(os.fspath(config_target))

    selected = runtime.legacy_results / "selected_personas.json"
    if selected.exists():
        preserved.append(os.fspath(selected))
    else:
        selected.parent.mkdir(parents=True, exist_ok=True)
        selected.write_text(
            json.dumps(list(TEMPLATE_NAMES), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        created.append(os.fspath(selected))
    return {"created": created, "preserved": preserved}


def secrets_scan(root: Path | None = None) -> dict[str, Any]:
    runtime = _paths()
    scan_roots = [root] if root is not None else [
        runtime.legacy_results / "checkpoints",
        runtime.results_root / "checkpoints",
    ]
    unique_roots: list[Path] = []
    for candidate in scan_roots:
        resolved = candidate.resolve()
        if resolved not in unique_roots:
            unique_roots.append(resolved)
    affected: list[dict[str, Any]] = []
    invalid: list[str] = []
    for scan_root in unique_roots:
        if scan_root.is_dir():
            for path in sorted(scan_root.rglob("*.json")):
                if path.name == "conversation.json":
                    continue
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    invalid.append(os.fspath(path))
                    continue
                fields = find_secret_fields(value)
                if fields:
                    affected.append({"file": os.fspath(path), "fields": fields})
    return {
        "roots": [os.fspath(item) for item in unique_roots],
        "affected_files": affected,
        "affected_count": len(affected),
        "invalid_json": invalid,
    }


def _run(command: list[str], env: dict[str, str], timeout: int = 900) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        result = subprocess.run(
            command,
            cwd=os.fspath(_paths().project_root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "exit_code": result.returncode,
            "ok": result.returncode == 0,
            "stderr": redact_text(result.stderr)[-2000:],
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "exit_code": None,
            "ok": False,
            "stderr": f"Timed out after {timeout} seconds",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }


def _checkpoint_continuity(checkpoints: Path) -> dict[str, Any]:
    files = sorted(checkpoints.glob("simulate-*.json")) if checkpoints.is_dir() else []
    states: list[dict[str, Any]] = []
    for path in files:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            states.append(value)
    steps = [state.get("step") for state in states]
    times = [state.get("time") for state in states]
    try:
        parsed_times = [datetime.strptime(value, "%Y%m%d-%H:%M") for value in times]
        expected_minutes = [int(state.get("stride")) for state in states[:-1]]
        time_continuity = len(parsed_times) >= 2 and all(
            int((right - left).total_seconds() // 60) == stride
            for left, right, stride in zip(
                parsed_times, parsed_times[1:], expected_minutes
            )
        )
    except (TypeError, ValueError):
        time_continuity = False
    agents_preserved = bool(states) and all(
        isinstance(state.get("agents"), dict) and state["agents"]
        for state in states
    )
    memory_preserved = agents_preserved and all(
        isinstance(agent.get("associate", {}).get("memory"), dict)
        for state in states
        for agent in state["agents"].values()
        if isinstance(agent, dict)
    )
    memory_continuity = memory_preserved
    for previous, current in zip(states, states[1:]):
        previous_agents = previous.get("agents", {})
        current_agents = current.get("agents", {})
        for agent_name, previous_agent in previous_agents.items():
            current_agent = current_agents.get(agent_name, {})
            previous_memory = previous_agent.get("associate", {}).get("memory", {})
            current_memory = current_agent.get("associate", {}).get("memory", {})
            for memory_type, previous_ids in previous_memory.items():
                current_ids = current_memory.get(memory_type, [])
                if not set(map(str, previous_ids)).issubset(set(map(str, current_ids))):
                    memory_continuity = False
    conversation_path = checkpoints / "conversation.json"
    try:
        conversations = json.loads(conversation_path.read_text(encoding="utf-8"))
        conversation_ok = isinstance(conversations, dict)
    except (OSError, ValueError):
        conversation_ok = False
    return {
        "steps": steps,
        "times": times,
        "step_continuity": len(steps) >= 2
        and all(isinstance(step, int) for step in steps)
        and all(right == left + 1 for left, right in zip(steps, steps[1:])),
        "time_continuity": time_continuity,
        "agents_preserved": agents_preserved,
        "memory_preserved": memory_preserved,
        "memory_continuity": memory_continuity,
        "conversation_log": conversation_ok,
    }


def _validate_replay_routes(results_root: Path, name: str) -> dict[str, Any]:
    previous = os.environ.get("GA_RESULTS_DIR")
    os.environ["GA_RESULTS_DIR"] = os.fspath(results_root)
    try:
        from agents_town.legacy.replay.app import app

        app.config.update(TESTING=True)
        with app.test_client() as client:
            page = client.get("/", query_string={"name": name})
            static_asset = client.get("/static/css/style.css")
        return {
            "page_status": page.status_code,
            "static_status": static_asset.status_code,
            "ok": page.status_code == 200 and static_asset.status_code == 200,
        }
    except Exception as error:
        return {"page_status": None, "static_status": None, "ok": False, "error": redact_text(error)[:500]}
    finally:
        if previous is None:
            os.environ.pop("GA_RESULTS_DIR", None)
        else:
            os.environ["GA_RESULTS_DIR"] = previous


def smoke(name: str) -> tuple[bool, dict[str, Any]]:
    runtime = _paths()
    safe_name = "".join(char for char in name if char.isalnum() or char in "-_")
    if not safe_name:
        raise ValueError("Validation name must contain letters, numbers, '-' or '_'.")
    run_dir = runtime.legacy_results / "validation" / safe_name
    runtime_root = run_dir / "runtime-root"
    selected = runtime_root / "legacy/selected_personas.json"
    selected.parent.mkdir(parents=True, exist_ok=True)
    if not selected.exists():
        selected.write_text(
            json.dumps(list(TEMPLATE_NAMES), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    base_env = dict(os.environ)
    base_env["GA_RESULTS_DIR"] = os.fspath(runtime_root)
    base_env["PYTHONIOENCODING"] = "utf-8"
    config = load_local_config(runtime)
    commands = [
        (
            [sys.executable, "-m", "agents_town", "start", "--name", safe_name, "--step", "1", "--stride", "10"],
            scoped_subprocess_environment("start", base_env=base_env, config=config),
        ),
        (
            [sys.executable, "-m", "agents_town", "start", "--name", safe_name, "--step", "1", "--stride", "10", "--resume"],
            scoped_subprocess_environment("start", base_env=base_env, config=config),
        ),
        (
            [sys.executable, "-m", "agents_town.legacy.replay.report", "--name", safe_name],
            scoped_subprocess_environment("compress", base_env=base_env, config=config),
        ),
    ]
    stages: list[dict[str, Any]] = []
    for command, stage_env in commands:
        stage = _run(command, stage_env)
        stages.append(stage)
        if not stage["ok"]:
            break

    checkpoints = runtime_root / "legacy/checkpoints" / safe_name
    scan = secrets_scan(checkpoints)
    continuity = _checkpoint_continuity(checkpoints)
    compressed = runtime_root / "legacy/compressed" / safe_name
    replay = _validate_replay_routes(runtime_root, safe_name)
    credential_status = {
        "liblib": all(resolve_credentials("liblibai", config=config).values()),
        "suno": bool(resolve_credentials("suno", config=config).get("api_key")),
        "gemini": bool(resolve_credentials("gemini", config=config).get("api_key")),
    }
    media = {
        service: (
            "NOT_RUN_CREDENTIALS_PRESENT"
            if available
            else "SKIPPED_NO_CREDENTIALS"
        )
        for service, available in credential_status.items()
    }
    artifacts = {
        "checkpoint_count": len(list(checkpoints.glob("simulate-*.json"))) if checkpoints.is_dir() else 0,
        "simulation_markdown": (compressed / "simulation.md").is_file(),
        "movement_json": (compressed / "movement.json").is_file(),
        "secret_fields": scan["affected_count"],
        "continuity": continuity,
        "replay": replay,
    }
    ok = (
        len(stages) == len(commands)
        and all(stage["ok"] for stage in stages)
        and artifacts["checkpoint_count"] >= 2
        and artifacts["simulation_markdown"]
        and artifacts["movement_json"]
        and artifacts["secret_fields"] == 0
        and all(
            continuity[key]
            for key in (
                "step_continuity",
                "time_continuity",
                "agents_preserved",
                "memory_preserved",
                "memory_continuity",
                "conversation_log",
            )
        )
        and replay["ok"]
    )
    report = {
        "run_id": safe_name,
        "ok": ok,
        "stages": stages,
        "artifacts": artifacts,
        "media": media,
        "note": "No external media service was called by smoke validation.",
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "validation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "validation-report.md").write_text(
        "# Legacy validation report\n\n"
        f"- Run: `{safe_name}`\n"
        f"- Result: `{'PASS' if ok else 'FAIL'}`\n"
        f"- Checkpoints: `{artifacts['checkpoint_count']}`\n"
        f"- Secret-bearing checkpoints: `{artifacts['secret_fields']}`\n"
        f"- Continuity: `{'PASS' if all(value for key, value in continuity.items() if key not in {'steps', 'times'}) else 'FAIL'}`\n"
        f"- Replay routes: `{'PASS' if replay['ok'] else 'FAIL'}`\n",
        encoding="utf-8",
    )
    return ok, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="Run read-only environment checks")
    subparsers.add_parser("bootstrap", help="Create missing local config and template agents")
    scan_parser = subparsers.add_parser("secrets-scan", help="Scan checkpoints without changing them")
    scan_parser.add_argument("--root", type=Path)
    smoke_parser = subparsers.add_parser("smoke", help="Run isolated simulate/resume/report checks")
    smoke_parser.add_argument("--name", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preflight":
        ok, report = preflight()
    elif args.command == "bootstrap":
        report = bootstrap()
        ok = True
    elif args.command == "secrets-scan":
        report = secrets_scan(args.root)
        ok = True
    else:
        ok, report = smoke(args.name)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 2


__all__ = [
    "bootstrap",
    "build_parser",
    "main",
    "preflight",
    "secrets_scan",
    "smoke",
]
