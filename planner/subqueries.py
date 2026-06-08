from .llm import chat_json
from .types import CoverageGap, GeneratedSubquery, UsageInfo

_SUBQUERY_SYSTEM = """你是研究查询生成器。任务是生成针对性的子查询来填补覆盖缺口。

## 目标
1. 优先填补 critical 级别缺口
2. 避免与历史查询重复或重叠
3. 多语言感知：研究亚洲公司时优先使用本地语言（zh/ja/ko），通过 language_hint 字段声明
4. 备选搜索策略：
   - 标准 web_search 找不到时，建议 web_fetch 直接访问公司域名
   - LinkedIn / Crunchbase / 公司财报站

## 输出严格 JSON
{
  "subqueries": [
    {
      "id": "sq-1",
      "query": "具体的搜索查询字符串",
      "target_gap": "对应的缺口 area",
      "priority": "high|medium|low",
      "suggested_tools": ["web_search", "web_fetch"],
      "language_hint": "zh|en|ja|ko|null"
    }
  ]
}

只输出 JSON。"""


def generate_subqueries(
    query: str,
    critical_gaps: list[CoverageGap],
    max_n: int = 3,
) -> tuple[list[GeneratedSubquery], UsageInfo]:
    if not critical_gaps:
        return [], UsageInfo()
    gaps_text = "\n".join(
        f"- [{g.severity}] {g.area}: {g.description}" for g in critical_gaps
    )
    user = (
        f"原始研究请求：{query}\n\n"
        f"待填补的缺口：\n{gaps_text}\n\n"
        f"最多生成 {max_n} 个子查询。"
    )
    data, usage = chat_json(
        [
            {"role": "system", "content": _SUBQUERY_SYSTEM},
            {"role": "user", "content": user},
        ],
        stage="subqueries",
    )
    raw = data.get("subqueries", [])
    return [GeneratedSubquery.model_validate(sq) for sq in raw[:max_n]], usage
