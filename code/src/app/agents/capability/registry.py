from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from functools import cache
from types import MappingProxyType
from typing import Any

from app.agents.capability.model import Action, Capability, IntentBundle, SkillFragment
from app.agents.common.context_blocks import ContextBlockSpec
from app.agents.common.read_tools import ReadToolSpec, query_contract_violation
from app.agents.common.units import UNIVERSAL_ACTIONS, ConversationCapability
from app.domain_values import TOOL_NAMES, DomainAgentName, Intent, domain_of_intent


def _all_capabilities(extra_capabilities: tuple[Capability, ...] = ()) -> list[Capability]:
    out: list[Capability] = []
    for bundle in INTENT_BUNDLES.values():
        out.extend(bundle.capabilities)
    out.extend(extra_capabilities)
    return out


def _all_actions(extra_capabilities: tuple[Capability, ...] = ()) -> list[Action[Any]]:
    out: list[Action[Any]] = []
    for cap in _all_capabilities(extra_capabilities):
        out.extend(cap.actions)
    for bundle in INTENT_BUNDLES.values():
        out.extend(bundle.intent_write_actions)
    # No bundle lists the universal actions, so the registry reaches them here.
    out.extend(UNIVERSAL_ACTIONS)
    return out


def _all_read_tools(extra_capabilities: tuple[Capability, ...] = ()) -> list[ReadToolSpec]:
    out: list[ReadToolSpec] = []
    for cap in _all_capabilities(extra_capabilities):
        out.extend(cap.read_tools)
    for bundle in INTENT_BUNDLES.values():
        out.extend(bundle.intent_read_tools)
    return out


def _all_context_blocks(
    extra_capabilities: tuple[Capability, ...] = (),
) -> list[ContextBlockSpec]:
    out: list[ContextBlockSpec] = []
    for cap in _all_capabilities(extra_capabilities):
        out.extend(cap.context_blocks)
    for bundle in INTENT_BUNDLES.values():
        out.extend(bundle.intent_context)
    return out


def _all_skill_fragments(extra_capabilities: tuple[Capability, ...] = ()) -> list[SkillFragment]:
    out: list[SkillFragment] = []
    for cap in _all_capabilities(extra_capabilities):
        if cap.skill_fragment is not None:
            out.append(cap.skill_fragment)
    for bundle in INTENT_BUNDLES.values():
        out.extend(bundle.intent_skill)
    return out


def _index[T](items: Iterable[T], key: Callable[[T], str]) -> dict[str, T]:
    out: dict[str, T] = {}
    for item in items:
        name = key(item)
        existing = out.get(name)
        if existing is not None and existing is not item:
            raise AssertionError(f"duplicate name {name!r} across the flat capability registry")
        out[name] = item
    return out


def _shared_index[T](items: Iterable[T], key: Callable[[T], str]) -> Mapping[str, T]:
    """Publish one read-only index of a derived registry.

    These five accessors are looked up per name inside `resolve_plan`'s comprehensions, so a
    per-call rebuild walked every capability and intent bundle once per plan element on the
    request path. The object graph is complete at import — `INTENT_BUNDLES` is a module
    constant and `assert_registry_consistent()` runs below it — so the index can be built
    once and shared. It is published read-only because a shared mutable dict would let one
    caller's write reach every other reader.
    """
    return MappingProxyType(_index(items, key))


@cache
def capability_by_name() -> Mapping[str, Capability]:
    return _shared_index(_all_capabilities(), lambda capability: capability.name)


@cache
def read_tool_by_name() -> Mapping[str, ReadToolSpec]:
    return _shared_index(_all_read_tools(), lambda read_tool: read_tool.name)


@cache
def context_block_by_name() -> Mapping[str, ContextBlockSpec]:
    return _shared_index(_all_context_blocks(), lambda context_block: context_block.name)


@cache
def action_by_kind() -> Mapping[str, Action[Any]]:
    return _shared_index(_all_actions(), lambda action: action.kind)


@cache
def skill_fragment_by_name() -> Mapping[str, SkillFragment]:
    return _shared_index(_all_skill_fragments(), lambda skill_fragment: skill_fragment.name)


def read_domains_of_intent(intent: Intent) -> frozenset[DomainAgentName]:
    """The write-domains a query intent reads, derived from the object graph: union of
    ``reads_domains`` over the intent bundle's capabilities. A write intent reads nothing
    (its bundle's capabilities declare no ``reads_domains``)."""
    bundle = INTENT_BUNDLES.get(intent)
    if bundle is None:
        return frozenset()
    domains: set[DomainAgentName] = set()
    for capability in bundle.capabilities:
        domains.update(capability.reads_domains)
    return frozenset(domains)


