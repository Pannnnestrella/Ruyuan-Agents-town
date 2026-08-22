"""Archived wrapper for legacy replay report generation."""

from _bootstrap import PROJECT_ROOT
from agents_town.legacy.replay.report import main

__all__ = ["PROJECT_ROOT", "main"]


if __name__ == "__main__":
    main()
