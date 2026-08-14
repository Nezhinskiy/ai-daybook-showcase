import uuid

from app.agents.capability.expand import expand_intent
from app.agents.capability.registry import action_by_kind
from app.agents.capability.resolve import resolve_plan
from app.agents.common.guard import capability_guard_rejection
from app.agents.common.units import UNIVERSAL_ACTION_KINDS, AskUserAction
from app.agents.inventory.note_actions import CreateTaskFromNoteActionOutput
from app.contracts import PlannedToolCall
from app.domain_values import Intent


class _Action:
    def __init__(self, kind: str) -> None:
        self.kind = kind


def test_guard_rejects_out_of_bundle_action() -> None:
    plan = resolve_plan(expand_intent(Intent.FOOD_CORRECTION, has_media=False))

    rejection = capability_guard_rejection([_Action("log_meal")], [], plan)

    assert rejection == "disallowed_action:log_meal"


def test_guard_rejects_empty_actions() -> None:
    plan = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    rejection = capability_guard_rejection([], [], plan)

    assert rejection == "empty_actions"


def test_guard_rejects_out_of_bundle_tool() -> None:
    plan = resolve_plan(expand_intent(Intent.FOOD_CORRECTION, has_media=False))

    rejection = capability_guard_rejection(
        [_Action("update_meal")],
        [PlannedToolCall(tool_name="create_meal", input={})],
        plan,
    )

    assert rejection == "disallowed_effect_tool:create_meal"


def test_guard_allows_in_bundle() -> None:
    plan = resolve_plan(expand_intent(Intent.FOOD_CORRECTION, has_media=False))

    assert capability_guard_rejection([_Action("ask_user")], [], plan) is None


def test_guard_scopes_cross_domain_note_to_task_by_bundle() -> None:
    # J1-e N2 is the first cross-domain write-tool reuse: an inventory decision
    # (create_task_from_note) plans the planning-owned create_task effect tool. The
    # guard is bundle-scoped, not domain-scoped — the same decision must be rejected
    # fail-closed under a bundle that does not compose NoteToTaskCapability
    # (INVENTORY_LOG) and accepted under one that does (INVENTORY_NOTE_LOG).
    decision = CreateTaskFromNoteActionOutput(
        kind="create_task_from_note",
        note_id=uuid.uuid4(),
        title="изучить статью про сон",
        raw_input="да, сделай задачу",
    )

    without_capability = resolve_plan(expand_intent(Intent.INVENTORY_LOG, has_media=False))
    rejection = capability_guard_rejection([decision], [], without_capability)
    assert rejection == "disallowed_action:create_task_from_note"

    with_capability = resolve_plan(expand_intent(Intent.INVENTORY_NOTE_LOG, has_media=False))
    adapter = with_capability.adapter_for(decision.kind)
    assert adapter is not None
    planned = adapter(decision)
    assert [call.tool_name for call in planned] == ["create_task"]
    assert capability_guard_rejection([decision], planned, with_capability) is None


def test_universal_action_kinds_derived_from_flag() -> None:
    # The guard's always-allowed set is derived from the ``universal`` flag on the
    # Action object, not a hardcoded literal. ask_user is the canonical universal action.
    assert AskUserAction.universal is True
    assert set(UNIVERSAL_ACTION_KINDS) == {AskUserAction.kind}


def test_universal_action_kinds_match_registry() -> None:
    # UNIVERSAL_ACTIONS in common/units.py is a hand-authored tuple: a new Action
    # with universal=True that is not added there would silently miss the guard's
    # allow-set. The derived registry is the other source of truth, so pin both
    # directions of drift: every universal-flagged action reachable through the
    # object graph is in UNIVERSAL_ACTION_KINDS, and nothing else is.
    registry_universal = {kind for kind, action in action_by_kind().items() if action.universal}
    assert registry_universal == set(UNIVERSAL_ACTION_KINDS)
