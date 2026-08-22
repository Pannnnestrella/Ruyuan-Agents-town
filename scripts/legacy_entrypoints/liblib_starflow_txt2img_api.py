"""Archived wrapper for the legacy LibLib integration."""

from _bootstrap import run_module


def main() -> None:
    run_module("agents_town.legacy.integrations.liblib_starflow")


__all__ = ["main"]


if __name__ == "__main__":
    main()
