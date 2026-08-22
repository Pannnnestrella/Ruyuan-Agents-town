"""Archived wrapper for the legacy Suno integration."""

from _bootstrap import run_module


def main() -> None:
    run_module("agents_town.legacy.integrations.suno")


__all__ = ["main"]


if __name__ == "__main__":
    main()
