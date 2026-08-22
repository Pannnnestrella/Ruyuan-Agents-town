"""Module alias for interactive LLM planning compatibility."""

import sys

from agents_town.interactive.planning import llm_planner as _implementation

sys.modules[__name__] = _implementation
