from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolResult:
    ok: bool
    message: str
    data: dict = field(default_factory=dict)
