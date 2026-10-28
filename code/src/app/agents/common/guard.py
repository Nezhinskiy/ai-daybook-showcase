from __future__ import annotations

from collections.abc import Sequence

from app.agents.capability.resolve import ResolvedPlan
from app.contracts import PlannedToolCall


def capability_guard_rejection(
    actions: Sequence[object],
    planned_tool_calls: Sequence[PlannedToolCall],
    resolved: ResolvedPlan,
    *,
    allow_empty: bool = False,
) -> str | None:
    """Reject any action kind or effect tool outside the scoped capability bundle.

    ``allow_empty=True`` (set by agents whose schema permits zero actions, e.g. the
    analyzer's "already asked, nothing to close yet" run) skips the empty-plan rejection.

    ``actions`` is deliberately ``Sequence[object]`` rather than a protocol that promises
    ``kind``: this is the fail-closed boundary between a model's decision and the effect
    layer, and its job is to *prove* the shape rather than assume it. Declaring the
    attribute in the signature would move the missing-attribute case from a rejection code
    to an ``AttributeError`` at exactly the point where the decision is least trustworthy.
    ``object`` keeps the structural check meaningful while keeping ``Any`` — which switches
    type checking off for whatever flows through it — off the security path.
    """
    if not actions:
        return None if allow_empty else "empty_actions"

    allowed_actions = set(resolved.action_kinds)
    for action in actions:
        kind = getattr(action, "kind", None)
        if not isinstance(kind, str) or kind not in allowed_actions:
            return f"disallowed_action:{kind}"

    allowed_tools = set(resolved.allowed_effect_tools)
    for call in planned_tool_calls:
        if call.tool_name not in allowed_tools:
            return f"disallowed_effect_tool:{call.tool_name}"

    return None
