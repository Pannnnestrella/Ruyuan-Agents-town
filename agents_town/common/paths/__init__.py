"""Runtime path discovery for source and frozen distributions."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved source, packaged-resource, and writable result locations."""

    project_root: Path
    resource_root: Path
    results_root: Path

    @property
    def common_resources(self) -> Path:
        return self.resource_root / "agents_town" / "common" / "resources"

    @property
    def interactive_resources(self) -> Path:
        return self.resource_root / "agents_town" / "interactive" / "resources"

    @property
    def legacy_resources(self) -> Path:
        return self.resource_root / "agents_town" / "legacy" / "resources"

    @property
    def interactive_results(self) -> Path:
        return self.results_root / "interactive"

    @property
    def legacy_results(self) -> Path:
        return self.results_root / "legacy"


def _base_dir(anchor: str | Path | None = None) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    if anchor is not None:
        path = Path(anchor).resolve()
        return path if path.is_dir() else path.parent
    return Path(__file__).resolve().parents[3]


def _resource_candidates(base: Path) -> list[Path]:
    candidates = [
        base,
        base / "_internal",
        base / "AI-Town" / "_internal",
        base / "AI-Town",
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.insert(0, Path(meipass).resolve())
    return candidates


def discover_runtime_paths(anchor: str | Path | None = None) -> RuntimePaths:
    """Discover paths without importing either application package.

    New distributions are detected by their ``agents_town`` package.  The
    legacy ``frontend``/``data`` layout remains a read-only fallback during the
    compatibility period.
    """

    base = _base_dir(anchor)
    resource_root = base
    for candidate in _resource_candidates(base):
        if (candidate / "agents_town").is_dir():
            resource_root = candidate
            break
        if (candidate / "frontend" / "static").is_dir() and (candidate / "data").is_dir():
            resource_root = candidate
            break

    project_root = Path(__file__).resolve().parents[3]
    configured_results = os.environ.get("GA_RESULTS_DIR", "").strip()
    results_root = (
        Path(configured_results).expanduser().resolve()
        if configured_results
        else base / "results"
    )
    return RuntimePaths(project_root, resource_root, results_root)
