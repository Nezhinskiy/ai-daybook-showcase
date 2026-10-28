import uuid

from app.agents.capability.expand import expand_intent
from app.agents.capability.registry import action_by_kind
from app.agents.capability.resolve import resolve_plan
from app.agents.common.guard import capability_guard_rejection
from app.agents.common.units import UNIVERSAL_ACTIONS, AskUserAction
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


def test_guard_admits_exactly_the_plan_action_kinds() -> None:
    # The plan is the one source of the action-kind allow-set: for every intent and media
    # state, a registered kind passes the action-kind barrier exactly when the expanded plan
    # carries it. A second allow-list beside the plan (the old universal-kind union) would
    # admit a kind the plan left out.
    for intent in Intent:
        for has_media in (False, True):
            plan = resolve_plan(expand_intent(intent, has_media=has_media))
            for kind in action_by_kind():
                rejection = capability_guard_rejection([_Action(kind)], [], plan)
                if kind in plan.action_kinds:
                    assert rejection is None, (intent, has_media, kind)
                else:
                    assert rejection == f"disallowed_action:{kind}", (intent, has_media, kind)


def test_opted_out_bundles_reject_ask_user_at_the_action_kind_barrier() -> None:
    # The raw-events recorder and analyzer opt out of the universal actions, so ask_user is
    # rejected as an action kind, before any effect tool is looked at.
    assert [action.kind for action in UNIVERSAL_ACTIONS] == [AskUserAction.kind]
    for intent in (Intent.RAW_EVENT_LOG, Intent.RAW_EVENT_ANALYSIS):
        for has_media in (False, True):
            plan = resolve_plan(expand_intent(intent, has_media=has_media))
            rejection = capability_guard_rejection(
                [_Action(AskUserAction.kind)],
                [PlannedToolCall(tool_name="ask_user", input={})],
                plan,
                allow_empty=True,
            )
            assert rejection == "disallowed_action:ask_user", (intent, has_media)


def test_registry_indexes_the_universal_actions() -> None:
    # No bundle lists a universal action, so the registry must reach them itself, or
    # resolve_plan's kind lookup fails on every plan that carries one.
    for action in UNIVERSAL_ACTIONS:
        assert action_by_kind()[action.kind] is action


def test_guard_rejects_an_action_object_that_has_no_kind() -> None:
    """A decision object without a string `kind` is rejected, never raised through.

    The guard takes `Sequence[object]` precisely so this stays a rejection code: it is the
    fail-closed boundary between a model's decision and the effect layer, so a shape it
    cannot read must produce `disallowed_action`, not an AttributeError that escapes into
    the caller's error path.
    """
    plan = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    assert capability_guard_rejection([object()], [], plan) == "disallowed_action:None"
    assert capability_guard_rejection([_Action(1)], [], plan) == "disallowed_action:1"  # type: ignore[arg-type]
