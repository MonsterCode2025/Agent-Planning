from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .llm import chat
from .tools import web_fetch, web_search
from .types import Subtask, SubtaskResult


def topological_layers(subtasks: list[Subtask]) -> list[list[Subtask]]:
    """Group subtasks into layers, each layer runnable in parallel."""
    id_to_sub = {s.id: s for s in subtasks}
    in_degree = {s.id: 0 for s in subtasks}
    for s in subtasks:
        for dep in s.dependencies:
            if dep not in id_to_sub:
                raise ValueError(f"Subtask {s.id} depends on unknown {dep}")
            in_degree[s.id] += 1

    remaining = set(id_to_sub)
    layers: list[list[Subtask]] = []
    while remaining:
        ready = [sid for sid in remaining if in_degree[sid] == 0]
        if not ready:
            raise ValueError("Cyclic dependency detected among subtasks")
        layers.append([id_to_sub[sid] for sid in ready])
        for sid in ready:
            remaining.discard(sid)
            for s in subtasks:
                if sid in s.dependencies and s.id in remaining:
                    in_degree[s.id] -= 1
    return layers


_SUBTASK_TEMPLATE = """你是一名严谨的研究员，正在执行一个子任务。请基于提供的资料完成该子任务，并严格遵守范围限定。

## 子任务
{description}

## 范围限定
- 范围内（必须覆盖）：{in_scope}
- 范围外（必须排除）：{out_of_scope}

## 应当产出的字段
{produces}

## 已知上下文（来自上游子任务）
{context}

## 搜索结果（标题 + 摘要）
{sources}

## 抓取的网页正文片段
{fetched}

## 输出要求
1. 中文，结构化（用小标题/列表）
2. 只输出范围内的事实，不要复述范围外内容
3. 引用来源时用 [来源] 标注（如 [来源 1]）
4. 不确定的信息明确标注「未确认」
"""


def execute_subtask(
    subtask: Subtask,
    context: dict[str, str],
    language: str = "en",
) -> SubtaskResult:
    try:
        consumed = "\n".join(
            f"- {k}: {v[:600]}" for k, v in context.items() if k in subtask.consumes
        ) or "(无)"

        search_results: list[dict] = []
        if "web_search" in subtask.suggested_tools or not subtask.suggested_tools:
            search_results = web_search(subtask.description, language=language, num=4)

        sources = "\n".join(
            f"[{i+1}] {r['title']} ({r['link']})\n    {r['snippet']}"
            for i, r in enumerate(search_results)
        ) or "(无)"

        fetched_parts: list[str] = []
        if "web_fetch" in subtask.suggested_tools:
            for r in search_results[:2]:
                if not r.get("link"):
                    continue
                text = web_fetch(r["link"], max_chars=1500)
                fetched_parts.append(f"### {r['title']}\n{text}")
        fetched = "\n\n".join(fetched_parts) or "(未抓取)"

        in_scope = ", ".join(subtask.boundaries.in_scope) if subtask.boundaries else "(未声明)"
        out_of_scope = ", ".join(subtask.boundaries.out_of_scope) if subtask.boundaries else "(未声明)"
        produces = ", ".join(subtask.produces) or "(未声明)"

        prompt = _SUBTASK_TEMPLATE.format(
            description=subtask.description,
            in_scope=in_scope,
            out_of_scope=out_of_scope,
            produces=produces,
            context=consumed,
            sources=sources,
            fetched=fetched,
        )
        result = chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            stage="subtask",
        )
        return SubtaskResult(
            subtask_id=subtask.id,
            description=subtask.description,
            content=result.content,
        )
    except Exception as e:
        return SubtaskResult(
            subtask_id=subtask.id,
            description=subtask.description,
            content="",
            error=str(e),
        )


def execute_layer(
    layer: list[Subtask],
    context: dict[str, str],
    language: str = "en",
    max_concurrency: Optional[int] = None,
) -> list[SubtaskResult]:
    """并发执行同一层的子任务。

    max_concurrency 来自分解阶段的 `concurrency_limit`（Shannon 借鉴），
    实际 worker 数取 min(max_concurrency, len(layer)) 并保底 1。
    """
    if len(layer) == 1:
        return [execute_subtask(layer[0], context, language)]
    cap = max_concurrency if (max_concurrency and max_concurrency > 0) else 4
    workers = max(1, min(cap, len(layer)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda s: execute_subtask(s, context, language), layer))
