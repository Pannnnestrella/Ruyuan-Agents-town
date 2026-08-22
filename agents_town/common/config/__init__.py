"""Safe local configuration loading shared by both applications."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..paths import RuntimePaths, discover_runtime_paths


_SECRET_FIELD_NAMES = {
    "api_key",
    "api_keys",
    "authorization",
    "access_key",
    "secret_key",
    "access_token",
    "refresh_token",
    "bearer",
    "token",
}
_SECRET_QUERY_NAMES = {
    "accesskey",
    "access_key",
    "signature",
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
}


def _is_secret_field(name: object) -> bool:
    normalised = _normalise_name(name)
    if normalised in _SECRET_FIELD_NAMES:
        return True
    return normalised.endswith(
        (
            "_api_key",
            "_api_secret",
            "_access_key",
            "_secret_key",
            "_access_token",
            "_refresh_token",
            "_auth_token",
        )
    )


def _normalise_name(value: object) -> str:
    return str(value).strip().lower().replace("-", "_")


def _legacy_api_keys(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config.get("api_keys", {})
    return value if isinstance(value, Mapping) else {}


def _service_section(config: Mapping[str, Any], service: str) -> Mapping[str, Any]:
    services = config.get("services", {})
    if not isinstance(services, Mapping):
        return {}
    value = services.get(service, {})
    return value if isinstance(value, Mapping) else {}


def _embedding_section(config: Mapping[str, Any]) -> Mapping[str, Any]:
    agent_base = config.get("agent_base", {})
    if not isinstance(agent_base, Mapping):
        return {}
    associate = agent_base.get("associate", {})
    if not isinstance(associate, Mapping):
        return {}
    embedding = associate.get("embedding", {})
    return embedding if isinstance(embedding, Mapping) else {}


def _first_nonempty(*values: object) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def load_local_config(paths: RuntimePaths | None = None) -> dict[str, Any]:
    """Load the ignored local config file, returning an empty mapping safely."""

    runtime = paths or discover_runtime_paths()
    candidates = [
        runtime.resource_root / "agents_town" / "common" / "resources" / "config.json",
        runtime.project_root / "data" / "config.json",
        runtime.resource_root / "data" / "config.json",
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                value = json.loads(candidate.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            continue
    return {}


def service_config(
    service: str,
    *,
    env: dict[str, str] | None = None,
    paths: RuntimePaths | None = None,
) -> dict[str, Any]:
    """Return one service section without logging or exposing credentials."""

    environment = os.environ if env is None else env
    config = load_local_config(paths)
    services = config.get("services", {})
    value = services.get(service, {}) if isinstance(services, dict) else {}
    result = dict(value) if isinstance(value, dict) else {}
    prefix = service.upper().replace("-", "_") + "_"
    for key, raw in environment.items():
        if key.startswith(prefix) and raw:
            result[key[len(prefix):].lower()] = raw
    return result


def resolve_credentials(
    provider: str,
    *,
    env: Mapping[str, str] | None = None,
    paths: RuntimePaths | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Resolve one provider's credentials without borrowing another provider's key.

    Environment variables take precedence.  The ignored local JSON remains a
    read-only compatibility fallback for one release cycle.
    """

    environment = os.environ if env is None else env
    local_config: Mapping[str, Any] = config if config is not None else load_local_config(paths)
    legacy = _legacy_api_keys(local_config)
    name = _normalise_name(provider)

    if name in {"ollama", "local"}:
        return {}
    if name == "liblibai":
        section = _service_section(local_config, "liblibai")
        return {
            "access_key": _first_nonempty(
                environment.get("LIBLIBAI_ACCESS_KEY"), section.get("access_key")
            ),
            "secret_key": _first_nonempty(
                environment.get("LIBLIBAI_SECRET_KEY"), section.get("secret_key")
            ),
        }
    if name == "suno":
        section = _service_section(local_config, "suno")
        return {
            "api_key": _first_nonempty(
                environment.get("SUNO_API_KEY"), section.get("api_key")
            )
        }
    if name in {"gemini", "google"}:
        section = _service_section(local_config, "gemini")
        embedding = _embedding_section(local_config)
        embedding_key = (
            embedding.get("api_key")
            if _normalise_name(embedding.get("type", "")) in {"gemini", "google"}
            else ""
        )
        return {
            "api_key": _first_nonempty(
                environment.get("GEMINI_API_KEY"),
                environment.get("GOOGLE_API_KEY"),
                section.get("api_key"),
                legacy.get("GEMINI_API_KEY"),
                legacy.get("GOOGLE_API_KEY"),
                embedding_key,
            )
        }
    if name == "openai":
        return {
            "api_key": _first_nonempty(
                environment.get("OPENAI_API_KEY"), legacy.get("OPENAI_API_KEY")
            )
        }
    if name in {"zhipuai", "zhipu"}:
        embedding = _embedding_section(local_config)
        embedding_key = (
            embedding.get("api_key")
            if _normalise_name(embedding.get("type", "")) in {"zhipu", "zhipuai"}
            else ""
        )
        return {
            "api_key": _first_nonempty(
                environment.get("ZHIPUAI_API_KEY"),
                legacy.get("ZHIPUAI_API_KEY"),
                embedding_key,
            )
        }
    if name == "deepseek":
        return {
            "api_key": _first_nonempty(
                environment.get("DEEPSEEK_API_KEY"),
                environment.get("DEEPSEEK_API"),
                legacy.get("DEEPSEEK_API_KEY"),
                legacy.get("DEEPSEEK_API"),
            )
        }
    if name == "qianfan":
        return {
            "access_key": _first_nonempty(
                environment.get("QIANFAN_AK"), legacy.get("QIANFAN_AK")
            ),
            "secret_key": _first_nonempty(
                environment.get("QIANFAN_SK"), legacy.get("QIANFAN_SK")
            ),
        }
    if name in {"spark", "sparkai"}:
        return {
            "app_id": _first_nonempty(
                environment.get("SPARK_APPID"), legacy.get("SPARK_APPID")
            ),
            "api_key": _first_nonempty(
                environment.get("SPARK_API_KEY"), legacy.get("SPARK_API_KEY")
            ),
            "secret_key": _first_nonempty(
                environment.get("SPARK_API_SECRET"), legacy.get("SPARK_API_SECRET")
            ),
        }
    raise ValueError(f"Unsupported credential provider: {provider!r}")


