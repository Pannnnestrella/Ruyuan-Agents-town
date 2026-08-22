"""Archived wrapper for the former root ``__main__.py`` command."""

from _bootstrap import PROJECT_ROOT
from agents_town.cli import main

__all__ = ["PROJECT_ROOT", "main"]


if __name__ == "__main__":
    main()
