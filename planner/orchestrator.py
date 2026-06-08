import time
from typing import Iterator

from .decompose import decompose_task
from .evaluate import evaluate_coverage
from .execute import execute_layer, topological_layers
from .llm import get_tracker
from .logger import get_logger
from .subqueries import generate_subqueries
from .synthesize import synthesize
from .types import Mode, Subtask, SubtaskResult


MAX_ITERATIONS_DEFAULT = 3
AVAILABLE_TOOLS = ["web_search", "web_fetch"]

logger = get_logger("planner.orchestrator")


def _usage_snapshot() -> dict:
    totals, by_stage = get_tracker().snapshot()
    return {
        "total_tokens": totals.total_tokens,
        "total_prompt_tokens": totals.prompt_tokens,
        "total_completion_tokens": totals.completion_tokens,
        "total_cached_tokens": totals.cached_tokens,
        "total_cost_usd": totals.cost_usd,
        "total_calls": totals.calls,
        "by_stage": {
            k: {
                "tokens": v.total_tokens,
                "cost_usd": v.cost_usd,
                "calls": v.calls,
            }
            for k, v in by_stage.items()
        },
    }


def run_research(
    query: str,
    max_iterations: int = MAX_ITERATIONS_DEFAULT,
    language: str = "en",
    mode: Mode = "standard",
) -> Iterator[dict]:
    """完整 Planning 循环：分解 → DAG 执行 → 综合 → 迭代评估 → 补充查询。

    每个 yield 事件附带 `usage` 字段（累计 token + cost），final 事件含 by-stage 分布。
    """
    tracker = get_tracker()
    tracker.reset()
    started_at = time.monotonic()
    logger.info(
        "=== START research | query=%r | max_iterations=%d | language=%s | mode=%s ===",
        query,
        max_iterations,
        language,
        mode,
    )

    # === 阶段 1：分解 ===
    logger.info("[decompose] running mode=%s", mode)
    yield {"stage": "decompose", "status": "running", "usage": _usage_snapshot()}
    decomp, decomp_usage = decompose_task(query, AVAILABLE_TOOLS, mode=mode)
    logger.info(
        "[decompose] done | subtasks=%d | strategy=%s | complexity=%.2f | "
        "concurrency_limit=%d | cognitive=%s (conf=%.2f, fb=%s) | "
        "est_tokens=%d | usage_tokens=%d cost=$%.6f",
        len(decomp.subtasks),
        decomp.execution_strategy,
        decomp.complexity_score,
        decomp.concurrency_limit,
        decomp.cognitive_strategy,
        decomp.confidence,
        decomp.fallback_strategy,
        decomp.total_estimated_tokens,
        decomp_usage.total_tokens,
        decomp_usage.cost_usd,
    )
    yield {
        "stage": "decompose",
        "status": "done",
        "decomposition": decomp.model_dump(),
        "usage": _usage_snapshot(),
    }

    # === 阶段 2：拓扑分层执行 ===
    layers = topological_layers(decomp.subtasks)
    layer_summary = [[s.id for s in layer] for layer in layers]
    logger.info(
        "[execute] topological plan | layers=%s | concurrency_limit=%d",
        layer_summary,
        decomp.concurrency_limit,
    )
    yield {
        "stage": "execute",
        "status": "plan",
        "layers": layer_summary,
        "concurrency_limit": decomp.concurrency_limit,
        "usage": _usage_snapshot(),
    }

    all_results: list[SubtaskResult] = []
    context: dict[str, str] = {}

    for idx, layer in enumerate(layers):
        layer_ids = [s.id for s in layer]
        logger.info(
            "[execute] layer %d/%d running | subtasks=%s",
            idx,
            len(layers) - 1,
            layer_ids,
        )
        yield {
            "stage": "execute",
            "status": "layer_running",
            "layer_index": idx,
            "subtasks": layer_ids,
            "usage": _usage_snapshot(),
        }
        layer_results = execute_layer(
            layer,
            context,
            language=language,
            max_concurrency=decomp.concurrency_limit,
        )
        for sub, res in zip(layer, layer_results):
            all_results.append(res)
            if res.error:
                logger.warning("  subtask %s failed: %s", sub.id, res.error)
            else:
                for produced_key in sub.produces:
                    context[produced_key] = res.content
        errs = sum(1 for r in layer_results if r.error)
        logger.info(
            "[execute] layer %d done | results=%d | errors=%d",
            idx,
            len(layer_results),
            errs,
        )
        yield {
            "stage": "execute",
            "status": "layer_done",
            "layer_index": idx,
            "results": [r.model_dump() for r in layer_results],
            "usage": _usage_snapshot(),
        }

    # === 阶段 3：初始综合 ===
    logger.info("[synthesize] iter=0 running")
    yield {
        "stage": "synthesize",
        "status": "running",
        "iteration": 0,
        "usage": _usage_snapshot(),
    }
    current_synthesis, _ = synthesize(query, all_results)
    logger.info("[synthesize] iter=0 done | length=%d", len(current_synthesis))
    yield {
        "stage": "synthesize",
        "status": "done",
        "iteration": 0,
        "synthesis": current_synthesis,
        "usage": _usage_snapshot(),
    }

    # === 阶段 4：迭代评估循环 ===
    completed_iterations = 0
    final_coverage = None
    complete_reason = "max_iterations_loop_end"

    for iteration in range(1, max_iterations + 1):
        completed_iterations = iteration
        logger.info("[evaluate] iter=%d running", iteration)
        yield {
            "stage": "evaluate",
            "status": "running",
            "iteration": iteration,
            "usage": _usage_snapshot(),
        }
        coverage, _ = evaluate_coverage(
            query, current_synthesis, iteration, max_iterations
        )
        final_coverage = coverage
        logger.info(
            "[evaluate] iter=%d done | coverage=%.0f%% | critical_gaps=%d | "
            "continue=%s | guardrails=%s",
            iteration,
            coverage.overall_coverage * 100,
            len(coverage.critical_gaps),
            coverage.should_continue,
            coverage.guardrail_triggered,
        )
        yield {
            "stage": "evaluate",
            "status": "done",
            "iteration": iteration,
            "coverage": coverage.model_dump(),
            "usage": _usage_snapshot(),
        }

        if not coverage.should_continue:
            complete_reason = coverage.recommended_action
            logger.info(
                "[complete] reason=%s | iteration=%d", complete_reason, iteration
            )
            yield {
                "stage": "complete",
                "reason": complete_reason,
                "iteration": iteration,
                "usage": _usage_snapshot(),
            }
            break

        logger.info("[subqueries] iter=%d running", iteration)
        yield {
            "stage": "subqueries",
            "status": "running",
            "iteration": iteration,
            "usage": _usage_snapshot(),
        }
        subqs, _ = generate_subqueries(query, coverage.critical_gaps, max_n=3)
        logger.info("[subqueries] iter=%d done | count=%d", iteration, len(subqs))
        yield {
            "stage": "subqueries",
            "status": "done",
            "iteration": iteration,
            "subqueries": [sq.model_dump() for sq in subqs],
            "usage": _usage_snapshot(),
        }

        if not subqs:
            complete_reason = "no_subqueries_generated"
            logger.info(
                "[complete] reason=%s | iteration=%d", complete_reason, iteration
            )
            yield {
                "stage": "complete",
                "reason": complete_reason,
                "iteration": iteration,
                "usage": _usage_snapshot(),
            }
            break

        for sq in subqs:
            ad_hoc = Subtask(
                id=sq.id,
                description=sq.query,
                suggested_tools=sq.suggested_tools or ["web_search"],
            )
            sq_lang = sq.language_hint or language
            logger.info("  subquery %s [%s] running: %s", sq.id, sq_lang, sq.query)
            yield {
                "stage": "execute",
                "status": "subquery_running",
                "iteration": iteration,
                "subquery_id": sq.id,
                "query": sq.query,
                "language": sq_lang,
                "usage": _usage_snapshot(),
            }
            res = execute_layer(
                [ad_hoc],
                context,
                language=sq_lang,
                max_concurrency=decomp.concurrency_limit,
            )[0]
            all_results.append(res)
            if res.error:
                logger.warning("  subquery %s failed: %s", sq.id, res.error)
            else:
                logger.info(
                    "  subquery %s done | content_len=%d", sq.id, len(res.content)
                )
            yield {
                "stage": "execute",
                "status": "subquery_done",
                "iteration": iteration,
                "result": res.model_dump(),
                "usage": _usage_snapshot(),
            }

        logger.info("[synthesize] iter=%d running", iteration)
        yield {
            "stage": "synthesize",
            "status": "running",
            "iteration": iteration,
            "usage": _usage_snapshot(),
        }
        current_synthesis, _ = synthesize(query, all_results)
        logger.info(
            "[synthesize] iter=%d done | length=%d", iteration, len(current_synthesis)
        )
        yield {
            "stage": "synthesize",
            "status": "done",
            "iteration": iteration,
            "synthesis": current_synthesis,
            "usage": _usage_snapshot(),
        }

    elapsed = time.monotonic() - started_at
    final_coverage_pct = (
        final_coverage.overall_coverage * 100 if final_coverage else 0.0
    )
    final_usage = _usage_snapshot()
    logger.info(
        "=== END research | iterations=%d | elapsed=%.1fs | coverage=%.0f%% | "
        "reason=%s | total_tokens=%d | total_cost=$%.6f | calls=%d ===",
        completed_iterations,
        elapsed,
        final_coverage_pct,
        complete_reason,
        final_usage["total_tokens"],
        final_usage["total_cost_usd"],
        final_usage["total_calls"],
    )
    yield {
        "stage": "final",
        "synthesis": current_synthesis,
        "iterations": completed_iterations,
        "elapsed_seconds": elapsed,
        "final_coverage": final_coverage_pct,
        "reason": complete_reason,
        "usage": final_usage,
    }