def runtime_api_keys(
    *,
    env: Mapping[str, str] | None = None,
    paths: RuntimePaths | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Return the legacy model factory key names as a runtime-only mapping."""

    result: dict[str, str] = {}
    mappings = {
        "openai": {"api_key": "OPENAI_API_KEY"},
        "zhipuai": {"api_key": "ZHIPUAI_API_KEY"},
        "gemini": {"api_key": "GEMINI_API_KEY"},
        "deepseek": {"api_key": "DEEPSEEK_API_KEY"},
        "qianfan": {"access_key": "QIANFAN_AK", "secret_key": "QIANFAN_SK"},
        "spark": {
            "app_id": "SPARK_APPID",
            "api_key": "SPARK_API_KEY",
            "secret_key": "SPARK_API_SECRET",
        },
    }
    for provider, aliases in mappings.items():
        credentials = resolve_credentials(
            provider, env=env, paths=paths, config=config
        )
        for source_name, target_name in aliases.items():
            value = credentials.get(source_name, "")
            if value:
                result[target_name] = value
    return result


def sanitize_for_persistence(value: Any) -> Any:
    """Return a deep JSON-compatible copy with authentication fields removed."""

    if isinstance(value, Mapping):
        return {
            str(key): sanitize_for_persistence(item)
            for key, item in value.items()
            if not _is_secret_field(key)
        }
    if isinstance(value, list):
        return [sanitize_for_persistence(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_persistence(item) for item in value]
    return value


def find_secret_fields(value: Any, path: str = "$") -> list[str]:
    """List secret-shaped JSON field paths without returning their values."""

    matches: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if _is_secret_field(key):
                matches.append(child_path)
            else:
                matches.extend(find_secret_fields(item, child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            matches.extend(find_secret_fields(item, f"{path}[{index}]"))
    return matches


def redact_url(url: str) -> str:
    """Redact authentication query parameters while preserving routing details."""

    try:
        parsed = urlsplit(str(url))
        if not parsed.scheme or not parsed.netloc:
            return redact_text(str(url))
        query = urlencode(
            [
                (key, "[REDACTED]" if _normalise_name(key) in _SECRET_QUERY_NAMES else value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            ]
        )
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))
    except Exception:
        return "[REDACTED_URL]"


def redact_text(text: object, *, secret_values: tuple[str, ...] = ()) -> str:
    """Redact common bearer/query credential shapes and explicitly supplied values."""

    result = str(text)
    result = re.sub(
        r"(?i)(authorization\s*[:=]\s*bearer\s+|bearer\s+)[^\s,;]+",
        r"\1[REDACTED]",
        result,
    )
    result = re.sub(
        r"(?i)(accesskey|signature|api[_-]?key|secret[_-]?key|access[_-]?token)"
        r"(\s*[:=]\s*)([^&\s,}\]]+)",
        r"\1\2[REDACTED]",
        result,
    )
    for secret in secret_values:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def redact_value(value: Any, *, secret_values: tuple[str, ...] = ()) -> Any:
    """Recursively redact authentication fields and secret-shaped strings."""

    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _is_secret_field(key)
                else redact_value(item, secret_values=secret_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, secret_values=secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, secret_values=secret_values) for item in value)
    if isinstance(value, str):
        text = redact_url(value) if "://" in value else value
        return redact_text(text, secret_values=secret_values)
    return value


def validate_service_base_url(url: str, *, allow_loopback_http: bool = False) -> str:
    """Reject credential-bearing plaintext endpoints outside the local machine."""

    value = str(url).strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    if (
        allow_loopback_http
        and parsed.scheme == "http"
        and (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
    ):
        return value
    raise ValueError("Credential-bearing API endpoints must use HTTPS; HTTP is allowed only for loopback services.")


__all__ = [
    "find_secret_fields",
    "load_local_config",
    "redact_text",
    "redact_url",
    "redact_value",
    "resolve_credentials",
    "runtime_api_keys",
    "sanitize_for_persistence",
    "service_config",
    "validate_service_base_url",
]
