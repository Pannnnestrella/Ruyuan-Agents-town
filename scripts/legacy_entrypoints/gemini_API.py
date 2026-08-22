"""Archived wrapper for the legacy Gemini integration."""

from _bootstrap import run_module


def main() -> None:
    run_module("agents_town.legacy.integrations.gemini")


__all__ = ["main"]


if __name__ == "__main__":
    main()
