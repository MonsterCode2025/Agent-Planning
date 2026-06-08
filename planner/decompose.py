from .llm import chat_json
from .types import DecompositionResult, Mode, UsageInfo

_MODE_HINT: dict[Mode, str] = {
    "quick": "2-3 个子任务，只覆盖最核心维度，最省 token",
    "standard": "3-7 个子任务，覆盖主要维度，平衡深度与成本",
    "deep": "5-10 个子任务，多维度细化，包含交叉验证与对比",
}


def _decompose_system(mode: Mode) -> str:
    return f"""你是一个任务分解专家，负责把模糊的研究请求拆解为可执行的子任务图。

## 核心要求
1. 子任务粒度：{_MODE_HINT[mode]}
2. 每个子任务必须声明：
   - produces: 产出哪些信息字段（如 "company_basics"、"products"）
   - consumes: 依赖哪些上游字段
   - dependencies: 依赖的上游 subtask id 列表
   - estimated_tokens: 该子任务预估消耗的总 token 数（prompt + 输出）
3. 用 boundaries.in_scope / out_of_scope 显式声明范围边界，防止子任务之间内容重叠
4. 总体字段（plan_schema_v2 借鉴 Shannon）：
   - complexity_score (0.0-1.0)
   - mode（simple/standard/complex）
   - execution_strategy: dependencies 全空 → "parallel"；严格链 → "sequential"；部分依赖 → "dag"
   - concurrency_limit: 执行该 DAG 时建议的最大并发数（避免下游限流，2-6 较合理）
   - cognitive_strategy: 推荐推理模式，取值 plan_execute / react / cot / tot / auto
   - confidence: 对策略选择的置信度 (0.0-1.0)
   - fallback_strategy: 主策略失败时的回退（同上集合）
   - agent_types: 每个子任务建议的 agent 类型（如 ["researcher","analyst"]），长度与 subtasks 对齐
   - token_estimates: 子任务 id → 预估 token 的映射
   - total_estimated_tokens: 全部子任务的 token 预估之和

## 输出严格 JSON（除 JSON 外不要输出任何字符）
{{
  "mode": "simple|standard|complex",
  "complexity_score": 0.0,
  "execution_strategy": "parallel|sequential|dag",
  "concurrency_limit": 4,
  "cognitive_strategy": "plan_execute|react|cot|tot|auto",
  "confidence": 0.0,
  "fallback_strategy": "plan_execute|react|cot|tot|auto",
  "agent_types": ["researcher", "analyst"],
  "total_estimated_tokens": 0,
  "token_estimates": {{"subtask-1": 0}},
  "subtasks": [
    {{
      "id": "subtask-1",
      "description": "用一句中文描述该子任务的目标",
      "dependencies": [],
      "produces": ["..."],
      "consumes": [],
      "suggested_tools": ["web_search", "web_fetch"],
      "estimated_tokens": 0,
      "boundaries": {{
        "in_scope": ["..."],
        "out_of_scope": ["..."]
      }}
    }}
  ]
}}
"""


def decompose_task(
    query: str,
    available_tools: list[str],
    mode: Mode = "standard",
) -> tuple[DecompositionResult, UsageInfo]:
    user = (
        f"研究请求：{query}\n\n"
        f"可用工具：{', '.join(available_tools)}\n\n"
        f"分解粒度档位：{mode}\n\n"
        f"请输出 JSON。"
    )
    data, usage = chat_json(
        [
            {"role": "system", "content": _decompose_system(mode)},
            {"role": "user", "content": user},
        ],
        stage="decompose",
    )
    return DecompositionResult.model_validate(data), usage
