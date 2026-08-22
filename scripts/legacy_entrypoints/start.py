"""Archived wrapper for the legacy open-world simulation."""

from _bootstrap import run_module


def main() -> None:
    run_module("agents_town.legacy.simulation.runner")


__all__ = ["main"]


if __name__ == "__main__":
    main()
