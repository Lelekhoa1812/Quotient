# Motivation vs Logic
# Motivation: Model turns are data. Tool names are dispatched exactly, not inferred from prose.
# Logic: A turn is either a schema object or a list of tool calls the worker executes.

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class ModelTurn:
    output: dict
    tool_calls: list[ToolCall] = field(default_factory=list)
    trace: str = ""
    cached_tokens: int = 0
