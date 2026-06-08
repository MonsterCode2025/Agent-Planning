from .llm import chat
from .types import SubtaskResult, UsageInfo


_SYNTH_TEMPLATE = """你是资深研究分析师。请基于以下子任务的产出，撰写一份针对原始请求的综合研究报告。

## 原始请求
{query}

## 子任务产出
{parts}

## 撰写要求
1. 结构化：根据请求自动选择合适的章节（公司基本面 / 产品矩阵 / 竞争对手 / 战略 / 风险 等）
2. 综合分析而非简单拼接：发现跨子任务的洞察、矛盾、趋势
3. 关键结论用 **粗体** 突出
4. 引用来源时保留 [来源 N] 标注
5. 中文输出，2000 字左右
6. 不要回顾"我做了哪些子任务"——只输出报告本身
"""


def synthesize(query: str, results: list[SubtaskResult]) -> tuple[str, UsageInfo]:
    valid = [r for r in results if not r.error and r.content]
    if not valid:
        return "_（所有子任务都失败了，无法综合。）_", UsageInfo()
    parts = "\n\n".join(
        f"### {r.description}（{r.subtask_id}）\n{r.content}" for r in valid
    )
    prompt = _SYNTH_TEMPLATE.format(query=query, parts=parts)
    result = chat(
        [{"role": "user", "content": prompt}],
        temperature=0.4,
        stage="synthesize",
    )
    return result.content, result.usage
