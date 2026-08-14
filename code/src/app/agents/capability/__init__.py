from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.agents.capability.model import (
    Action,
    Capability,
    EffectTool,
    IntentBundle,
    SkillFragment,
    dedupe_by_identity,
)

if TYPE_CHECKING:
    from app.agents.capability.expand import expand_intent
    from app.agents.capability.plan import CapabilityPlan
    from app.agents.capability.resolve import ResolvedPlan, resolve_plan

__all__ = [
    "Action",
    "Capability",
    "CapabilityPlan",
    "EffectTool",
    "IntentBundle",
    "ResolvedPlan",
    "SkillFragment",
    "dedupe_by_identity",
    "expand_intent",
    "resolve_plan",
]


def __getattr__(name: str) -> Any:
    if name == "CapabilityPlan":
        from app.agents.capability.plan import CapabilityPlan

        return CapabilityPlan
    if name == "expand_intent":
        from app.agents.capability.expand import expand_intent

        return expand_intent
    if name in {"ResolvedPlan", "resolve_plan"}:
        from app.agents.capability.resolve import ResolvedPlan, resolve_plan

        return {"ResolvedPlan": ResolvedPlan, "resolve_plan": resolve_plan}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
