"""Run the interactive web application without re-executing its app module."""

from __future__ import annotations

import os

from .app import app


def main() -> None:
    try:
        port = int(os.environ.get("GA_INTERACTIVE_PORT", "5001"))
    except ValueError:
        port = 5001
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


__all__ = ["main"]


if __name__ == "__main__":
    main()
