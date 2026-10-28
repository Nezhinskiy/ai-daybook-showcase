from __future__ import annotations

from collections.abc import Iterable

from app.agents.capability.model import dedupe_by_identity
from app.agents.capability.plan import CapabilityPlan
from app.agents.capability.registry import INTENT_BUNDLES
from app.agents.common.context_blocks import TimeContext
from app.agents.common.units import UNIVERSAL_ACTIONS
from app.domain_values import Intent, domain_of_intent

# No pre-rendered unsupported-intent message lives here. Its one consumer
# (activities/runtime/agent_exec.py's _unsupported_intent_result) holds an ExecuteAgentInput
# with a resolved response_language, so it reads runtime_copy's UNSUPPORTED_INTENT_KEY at
# render time instead. A module-level constant here could only pin one language.


def _universal_only_plan(intent: Intent, *, has_media: bool) -> CapabilityPlan:
    """The plan for an intent with no bundle: the universal actions and nothing else."""
    actions = [action for action in UNIVERSAL_ACTIONS if _keep(action.requires_media, has_media)]
    return CapabilityPlan(
        domain=domain_of_intent(intent),
        intent=intent,
        skill_fragments=[],
        allowed_action_kinds=[action.kind for action in actions],
        allowed_effect_tools=_dedupe_values(
            effect_tool.name for action in actions for effect_tool in action.effect_tools
        ),
        read_tools=[],
        context_blocks=[TimeContext.name],
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


def intent_reaches_effect_tool(intent: Intent, tool_name: str) -> bool:
    """Whether a turn routed to *intent* can express a call to *tool_name*.

    Answered off the expanded plan rather than a list of intents, so a capability added to
    or removed from a bundle changes the answer with nothing else edited. ``has_media`` is
    ``False`` because the caller this exists for is a post-commit card's tap, which
    re-enters on the clarification's stored intent carrying no attachment — the narrowest
    plan that turn can get, and therefore the honest one to promise against.

    A card offering to hand the user back to an agent that has no action for the fix is
    worse than no card, so a materializer asks this before emitting one.
    """
    return tool_name in expand_intent(intent, has_media=False).allowed_effect_tools


def expand_intent(intent: Intent, *, has_media: bool) -> CapabilityPlan:
    bundle = INTENT_BUNDLES.get(intent)
    if bundle is None:
        return _universal_only_plan(intent, has_media=has_media)

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
            # Universal actions go last: no bundle lists them, and the plan's action order
            # is the schema's arm order.
            *(
                ()
                if bundle.omit_universal_actions
                else (
                    action
                    for action in UNIVERSAL_ACTIONS
                    if _keep(action.requires_media, has_media)
                )
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