def _load_intent_bundles() -> dict[Intent, IntentBundle]:
    from app.agents.activity.units import ACTIVITY_BUNDLES
    from app.agents.faq.units import FAQ_BUNDLES
    from app.agents.food.units import FOOD_BUNDLES
    from app.agents.inventory.units import INVENTORY_BUNDLES
    from app.agents.journal.units import JOURNAL_BUNDLES
    from app.agents.planning.units import PLANNING_BUNDLES
    from app.agents.profile.units import PROFILE_BUNDLES
    from app.agents.query.units import QUERY_BUNDLES
    from app.agents.raw_events.units import RAW_EVENTS_BUNDLES
    from app.agents.raw_events_analyzer.units import RAW_EVENT_ANALYSIS_BUNDLES

    return {
        **FOOD_BUNDLES,
        **ACTIVITY_BUNDLES,
        **PLANNING_BUNDLES,
        **QUERY_BUNDLES,
        **PROFILE_BUNDLES,
        **INVENTORY_BUNDLES,
        **JOURNAL_BUNDLES,
        **FAQ_BUNDLES,
        **RAW_EVENTS_BUNDLES,
        **RAW_EVENT_ANALYSIS_BUNDLES,
    }


def _require_conversational_core(bundles: Mapping[Intent, IntentBundle]) -> None:
    """Every bundle must carry ConversationCapability — the one universal capability.

    Memory and Vision are opt-in tiers (profile_update and inventory_delete carry neither;
    query bundles carry no Vision), so only Conversation is enforced.
    """
    for intent, bundle in bundles.items():
        if not any(capability is ConversationCapability for capability in bundle.capabilities):
            raise AssertionError(f"intent bundle {intent!r} missing ConversationCapability")


# Read tools that never write to tool_calls (pure vision/computation, no DB effect) and so
# sit outside TOOL_NAMES by design. Module-level (not just a local inside
# assert_registry_consistent) so tests can import the real accessor directly instead of
# re-declaring a duplicate literal (AGENTS.md principle 11 — no side registries).
_non_db_read_tools = {"recognize_image", "lookup_product_nutrition", "caption_screenshot"}


def assert_registry_consistent(
    extra_capabilities: tuple[Capability, ...] = (),
) -> None:
    _index(
        _all_capabilities(extra_capabilities),
        lambda capability: capability.name,
    )
    _index(_all_read_tools(extra_capabilities), lambda read_tool: read_tool.name)
    _index(_all_context_blocks(extra_capabilities), lambda context_block: context_block.name)
    _index(_all_actions(extra_capabilities), lambda action: action.kind)
    _index(_all_skill_fragments(extra_capabilities), lambda skill_fragment: skill_fragment.name)

    for skill_fragment in _all_skill_fragments(extra_capabilities):
        if not skill_fragment.path.exists():
            raise AssertionError(f"missing skill fragment path: {skill_fragment.path}")

    for action in _all_actions(extra_capabilities):
        for effect_tool in action.effect_tools:
            if effect_tool.name not in TOOL_NAMES:
                raise AssertionError(
                    f"unknown effect tool {effect_tool.name!r} for action {action.kind!r}"
                )

    for read_tool in _all_read_tools(extra_capabilities):
        if read_tool.name not in TOOL_NAMES and read_tool.name not in _non_db_read_tools:
            raise AssertionError(f"unknown read tool name: {read_tool.name!r}")
        # A declared query contract is only worth what its argument surface makes reachable;
        # the spec owns the rule, this loop is just where every registered spec meets it.
        violation = query_contract_violation(read_tool)
        if violation is not None:
            raise AssertionError(violation)

    for intent, bundle in INTENT_BUNDLES.items():
        expected_agent = domain_of_intent(intent)
        if bundle.agent != expected_agent:
            raise AssertionError(
                f"intent bundle agent mismatch for {intent}: "
                f"expected {expected_agent}, got {bundle.agent}"
            )

    _require_conversational_core(INTENT_BUNDLES)


# Read-only for the same reason the derived indexes are: the accessors below cache what
# they build from it, so a post-import mutation would reach some readers and not others.
# Callers that need a variant build their own `dict(INTENT_BUNDLES)`.
INTENT_BUNDLES: Mapping[Intent, IntentBundle] = MappingProxyType(_load_intent_bundles())


assert_registry_consistent()
