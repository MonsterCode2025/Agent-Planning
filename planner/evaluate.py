from .llm import chat_json
from .types import CoverageEvaluationResult, UsageInfo

_EVAL_SYSTEM = """你是研究质量评估专家。请评估当前综合结果对原始请求的覆盖度。

## 输出严格 JSON
{
  "overall_coverage": 0.0-1.0,
  "critical_gaps": [
    {"area": "...", "description": "...", "severity": "critical"}
  ],
  "optional_gaps": [
    {"area": "...", "description": "...", "severity": "optional"}
  ],
  "should_continue": true/false,
  "recommended_action": "continue|complete",
  "confidence_level": "high|medium|low"
}

判断准则：
- critical_gaps 是回答原始请求必须填补的；optional_gaps 只是锦上添花
- 如果综合结果空洞或含糊不清，overall_coverage 不应超过 0.6
- 只输出 JSON，不要解释。"""


_COVERAGE_THRESHOLD = 0.85
_LOW_CONFIDENCE_LEN = 500


def evaluate_coverage(
    query: str,
    synthesis: str,
    iteration: int,
    max_iterations: int,
) -> tuple[CoverageEvaluationResult, UsageInfo]:
    """LLM 评估 + 确定性护栏（参见文章 10.5）。返回 (结果, 本次 LLM 调用用量)。"""
    user = (
        f"原始请求：{query}\n\n"
        f"当前迭代：{iteration}/{max_iterations}\n\n"
        f"当前综合结果（共 {len(synthesis)} 字）：\n{synthesis}\n\n"
        f"请输出评估 JSON。"
    )
    data, usage = chat_json(
        [
            {"role": "system", "content": _EVAL_SYSTEM},
            {"role": "user", "content": user},
        ],
        stage="evaluate",
    )
    result = CoverageEvaluationResult.model_validate(data)
    triggered: list[str] = []

    # 护栏 1：第一次迭代 + 低覆盖度 → 强制继续
    if iteration == 1 and result.overall_coverage < 0.5:
        result.should_continue = True
        result.recommended_action = "continue"
        triggered.append("rule1_first_iter_low_coverage")

    # 护栏 2：存在 critical 缺口 + 还有预算 → 强制继续
    if result.critical_gaps and iteration < max_iterations:
        result.should_continue = True
        result.recommended_action = "continue"
        triggered.append("rule2_critical_gaps_remaining_budget")

    # 护栏 3：达到最大迭代 → 强制停止
    if iteration >= max_iterations:
        result.should_continue = False
        result.recommended_action = "complete"
        triggered.append("rule3_max_iterations")

    # 护栏 4：综合结果太短但声称高覆盖度 → 置信度降级
    if len(synthesis) < _LOW_CONFIDENCE_LEN and result.overall_coverage > 0.7:
        result.confidence_level = "low"
        triggered.append("rule4_short_synthesis_high_coverage")

    # 质量已达标 + 无 critical 缺口 → 可以停止（即便还有预算）
    if (
        result.overall_coverage >= _COVERAGE_THRESHOLD
        and not result.critical_gaps
        and "rule3_max_iterations" not in triggered
    ):
        result.should_continue = False
        result.recommended_action = "complete"
        triggered.append("quality_threshold_met")

    result.guardrail_triggered = triggered
    return result, usage
