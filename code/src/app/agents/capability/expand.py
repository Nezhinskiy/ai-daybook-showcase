from __future__ import annotations

from collections.abc import Iterable

from app.agents.capability.model import dedupe_by_identity
from app.agents.capability.plan import CapabilityPlan
from app.agents.capability.registry import INTENT_BUNDLES
from app.domain_values import Intent, domain_of_intent

UNSUPPORTED_INTENT_MESSAGE = "Пока не умею надёжно обработать это сообщение."


def _ask_user_only_plan(intent: Intent) -> CapabilityPlan:
    return CapabilityPlan(
        domain=domain_of_intent(intent),
        intent=intent,
        skill_fragments=[],
        allowed_action_kinds=["ask_user"],
        allowed_effect_tools=["ask_user"],
        read_tools=[],
        context_blocks=["time"],
    )


def _keep(unit_requires_media: bool, has_media: bool) -> bool:
    return has_media or not unit_requires_media


def _dedupe_values(items: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)


def is_supported_intent(intent: Intent) -> bool:
    return intent in INTENT_BUNDLES


def expand_intent(intent: Intent, *, has_media: bool) -> CapabilityPlan:
    bundle = INTENT_BUNDLES.get(intent)
    if bundle is None:
        return _ask_user_only_plan(intent)

    caps = [
        capability
        for capability in dedupe_by_identity(bundle.capabilities)
        if _keep(capability.requires_media, has_media)
    ]
    skill_frags = dedupe_by_identity(
        [
            *bundle.intent_skill,
            *(
                capability.skill_fragment
                for capability in caps
                if capability.skill_fragment is not None
            ),
        ]
    )
    actions = dedupe_by_identity(
        [
            *(
                action
                for capability in caps
                for action in capability.actions
                if _keep(action.requires_media, has_media)
            ),
            *(
                action
                for action in bundle.intent_write_actions
                if _keep(action.requires_media, has_media)
            ),
        ]
    )
    read_tools = [
        read_tool
        for read_tool in dedupe_by_identity(
            [
                *bundle.intent_read_tools,
                *(read_tool for capability in caps for read_tool in capability.read_tools),
            ]
        )
        if _keep(read_tool.requires_media, has_media)
    ]
    context_blocks = dedupe_by_identity(
        [
            *bundle.intent_context,
            *(context_block for capability in caps for context_block in capability.context_blocks),
        ]
    )
    action_kinds = [action.kind for action in actions]
    effect_tools = _dedupe_values(
        effect_tool.name for action in actions for effect_tool in action.effect_tools
    )

    return CapabilityPlan(
        domain=domain_of_intent(intent),
        intent=intent,
        skill_fragments=[skill_fragment.name for skill_fragment in skill_frags],
        allowed_action_kinds=action_kinds,
        allowed_effect_tools=effect_tools,
        read_tools=[read_tool.name for read_tool in read_tools],
        context_blocks=[context_block.name for context_block in context_blocks],
    )
