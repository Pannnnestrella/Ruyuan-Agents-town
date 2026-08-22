"""Make canonical package modules available to archived standalone wrappers."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_module(module: str) -> None:
    runpy.run_module(module, run_name="__main__")


__all__ = ["PROJECT_ROOT", "run_module"]
