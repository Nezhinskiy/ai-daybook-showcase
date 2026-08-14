from dataclasses import replace
from typing import get_type_hints

from app.agents.capability.expand import expand_intent
from app.agents.capability.resolve import (
    ResolvedPlan,
    resolve_plan,
    resolved_plan_scope_mismatch,
)
from app.agents.common.context_blocks import ContextBlockSpec
from app.agents.common.read_tools import ReadToolSpec
from app.agents.skill_loader import compose_skill
from app.domain_values import DomainAgentName, Intent


def test_resolved_plan_exposes_objects_and_accessors() -> None:
    resolved = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    assert resolved.domain is DomainAgentName.FOOD_AGENT
    assert any(tool.name == "search_recent_meals" for tool in resolved.read_tools)
    assert "log_meal" in resolved.action_kinds
    assert "create_agent_memory" in resolved.action_kinds
    assert "create_meal" in resolved.allowed_effect_tools
    assert "create_agent_memory" in resolved.allowed_effect_tools
    assert resolved.adapter_for("log_meal") is not None
    assert resolved.output_models()


def test_resolved_plan_contract_is_typed_to_runtime_objects() -> None:
    hints = get_type_hints(ResolvedPlan)

    assert hints["read_tools"] == tuple[ReadToolSpec, ...]
    assert hints["context_blocks"] == tuple[ContextBlockSpec, ...]


def test_composed_prompt_matches_explicit_resolved_fragments() -> None:
    resolved = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    assert resolved.skill == compose_skill(resolved.skill_fragments)
    assert "# FoodAgent" in resolved.skill
    assert "Capability: log_meal" in resolved.skill
    assert "Capability: vision" not in resolved.skill


def test_media_gated_tool_absent_without_media() -> None:
    resolved = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    assert all(tool.name != "recognize_image" for tool in resolved.read_tools)


def test_media_gated_tool_present_with_media() -> None:
    resolved = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=True))

    assert any(tool.name == "recognize_image" for tool in resolved.read_tools)


def test_resolved_action_kinds_keep_plan_order_with_ask_user_last() -> None:
    resolved = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    assert resolved.action_kinds == (
        "log_meal",
        "log_cooking",
        "cook_and_eat",
        "log_food_fact",
        "update_meal",
        "set_nutrition_goals",
        "create_agent_memory",
        "update_agent_memory",
        "deactivate_agent_memory",
        "ask_user",
    )


def test_adapter_for_unknown_kind_returns_none() -> None:
    resolved = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    assert resolved.adapter_for("unknown") is None


def test_scope_mismatch_names_action_kinds_not_serialized() -> None:
    expected = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))
    tampered = expected.plan.model_copy(
        update={
            "allowed_action_kinds": [
                kind for kind in expected.plan.allowed_action_kinds if kind != "log_meal"
            ]
        }
    )

    reason = resolved_plan_scope_mismatch(resolve_plan(tampered), expected)

    assert reason is not None
    assert reason.startswith("plan_action_kinds:")
    assert ":expected_action_kinds:" in reason
    assert "log_meal" in reason


def test_scope_mismatch_names_read_tools_not_serialized() -> None:
    expected = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))
    tampered = expected.plan.model_copy(
        update={
            "read_tools": [
                name for name in expected.plan.read_tools if name != "search_recent_meals"
            ]
        }
    )

    reason = resolved_plan_scope_mismatch(resolve_plan(tampered), expected)

    assert reason is not None
    assert reason.startswith("plan_read_tools:")
    assert ":expected_read_tools:" in reason
    assert "search_recent_meals" in reason


def test_scope_mismatch_serialized_is_last_resort_for_unexplained_drift() -> None:
    expected = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))
    tampered = expected.plan.model_copy(
        update={"allowed_effect_tools": list(reversed(expected.plan.allowed_effect_tools))}
    )
    actual = replace(expected, plan=tampered)

    assert resolved_plan_scope_mismatch(actual, expected) == "plan_serialized_mismatch"


def test_codec_projection_keeps_ordered_first_seen_fields_without_kind() -> None:
    resolved = resolve_plan(expand_intent(Intent.FOOD_LOG, has_media=False))

    fields = resolved.codec_projection()

    assert fields == (
        "title",
        "raw_input",
        "ingredients",
        "nutrition_selection",
        "source_attachment_ids",
        "is_alco",
        "nutrition_confidence",
        "meal_date",
        "total_quantity",
        "started_at",
        "cooked_at",
        "duration_minutes",
        "portion_quantity",
        "name",
        "aliases",
        "brand",
        "barcode",
        "package_quantity_raw",
        "package_quantity",
        "nutrition",
        "basis_origin",
        "catalog_source",
        "evidence",
        "confidence",
        "meal_id",
        "unlink_batch",
        "portion_factor",
        "calorie_target",
        "protein_target_g",
        "fat_target_g",
        "carbs_target_g",
        "memory_type",
        "key",
        "content",
        "payload",
        "id",
        "reason",
        "question",
        "options",
    )
    assert "kind" not in fields
