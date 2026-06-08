from .llm import chat_json
from .types import DecompositionResult

_DECOMPOSE_SYSTEM = """你是一个任务分解专家，负责把模糊的研究请求拆解为可执行的子任务图。

## 核心要求
1. 子任务数量控制在 3-7 个（过细会导致协调成本 > 执行成本）
2. 每个子任务必须声明：
   - produces: 产出哪些信息字段（如 "company_basics", "products"）
   - consumes: 依赖哪些上游字段
   - dependencies: 依赖的上游 subtask id 列表
3. 用 boundaries.in_scope / out_of_scope 显式声明范围边界，防止子任务之间内容重叠
4. 给出 complexity_score (0.0-1.0)、mode（simple/standard/complex）
5. execution_strategy 规则：
   - 全部子任务 dependencies 都为空 → "parallel"
   - 形成严格链 → "sequential"
   - 部分依赖 → "dag"

## 输出严格 JSON
{
  "mode": "simple|standard|complex",
  "complexity_score": 0.0,
  "execution_strategy": "parallel|sequential|dag",
  "subtasks": [
    {
      "id": "subtask-1",
      "description": "用一句中文描述该子任务的目标",
      "dependencies": [],
      "produces": ["..."],
      "consumes": [],
      "suggested_tools": ["web_search", "web_fetch"],
      "boundaries": {
        "in_scope": ["..."],
        "out_of_scope": ["..."]
      }
    }
  ]
}

只输出 JSON，不要任何解释。"""


def decompose_task(query: str, available_tools: list[str]) -> DecompositionResult:
    user = (
        f"研究请求：{query}\n\n"
        f"可用工具：{', '.join(available_tools)}\n\n"
        f"请输出分解 JSON。"
    )
    data = chat_json(
        [
            {"role": "system", "content": _DECOMPOSE_SYSTEM},
            {"role": "user", "content": user},
        ]
    )
    return DecompositionResult.model_validate(data)
