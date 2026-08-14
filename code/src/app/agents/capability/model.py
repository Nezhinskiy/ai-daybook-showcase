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
    # Kept in the guard's action-kind allow-set even when the action is not in the
    # resolved bundle (e.g. ask_user clarifications), via UNIVERSAL_ACTION_KINDS.
    # This covers only the action-kind barrier: the guard's effect-tool barrier still
    # admits tools from in-bundle actions alone, so a universal action emitted truly
    # outside the bundle is rejected unless its effect tool is also in scope (today
    # moot — every bundle includes ask_user). Explicit object property, not a
    # hardcoded special-case string in the guard.
    universal: bool = False

    def __post_init__(self) -> None:
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
