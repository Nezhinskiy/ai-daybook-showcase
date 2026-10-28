from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel

    from app.agents.common.context_blocks import ContextBlockSpec
    from app.agents.common.decision_materializer import MaterializedActionAdaptation
    from app.agents.common.read_tools import ReadToolSpec
    from app.contracts import PlannedToolCall
    from app.domain_values import DomainAgentName


@dataclass(frozen=True)
class SkillFragment:
    """A prompt fragment backed by a Markdown file. Self-locating (carries its path)."""

    name: str
    path: Path


@dataclass(frozen=True)
class EffectTool:
    """A stable wire id for a domain write tool. ``name`` must be in TOOL_NAMES."""

    name: str


def materialized_only(action: BaseModel) -> list[PlannedToolCall]:
    """The plain adapter of an action whose calls only its materialized adapter plans.

    Finalize binds a materialized result to every action that has a materialized adapter
    before any plain adapter runs, and fails the turn closed when one is missing, so this is
    never the path such an action's write takes. It refuses rather than planning a call.
    `Action` accepts it only beside a `materialized_adapter`.
    """
    from app.agents.common.decision_materializer import DecisionMaterializationError

    del action
    raise DecisionMaterializationError("missing_materialized_action_result")


@dataclass(frozen=True)
class Action[ActionOutputT: BaseModel]:
    """Full, reusable definition of one action kind."""

    kind: str
    output_model: type[ActionOutputT]
    effect_tools: tuple[EffectTool, ...]
    adapter: Callable[[ActionOutputT], list[PlannedToolCall]]
    materialized_adapter: (
        Callable[[ActionOutputT, BaseModel], MaterializedActionAdaptation] | None
    ) = None
    codec_projection: tuple[str, ...] = ()
    """Whitelist of output_model field names projected into the Codex schema.

    Types and requiredness are derived from output_model.model_json_schema() —
    never hand-authored (a hand-written schema would duplicate the object graph).
    """
    request_fragment_field: str | None = None
    """Output field replaced with the exact request fragment after model execution."""
    requires_media: bool = False

    def __post_init__(self) -> None:
        if self.adapter is materialized_only and self.materialized_adapter is None:
            msg = f"Action {self.kind!r} is materialized_only but has no materialized_adapter"
            raise ValueError(msg)
        field_name = self.request_fragment_field
        if field_name is None:
            return
        field = self.output_model.model_fields.get(field_name)
        if field is None:
            msg = (
                f"Action {self.kind!r} request_fragment_field "
                f"{field_name!r} is not an output-model field"
            )
            raise ValueError(msg)
        if field_name == "kind" or field.annotation is not str:
            msg = (
                f"Action {self.kind!r} request_fragment_field {field_name!r} "
                "must identify a non-kind str output-model field"
            )
            raise ValueError(msg)


@dataclass(frozen=True)
class Capability:
    name: str
    skill_fragment: SkillFragment | None = None
    actions: tuple[Action[Any], ...] = ()
    read_tools: tuple[ReadToolSpec, ...] = ()
    context_blocks: tuple[ContextBlockSpec, ...] = ()
    requires_media: bool = False
    # write-domains this capability reads (SOFT-edge source)
    reads_domains: tuple[DomainAgentName, ...] = ()


@dataclass(frozen=True)
class IntentBundle:
    agent: DomainAgentName
    capabilities: tuple[Capability, ...] = ()
    intent_skill: tuple[SkillFragment, ...] = ()
    intent_write_actions: tuple[Action[Any], ...] = ()
    intent_read_tools: tuple[ReadToolSpec, ...] = ()
    intent_context: tuple[ContextBlockSpec, ...] = ()
    # Opt out of the universal actions (``UNIVERSAL_ACTIONS`` in ``agents/common/units.py``,
    # listed by no bundle) that ``expand_intent`` appends to every other plan. The guard
    # admits only plan actions, so an opted-out bundle rejects them at both barriers. Set
    # only where the agent's decision union cannot parse them.
    omit_universal_actions: bool = False


def dedupe_by_identity[T](items: Iterable[T]) -> list[T]:
    """Stable dedup by object identity (``is``), preserving first-seen order."""
    seen: set[int] = set()
    out: list[T] = []
    for item in items:
        item_id = id(item)
        if item_id not in seen:
            seen.add(item_id)
            out.append(item)
    return out
