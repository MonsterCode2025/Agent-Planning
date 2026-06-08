import time
from datetime import datetime

import gradio as gr

from planner.orchestrator import run_research


def _fmt_decomposition(d: dict) -> str:
    header = (
        f"**复杂度**: {d['complexity_score']:.2f} "
        f"| **模式**: `{d['mode']}` "
        f"| **执行策略**: `{d['execution_strategy']}`\n\n"
    )
    rows = [
        "| ID | 描述 | Produces | Consumes | Depends on | InScope | OutOfScope |",
        "|---|---|---|---|---|---|---|",
    ]
    for st in d["subtasks"]:
        b = st.get("boundaries") or {}
        rows.append(
            f"| `{st['id']}` "
            f"| {st['description']} "
            f"| {', '.join(st.get('produces', [])) or '—'} "
            f"| {', '.join(st.get('consumes', [])) or '—'} "
            f"| {', '.join(st.get('dependencies', [])) or '—'} "
            f"| {', '.join(b.get('in_scope', [])) or '—'} "
            f"| {', '.join(b.get('out_of_scope', [])) or '—'} |"
        )
    return header + "\n".join(rows)


def _fmt_coverage(it: int, c: dict) -> str:
    pct = c["overall_coverage"] * 100
    parts = [
        f"### 迭代 {it}",
        f"- **覆盖度**: `{pct:.0f}%`",
        f"- **关键缺口**: `{len(c['critical_gaps'])}` 个",
        f"- **可选缺口**: `{len(c['optional_gaps'])}` 个",
        f"- **置信度**: `{c['confidence_level']}`",
        f"- **是否继续**: `{c['should_continue']}` (action: `{c['recommended_action']}`)",
    ]
    if c.get("guardrail_triggered"):
        parts.append(
            f"- **触发护栏**: {', '.join(f'`{g}`' for g in c['guardrail_triggered'])}"
        )
    if c["critical_gaps"]:
        parts.append("\n**关键缺口详情**:")
        for g in c["critical_gaps"]:
            parts.append(f"  - **{g['area']}** — {g['description']}")
    return "\n".join(parts)


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _status_running(stage_label: str, elapsed: float) -> str:
    return (
        f"<div style='padding:10px 14px;border-radius:8px;"
        f"background:#fffbe6;border-left:4px solid #faad14;'>"
        f"<b>状态：运行中</b> · {stage_label} · 已耗时 <code>{elapsed:.1f}s</code>"
        f"</div>"
    )


def _status_done(iterations: int, coverage: float, elapsed: float, reason: str) -> str:
    return (
        f"<div style='padding:10px 14px;border-radius:8px;"
        f"background:#f6ffed;border-left:4px solid #52c41a;'>"
        f"<b>状态：研究已完成</b> · "
        f"迭代 <code>{iterations}</code> 次 · "
        f"最终覆盖度 <code>{coverage:.0f}%</code> · "
        f"耗时 <code>{elapsed:.1f}s</code> · "
        f"终止原因 <code>{reason}</code>"
        f"</div>"
    )


def _status_error(msg: str) -> str:
    return (
        f"<div style='padding:10px 14px;border-radius:8px;"
        f"background:#fff1f0;border-left:4px solid #ff4d4f;'>"
        f"<b>状态：失败</b> · {msg}"
        f"</div>"
    )


def _status_idle() -> str:
    return (
        "<div style='padding:10px 14px;border-radius:8px;"
        "background:#f5f5f5;border-left:4px solid #bfbfbf;'>"
        "<b>状态：空闲</b> · 等待开始"
        "</div>"
    )


_STAGE_LABEL = {
    ("decompose", "running"): "正在分解任务",
    ("decompose", "done"): "任务分解完成",
    ("execute", "plan"): "已生成拓扑执行计划",
    ("execute", "layer_running"): "正在执行子任务层",
    ("execute", "layer_done"): "子任务层完成",
    ("execute", "subquery_running"): "正在执行补充查询",
    ("execute", "subquery_done"): "补充查询完成",
    ("synthesize", "running"): "正在综合结果",
    ("synthesize", "done"): "综合完成",
    ("evaluate", "running"): "正在评估覆盖度",
    ("evaluate", "done"): "覆盖度评估完成",
    ("subqueries", "running"): "正在生成补充查询",
    ("subqueries", "done"): "补充查询生成完成",
}


