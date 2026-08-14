from __future__ import annotations

from typing import Any

from app.agents.capability.resolve import ResolvedPlan
from app.agents.common.units import UNIVERSAL_ACTION_KINDS
from app.contracts import PlannedToolCall


def capability_guard_rejection(
    actions: list[Any],
    planned_tool_calls: list[PlannedToolCall],
    resolved: ResolvedPlan,
    *,
    allow_empty: bool = False,
) -> str | None:
    """Reject any action kind or effect tool outside the scoped capability bundle.

    ``allow_empty=True`` (set by agents whose schema permits zero actions, e.g. the
    analyzer's "already asked, nothing to close yet" run) skips the empty-plan rejection.
    """
    if not actions:
        return None if allow_empty else "empty_actions"

    allowed_actions = set(resolved.action_kinds) | UNIVERSAL_ACTION_KINDS
    for action in actions:
        kind = getattr(action, "kind", None)
        if not isinstance(kind, str) or kind not in allowed_actions:
            return f"disallowed_action:{kind}"

    allowed_tools = set(resolved.allowed_effect_tools)
    for call in planned_tool_calls:
        if call.tool_name not in allowed_tools:
            return f"disallowed_effect_tool:{call.tool_name}"

    return None
