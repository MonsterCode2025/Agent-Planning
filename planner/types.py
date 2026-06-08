from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field


Mode = Literal["quick", "standard", "deep"]
CognitiveStrategy = Literal["plan_execute", "react", "cot", "tot", "auto"]


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
    estimated_tokens: int = 0


class DecompositionResult(BaseModel):
    mode: Literal["simple", "standard", "complex"]
    complexity_score: float
    subtasks: list[Subtask]
    execution_strategy: Literal["parallel", "sequential", "dag"]
    # Shannon plan_schema_v2 借鉴字段
    concurrency_limit: int = 4
    token_estimates: dict[str, int] = Field(default_factory=dict)
    total_estimated_tokens: int = 0
    cognitive_strategy: CognitiveStrategy = "plan_execute"
    confidence: float = 0.0
    fallback_strategy: CognitiveStrategy = "react"
    agent_types: list[str] = Field(default_factory=list)


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


@dataclass(frozen=True)
class UsageInfo:
    """单次或累计 LLM 用量（不可变，可加法合并）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "UsageInfo") -> "UsageInfo":
        return UsageInfo(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
            calls=self.calls + other.calls,
        )


@dataclass(frozen=True)
class ChatResult:
    content: str
    usage: UsageInfo
    stage: str = ""
