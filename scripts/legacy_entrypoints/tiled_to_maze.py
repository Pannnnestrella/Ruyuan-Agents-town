"""Archived wrapper for the legacy Tiled conversion utility."""

from _bootstrap import run_module


def main() -> None:
    run_module("agents_town.legacy.tools.tiled_to_maze")


__all__ = ["main"]


if __name__ == "__main__":
    main()
