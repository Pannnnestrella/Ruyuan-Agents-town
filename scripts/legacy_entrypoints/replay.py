"""Archived wrapper for the legacy replay server."""

from _bootstrap import run_module


def main() -> None:
    run_module("agents_town.legacy.replay.app")


__all__ = ["main"]


if __name__ == "__main__":
    main()