def research(query: str, max_iter: int, language: str):
    if not query.strip():
        gr.Warning("请先输入研究请求")
        yield (
            _status_error("研究请求为空"),
            "_请输入研究请求_",
            "",
            "",
            "_未启动_",
        )
        return

    decomp_md = "_等待分解..._"
    iter_md = ""
    final_md = "_等待综合..._"
    log_lines: list[str] = []
    started_at = time.monotonic()

    def elapsed() -> float:
        return time.monotonic() - started_at

    def push_log(stage: str, detail: str = "") -> str:
        log_lines.append(f"`{_ts()}` **{stage}** {detail}")
        return "\n\n".join(log_lines[-80:])

    status = _status_running("启动中", 0.0)
    log = push_log("start", f"query={query!r}, max_iter={max_iter}, lang={language}")
    yield status, decomp_md, iter_md, final_md, log

    try:
        for event in run_research(query, max_iterations=int(max_iter), language=language):
            stage = event.get("stage", "")
            ev_status = event.get("status", "")

            label = _STAGE_LABEL.get((stage, ev_status), f"{stage}/{ev_status}")
            status = _status_running(label, elapsed())

            if stage == "decompose" and ev_status == "done":
                decomp_md = _fmt_decomposition(event["decomposition"])
                log = push_log(
                    "decompose",
                    f"→ {len(event['decomposition']['subtasks'])} 个子任务",
                )

            elif stage == "execute" and ev_status == "plan":
                layers = event["layers"]
                log = push_log("topo", f"→ {len(layers)} 层: {layers}")

            elif stage == "execute" and ev_status == "layer_running":
                log = push_log(
                    f"layer {event['layer_index']}", f"running {event['subtasks']}"
                )

            elif stage == "execute" and ev_status == "layer_done":
                errs = sum(1 for r in event["results"] if r.get("error"))
                log = push_log(
                    f"layer {event['layer_index']}",
                    f"done ({len(event['results'])} 结果, {errs} 错误)",
                )

            elif stage == "execute" and ev_status == "subquery_running":
                log = push_log(
                    f"iter {event['iteration']} sub-query",
                    f"`{event['subquery_id']}` [{event['language']}] {event['query']}",
                )

            elif stage == "execute" and ev_status == "subquery_done":
                r = event["result"]
                detail = (
                    f"error: {r['error']}"
                    if r.get("error")
                    else f"ok ({len(r['content'])} 字)"
                )
                log = push_log(f"iter {event['iteration']} sub-query", detail)

            elif stage == "synthesize" and ev_status == "running":
                log = push_log("synthesize", f"iteration={event['iteration']}")

            elif stage == "synthesize" and ev_status == "done":
                final_md = event["synthesis"]
                log = push_log(
                    "synthesize",
                    f"done (iter {event['iteration']}, {len(event['synthesis'])} 字)",
                )

            elif stage == "evaluate" and ev_status == "done":
                iter_md += "\n\n" + _fmt_coverage(event["iteration"], event["coverage"])
                cov = event["coverage"]["overall_coverage"] * 100
                log = push_log(
                    f"evaluate iter {event['iteration']}",
                    f"coverage={cov:.0f}%, continue={event['coverage']['should_continue']}",
                )

            elif stage == "subqueries" and ev_status == "done":
                log = push_log(
                    f"subqueries iter {event['iteration']}",
                    f"→ {len(event['subqueries'])} 个",
                )

            elif stage == "complete":
                log = push_log("complete", f"reason={event['reason']}")

            elif stage == "final":
                final_md = event["synthesis"]
                status = _status_done(
                    iterations=event.get("iterations", 0),
                    coverage=event.get("final_coverage", 0.0),
                    elapsed=event.get("elapsed_seconds", elapsed()),
                    reason=event.get("reason", ""),
                )
                log = push_log(
                    "final",
                    f"完成 | 迭代 {event.get('iterations',0)} 次 | "
                    f"覆盖度 {event.get('final_coverage',0):.0f}% | "
                    f"耗时 {event.get('elapsed_seconds', elapsed()):.1f}s",
                )
                gr.Info(
                    f"研究已完成（{event.get('iterations',0)} 轮迭代，"
                    f"覆盖度 {event.get('final_coverage',0):.0f}%）"
                )

            else:
                log = push_log(stage, ev_status)

            yield status, decomp_md, iter_md, final_md, log
    except Exception as e:
        gr.Warning(f"研究过程出错：{e}")
        status = _status_error(str(e))
        log = push_log("error", str(e))
        yield status, decomp_md, iter_md, final_md, log


_DESC = """### 演示《AI Agent 架构》第 10 章 Planning 模式

**Pipeline**: 任务分解 → 拓扑排序 DAG 执行（边界声明防重叠）→ 综合 → 覆盖度评估（**4 条确定性护栏**）→ 补充查询（多语言感知）→ 迭代

**护栏**:
1. 首轮 + 低覆盖度 → 强制继续
2. 存在 critical 缺口 + 还有预算 → 强制继续
3. 达最大迭代 → 强制停止
4. 综合结果太短但 LLM 报告高覆盖度 → 置信度降级

> 详细日志同时写入控制台和 `logs/planner.log`。
"""


with gr.Blocks(title="Planning Agent — 第 10 章演示") as demo:
    gr.Markdown("# Planning 模式研究 Agent")
    gr.Markdown(_DESC)

    status_view = gr.HTML(value=_status_idle())

    with gr.Row():
        with gr.Column(scale=3):
            query_box = gr.Textbox(
                label="研究请求",
                value="研究 Anthropic 公司，给出 2000 字的商业与技术分析",
                lines=3,
            )
        with gr.Column(scale=1):
            max_iter = gr.Slider(1, 5, value=2, step=1, label="最大迭代次数")
            language = gr.Dropdown(
                choices=["en", "zh", "ja", "ko"],
                value="en",
                label="主语言（搜索 hl）",
            )
            run_btn = gr.Button("开始研究", variant="primary", size="lg")

    with gr.Tabs():
        with gr.Tab("① 任务分解"):
            decomp_view = gr.Markdown("_点击开始研究后显示_")
        with gr.Tab("② 覆盖度迭代"):
            iter_view = gr.Markdown("_点击开始研究后显示_")
        with gr.Tab("③ 最终报告"):
            final_view = gr.Markdown("_点击开始研究后显示_")
        with gr.Tab("④ 事件日志"):
            log_view = gr.Markdown("_点击开始研究后显示_")

    run_btn.click(
        research,
        inputs=[query_box, max_iter, language],
        outputs=[status_view, decomp_view, iter_view, final_view, log_view],
    )


if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        theme=gr.themes.Soft(),
    )
