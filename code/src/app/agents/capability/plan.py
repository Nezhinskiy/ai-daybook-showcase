from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain_values import Intent


class CapabilityPlan(BaseModel):
    domain: str
    intent: Intent
    skill_fragments: list[str] = Field(default_factory=list)
    allowed_action_kinds: list[str] = Field(default_factory=list)
    allowed_effect_tools: list[str] = Field(default_factory=list)
    read_tools: list[str] = Field(default_factory=list)
    context_blocks: list[str] = Field(default_factory=list)
