"""Versioned prompt templates and structured-output contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .context_budget import compress_context, estimate_tokens


ACTION_SCHEMA = {
    "type": "object", "required": ["action_type", "reason", "plan"],
    "properties": {
        "action_type": {"type": "string"}, "target_id": {"type": ["string", "null"]},
        "location_id": {"type": ["string", "null"]}, "object_id": {"type": ["string", "null"]},
        "content": {"type": "string"}, "share_belief_id": {"type": ["string", "null"]},
        "display_object_id": {"type": ["string", "null"]},
        "item_disposition": {"enum": ["none", "show", "refuse", "lie"]},
        "promise": {"type": ["object", "null"]}, "reason": {"type": "string"},
        "plan": {"type": "object"},
    },
}
CONVERSATION_SCHEMA = {
    "type": "object",
    "required": ["content", "share_belief_id", "item_disposition", "display_object_id"],
    "properties": {
        "content": {"type": "string", "maxLength": 180},
        "share_belief_id": {"type": ["string", "null"]},
        "item_disposition": {"enum": ["none", "show", "refuse", "lie"]},
        "display_object_id": {"type": ["string", "null"]},
    },
}
VOTE_SCHEMA = {
    "type": "object",
    "required": ["suspect_id", "reason", "answers", "case_conclusion", "personal_task_answers"],
    "properties": {
        "suspect_id": {"type": "string"}, "reason": {"type": "string", "maxLength": 180},
        "answers": {"type": "array"}, "case_conclusion": {"type": "object"},
        "personal_task_answers": {"type": "array"},
    },
}


@dataclass(frozen=True)
class PromptSpec:
    prompt_id: str
    version: str
    schema_version: str
    template_file: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class PromptDocument:
    text: str
    prompt_id: str
    prompt_version: str
    schema_version: str
    context_hash: str
    compression: dict[str, Any]
    estimated_tokens: int

    def with_retry(self, instruction: str) -> "PromptDocument":
        text = f"{self.text}\n\n{instruction}"
        return replace(self, text=text, estimated_tokens=estimate_tokens(text))

    def __str__(self) -> str:
        return self.text

    def __contains__(self, value: object) -> bool:
        return str(value) in self.text

    def __len__(self) -> int:
        return len(self.text)


PROMPT_SPECS = {
    "agent.intent": PromptSpec("agent.intent", "2.0.0", "action-intent/2", "intent-v2.txt", ACTION_SCHEMA),
    "agent.conversation": PromptSpec("agent.conversation", "2.0.0", "conversation-reply/2", "conversation-v2.txt", CONVERSATION_SCHEMA),
    "agent.final_vote": PromptSpec("agent.final_vote", "2.0.0", "final-vote/2", "final-vote-v2.txt", VOTE_SCHEMA),
}


class PromptCatalog:
    def __init__(self, template_root: str | Path | None = None):
        self.template_root = Path(
            template_root
            or Path(__file__).resolve().parents[1] / "resources" / "prompt_templates"
        )

    def render(
        self, prompt_id: str, context: dict[str, Any], *,
        variables: dict[str, str] | None = None, max_prompt_tokens: int = 30_000,
    ) -> PromptDocument:
        spec = PROMPT_SPECS[prompt_id]
        template = (self.template_root / spec.template_file).read_text(encoding="utf-8")
        variables = dict(variables or {})
        schema_text = json.dumps(spec.schema, ensure_ascii=False, indent=2)
        fixed = template.replace("{{context_json}}", "").replace("{{output_schema}}", schema_text)
        for key, value in variables.items():
            fixed = fixed.replace(f"{{{{{key}}}}}", str(value))
        context_budget = max(256, int(max_prompt_tokens) - estimate_tokens(fixed))
        compacted, compression = compress_context(context, target_tokens=context_budget)
        canonical = json.dumps(context, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        rendered = template.replace(
            "{{context_json}}", json.dumps(compacted, ensure_ascii=False, indent=2),
        ).replace("{{output_schema}}", schema_text)
        for key, value in variables.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        return PromptDocument(
            text=rendered, prompt_id=spec.prompt_id, prompt_version=spec.version,
            schema_version=spec.schema_version,
            context_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            compression=compression, estimated_tokens=estimate_tokens(rendered),
        )
