"""Friendly project entry point; starts Stormbound Inn by default."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from agents_town.cli import main as agents_main


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    agents_main(arguments or ["interactive"])


__all__ = ["main"]


if __name__ == "__main__":
    main()
