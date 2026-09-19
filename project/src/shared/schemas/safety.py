"""Safety decision schema."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SafetyDecision(BaseModel):
    """Deterministic safety gate result."""
    allowed: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
