from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel

from app.agents.capability.model import Action, SkillFragment
from app.agents.capability.plan import CapabilityPlan
from app.agents.capability.registry import (
    action_by_kind,
    context_block_by_name,
    read_tool_by_name,
    skill_fragment_by_name,
)
from app.agents.common.context_blocks import ContextBlockSpec
from app.agents.common.read_tools import ReadToolSpec
from app.agents.skill_loader import compose_skill
from app.contracts import PlannedToolCall
from app.domain_values import DomainAgentName, Intent


@dataclass(frozen=True)
class ResolvedPlan:
    plan: CapabilityPlan
    skill_fragments: tuple[SkillFragment, ...]
    skill: str
    read_tools: tuple[ReadToolSpec, ...]
    context_blocks: tuple[ContextBlockSpec, ...]
    actions: tuple[Action[Any], ...]

    @property
    def domain(self) -> DomainAgentName:
        return DomainAgentName(self.plan.domain)

    @property
    def intent(self) -> Intent:
        return self.plan.intent

    @property
    def action_kinds(self) -> tuple[str, ...]:
        return tuple(action.kind for action in self.actions)

    @property
    def allowed_effect_tools(self) -> frozenset[str]:
        return frozenset(
            effect_tool.name for action in self.actions for effect_tool in action.effect_tools
        )

    def output_models(self) -> tuple[type[BaseModel], ...]:
        return tuple(action.output_model for action in self.actions)

    def codec_projection(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for action in self.actions:
            for name in action.codec_projection:
                seen.setdefault(name, None)
        return tuple(seen)

    def adapter_for(self, kind: str) -> Callable[[BaseModel], list[PlannedToolCall]] | None:
        for action in self.actions:
            if action.kind == kind:
                return cast(Callable[[BaseModel], list[PlannedToolCall]], action.adapter)
        return None

    def action_for_output(self, output: BaseModel) -> Action[Any] | None:
        """Resolve a runtime output through the canonical output-model object."""
        for action in self.actions:
            if type(output) is action.output_model:
                return action
        return None

    def materialized_adapter_for(
        self,
        output: BaseModel,
    ) -> Callable[[BaseModel, BaseModel], Any] | None:
        action = self.action_for_output(output)
        if action is None or action.materialized_adapter is None:
            return None
        return cast(Callable[[BaseModel, BaseModel], Any], action.materialized_adapter)


def resolve_plan(plan: CapabilityPlan) -> ResolvedPlan:
    fragments = tuple(skill_fragment_by_name()[name] for name in plan.skill_fragments)
    read_tools = tuple(read_tool_by_name()[name] for name in plan.read_tools)
    context_blocks = tuple(context_block_by_name()[name] for name in plan.context_blocks)
    actions = tuple(action_by_kind()[kind] for kind in plan.allowed_action_kinds)
    return ResolvedPlan(
        plan=plan,
        skill_fragments=fragments,
        skill=compose_skill(fragments),
        read_tools=read_tools,
        context_blocks=context_blocks,
        actions=actions,
    )


def canonical_resolved_plan(intent: Intent, *, has_media: bool) -> ResolvedPlan:
    from app.agents.capability.expand import expand_intent

    return resolve_plan(expand_intent(intent, has_media=has_media))


def resolved_plan_for_intent(
    plan: ResolvedPlan | None,
    *,
    intent: Intent,
    has_media: bool,
) -> tuple[ResolvedPlan, str | None]:
    expected = canonical_resolved_plan(intent, has_media=has_media)
    if plan is None:
        return expected, None
    return plan, resolved_plan_scope_mismatch(plan, expected)


def resolved_plan_scope_mismatch(actual: ResolvedPlan, expected: ResolvedPlan) -> str | None:
    if actual.domain != expected.domain:
        return f"plan_domain:{actual.domain}:expected_domain:{expected.domain}"
    if actual.intent != expected.intent:
        return f"plan_intent:{actual.intent}:expected_intent:{expected.intent}"
    actual_skill_fragments = _object_names(actual.skill_fragments)
    expected_skill_fragments = _object_names(expected.skill_fragments)
    if actual_skill_fragments != expected_skill_fragments:
        return (
            "plan_skill_fragments:"
            f"{','.join(actual_skill_fragments)}:expected_skill_fragments:"
            f"{','.join(expected_skill_fragments)}"
        )
    if actual.skill_fragments != expected.skill_fragments:
        return "plan_skill_fragment_specs_mismatch"
    if actual.skill != expected.skill:
        return "plan_skill_mismatch"
    if actual.action_kinds != expected.action_kinds:
        return (
            "plan_action_kinds:"
            f"{','.join(actual.action_kinds)}:expected_action_kinds:"
            f"{','.join(expected.action_kinds)}"
        )
    if actual.actions != expected.actions:
        return "plan_actions_mismatch"
    if actual.allowed_effect_tools != expected.allowed_effect_tools:
        return (
            "plan_effect_tools:"
            f"{','.join(sorted(actual.allowed_effect_tools))}:expected_effect_tools:"
            f"{','.join(sorted(expected.allowed_effect_tools))}"
        )
    actual_read_tools = _object_names(actual.read_tools)
    expected_read_tools = _object_names(expected.read_tools)
    if actual_read_tools != expected_read_tools:
        return (
            "plan_read_tools:"
            f"{','.join(actual_read_tools)}:expected_read_tools:{','.join(expected_read_tools)}"
        )
    if actual.read_tools != expected.read_tools:
        return "plan_read_tool_specs_mismatch"
    actual_context_blocks = _object_names(actual.context_blocks)
    expected_context_blocks = _object_names(expected.context_blocks)
    if actual_context_blocks != expected_context_blocks:
        return (
            "plan_context_blocks:"
            f"{','.join(actual_context_blocks)}:expected_context_blocks:"
            f"{','.join(expected_context_blocks)}"
        )
    if actual.context_blocks != expected.context_blocks:
        return "plan_context_block_specs_mismatch"
    # Last resort: catches plan drift not explained by any specific check above
    # (e.g. reordered serialized lists or a new CapabilityPlan field).
    if actual.plan.model_dump(mode="json") != expected.plan.model_dump(mode="json"):
        return "plan_serialized_mismatch"
    return None


def _object_names(objects: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(str(item.name) for item in objects)
