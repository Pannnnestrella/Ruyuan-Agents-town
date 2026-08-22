"""Resolve legacy launcher subprocesses for source and frozen runtimes."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from agents_town.common import (
    load_local_config,
    resolve_credentials,
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    module: str
    frozen_executable: str


COMMAND_SPECS: dict[str, CommandSpec] = {
    "start": CommandSpec(
        "agents_town.legacy.simulation.runner",
        "start.exe",
    ),
    "compress": CommandSpec(
        "agents_town.legacy.replay.report",
        "compress.exe",
    ),
    "replay": CommandSpec(
        "agents_town.legacy.replay.app",
        "replay.exe",
    ),
    "liblib": CommandSpec(
        "agents_town.legacy.integrations.liblib_starflow",
        "liblib_starflow_txt2img_api.exe",
    ),
    "suno": CommandSpec(
        "agents_town.legacy.integrations.suno",
        "suno-api.exe",
    ),
    "gemini": CommandSpec(
        "agents_town.legacy.integrations.gemini",
        "gemini_API.exe",
    ),
}

SECRET_ENV_NAMES = {
    "OPENAI_API_KEY",
    "ZHIPUAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API",
    "QIANFAN_AK",
    "QIANFAN_SK",
    "SPARK_APPID",
    "SPARK_API_KEY",
    "SPARK_API_SECRET",
    "LIBLIBAI_ACCESS_KEY",
    "LIBLIBAI_SECRET_KEY",
    "SUNO_API_KEY",
}


def _spec(command_name: str) -> CommandSpec:
    try:
        return COMMAND_SPECS[command_name]
    except KeyError as exc:
        supported = ", ".join(sorted(COMMAND_SPECS))
        raise ValueError(
            f"Unknown launcher command {command_name!r}; expected one of: {supported}"
        ) from exc


def frozen_executable_candidates(
    command_name: str,
    executable_dir: str | os.PathLike[str],
) -> tuple[Path, ...]:
    """Return supported one-folder and collected-distribution layouts."""

    spec = _spec(command_name)
    base_dir = Path(executable_dir).resolve()
    stem = Path(spec.frozen_executable).stem
    return (
        base_dir / spec.frozen_executable,
        base_dir.parent / stem / spec.frozen_executable,
    )


def resolve_command(
    command_name: str,
    arguments: Iterable[str] = (),
    *,
    frozen: bool | None = None,
    python_executable: str | os.PathLike[str] | None = None,
    executable_dir: str | os.PathLike[str] | None = None,
    project_root: str | os.PathLike[str] | None = None,
) -> tuple[list[str], str]:
    """Build a module command in source mode or locate its frozen executable."""

    spec = _spec(command_name)
    arguments = [str(argument) for argument in arguments]
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen

    if not is_frozen:
        python = os.fspath(python_executable or sys.executable)
        working_dir = os.fspath(Path(project_root or Path.cwd()).resolve())
        return [python, "-u", "-m", spec.module, *arguments], working_dir

    base_dir = Path(executable_dir or Path(sys.executable).resolve().parent)
    for candidate in frozen_executable_candidates(command_name, base_dir):
        if candidate.is_file():
            return [os.fspath(candidate), *arguments], os.fspath(candidate.parent)

    candidates = ", ".join(
        os.fspath(path) for path in frozen_executable_candidates(command_name, base_dir)
    )
    raise FileNotFoundError(
        f"Frozen executable for {command_name!r} was not found; checked: {candidates}"
    )


def command_name_for_argv(argv: Iterable[str]) -> str | None:
    """Identify a canonical launcher command without inspecting root wrappers."""

    values = [os.fspath(value) for value in argv]
    if "-m" in values:
        index = values.index("-m")
        if index + 1 < len(values):
            module = values[index + 1]
            for name, spec in COMMAND_SPECS.items():
                if module == spec.module:
                    return name
    if values:
        executable = Path(values[0]).name.lower()
        for name, spec in COMMAND_SPECS.items():
            if executable == spec.frozen_executable.lower():
                return name
    return None


def _model_providers(config: Mapping[str, Any]) -> set[str]:
    agent_base = config.get("agent_base", {})
    if not isinstance(agent_base, Mapping):
        return set()
    think = agent_base.get("think", {})
    llm = think.get("llm", {}) if isinstance(think, Mapping) else {}
    associate = agent_base.get("associate", {})
    embedding = associate.get("embedding", {}) if isinstance(associate, Mapping) else {}
    providers: set[str] = set()

    if isinstance(llm, Mapping):
        explicit = str(llm.get("provider", "")).strip().lower()
        base_url = str(llm.get("base_url", "")).lower()
        model = str(llm.get("model", "")).lower()
        if explicit:
            providers.add(explicit)
        elif any(value in base_url for value in ("localhost", "127.0.0.1", "ollama")):
            providers.add("ollama")
        elif "bigmodel" in base_url or "glm" in model:
            providers.add("zhipuai")
        elif "google" in base_url or "gemini" in model:
            providers.add("gemini")
        elif "deepseek" in base_url or "deepseek" in model:
            providers.add("deepseek")
        elif "qianfan" in base_url or "ernie" in model:
            providers.add("qianfan")
        elif "spark" in base_url or "spark" in model:
            providers.add("spark")
        else:
            providers.add("openai")

    if isinstance(embedding, Mapping):
        embedding_type = str(embedding.get("type", "")).strip().lower()
        if embedding_type:
            providers.add(embedding_type)
    return providers


def _credential_environment(
    provider: str,
    *,
    environment: Mapping[str, str],
    config: Mapping[str, Any],
) -> dict[str, str]:
    name = provider.strip().lower()
    if name in {"ollama", "local", "hugging_face"}:
        return {}
    credentials = resolve_credentials(provider, env=environment, config=config)
    if name in {"zhipu", "zhipuai"}:
        return {"ZHIPUAI_API_KEY": credentials.get("api_key", "")}
    if name in {"gemini", "google"}:
        return {"GEMINI_API_KEY": credentials.get("api_key", "")}
    if name == "deepseek":
        return {"DEEPSEEK_API_KEY": credentials.get("api_key", "")}
    if name == "qianfan":
        return {
            "QIANFAN_AK": credentials.get("access_key", ""),
            "QIANFAN_SK": credentials.get("secret_key", ""),
        }
    if name in {"spark", "sparkai"}:
        return {
            "SPARK_APPID": credentials.get("app_id", ""),
            "SPARK_API_KEY": credentials.get("api_key", ""),
            "SPARK_API_SECRET": credentials.get("secret_key", ""),
        }
    if name == "openai":
        return {"OPENAI_API_KEY": credentials.get("api_key", "")}
    return {}


def scoped_subprocess_environment(
    command_name: str | None,
    *,
    base_env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Build a least-privilege environment for one launcher child process."""

    source_env = os.environ if base_env is None else base_env
    result = {
        str(key): str(value)
        for key, value in source_env.items()
        if str(key) not in SECRET_ENV_NAMES
    }
    local_config = dict(config) if config is not None else load_local_config()
    additions: dict[str, str] = {}
    if command_name == "start":
        for provider in _model_providers(local_config):
            additions.update(
                _credential_environment(
                    provider, environment=source_env, config=local_config
                )
            )
    elif command_name == "liblib":
        values = resolve_credentials("liblibai", env=source_env, config=local_config)
        additions = {
            "LIBLIBAI_ACCESS_KEY": values.get("access_key", ""),
            "LIBLIBAI_SECRET_KEY": values.get("secret_key", ""),
        }
    elif command_name == "suno":
        values = resolve_credentials("suno", env=source_env, config=local_config)
        additions = {"SUNO_API_KEY": values.get("api_key", "")}
    elif command_name == "gemini":
        values = resolve_credentials("gemini", env=source_env, config=local_config)
        additions = {"GEMINI_API_KEY": values.get("api_key", "")}
    result.update({key: value for key, value in additions.items() if value})
    return result


__all__ = [
    "COMMAND_SPECS",
    "CommandSpec",
    "SECRET_ENV_NAMES",
    "command_name_for_argv",
    "frozen_executable_candidates",
    "resolve_command",
    "scoped_subprocess_environment",
]
