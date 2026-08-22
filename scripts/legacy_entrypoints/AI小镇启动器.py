"""Archived wrapper for the legacy desktop launcher."""

from _bootstrap import PROJECT_ROOT
from agents_town.legacy.launcher.app import main

__all__ = ["PROJECT_ROOT", "main"]


if __name__ == "__main__":
    main()
