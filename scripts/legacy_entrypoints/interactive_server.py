"""Archived wrapper for the former root interactive server command."""

from _bootstrap import run_module


def main() -> None:
    run_module("agents_town.interactive.web")


__all__ = ["main"]


if __name__ == "__main__":
    main()
