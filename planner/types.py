from typing import Literal, Optional

from pydantic import BaseModel, Field


class BoundariesSpec(BaseModel):
    in_scope: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class Subtask(BaseModel):
    id: str
    description: str
    dependencies: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    suggested_tools: list[str] = Field(default_factory=list)
    boundaries: Optional[BoundariesSpec] = None


class DecompositionResult(BaseModel):
    mode: Literal["simple", "standard", "complex"]
    complexity_score: float
    subtasks: list[Subtask]
    execution_strategy: Literal["parallel", "sequential", "dag"]


class SubtaskResult(BaseModel):
    subtask_id: str
    description: str
    content: str
    error: Optional[str] = None


class CoverageGap(BaseModel):
    area: str
    description: str
    severity: Literal["critical", "optional"]


class CoverageEvaluationResult(BaseModel):
    overall_coverage: float
    critical_gaps: list[CoverageGap] = Field(default_factory=list)
    optional_gaps: list[CoverageGap] = Field(default_factory=list)
    should_continue: bool
    recommended_action: Literal["continue", "complete"]
    confidence_level: Literal["high", "medium", "low"] = "high"
    guardrail_triggered: list[str] = Field(default_factory=list)


class GeneratedSubquery(BaseModel):
    id: str
    query: str
    target_gap: str
    priority: Literal["high", "medium", "low"] = "medium"
    suggested_tools: list[str] = Field(default_factory=list)
    language_hint: Optional[str] = None
