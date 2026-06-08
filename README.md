# Planning 模式研究 Agent

---

## 目录

- [核心知识点](#核心知识点)
- [项目结构](#项目结构)
- [安装与运行](#安装与运行)
- [当 query 输入时，系统执行什么](#当-query-输入时系统执行什么)
- [4 条确定性护栏详解](#4-条确定性护栏详解)
- [Shannon plan_schema_v2 借鉴字段](#shannon-plan_schema_v2-借鉴字段)
- [Token 用量与成本统计](#token-用量与成本统计)
- [UI 四个 Tab 的含义](#ui-四个-tab-的含义)
- [日志说明](#日志说明)
- [配置项](#配置项)
- [已知限制](#已知限制)

---

## 核心知识点

| 文章要点 | 代码位置 |
|---|---|
| `Subtask` 含 `Produces` / `Consumes` / `Boundaries` / `estimated_tokens` | [planner/types.py:16](planner/types.py:16) |
| `DecompositionResult` 含 `complexity_score` / `execution_strategy` 等 | [planner/types.py:27](planner/types.py:27) |
| **Shannon 借鉴**：`concurrency_limit` / `cognitive_strategy` / `confidence` / `fallback_strategy` / `agent_types` / `token_estimates` | [planner/types.py:33](planner/types.py:33) |
| 任务分解 + `mode`（quick / standard / deep）粒度切换 | [planner/decompose.py:65](planner/decompose.py:65) `decompose_task` |
| 拓扑排序（A → [B, C 并行] → D） | [planner/execute.py:9](planner/execute.py:9) `topological_layers` |
| 范围边界注入 prompt（防止子任务内容重叠） | [planner/execute.py:34](planner/execute.py:34) `_SUBTASK_TEMPLATE` |
| 并行执行 + `max_concurrency` 来自 `concurrency_limit` | [planner/execute.py:123](planner/execute.py:123) `execute_layer` |
| 覆盖度评估 + **护栏 1** 首轮低覆盖度强制继续 | [planner/evaluate.py:54](planner/evaluate.py:54) |
| **护栏 2** 存在 critical 缺口 + 还有预算强制继续 | [planner/evaluate.py:60](planner/evaluate.py:60) |
| **护栏 3** 达最大迭代强制停止 | [planner/evaluate.py:66](planner/evaluate.py:66) |
| **护栏 4** 综合结果太短但报告高覆盖度则降级置信度 | [planner/evaluate.py:72](planner/evaluate.py:72) |
| 补充查询 + 多语言感知（`language_hint`） | [planner/subqueries.py](planner/subqueries.py) |
| **Token / USD 用量追踪**：线程安全累加 + 按 stage 子账 | [planner/llm.py:32](planner/llm.py:32) `UsageTracker` |
| 完整 Research 循环（流式 yield 事件，每事件附 `usage`） | [planner/orchestrator.py:40](planner/orchestrator.py:40) `run_research` |

---

## 项目结构

```
planning/
├── .env                          # LLM_BASE_URL / LLM_MODEL_ID / LLM_API_KEY / SERPAPI_API_KEY
│                                 # + 可选：LLM_*_USD_PER_M 价格覆盖
├── requirements.txt
├── app.py                        # Gradio UI（mode 选择 + 状态条 + token/cost chip + 完成通知）
├── logs/planner.log              # 运行后自动生成（滚动 5MB × 3）
└── planner/
    ├── __init__.py               # load_dotenv()
    ├── types.py                  # Pydantic 数据模型 + UsageInfo / ChatResult (frozen dataclass)
    ├── llm.py                    # DeepSeek (OpenAI 兼容) 客户端 + UsageTracker（按 stage 计费）
    ├── tools.py                  # web_search (SerpAPI) + web_fetch
    ├── decompose.py              # 任务分解（quick / standard / deep 三档粒度）
    ├── execute.py                # 拓扑排序 + 分层并行执行（max_concurrency 来自 concurrency_limit）
    ├── evaluate.py               # 覆盖度评估 + 4 条护栏
    ├── subqueries.py             # 补充查询生成（多语言感知）
    ├── synthesize.py             # 子任务结果综合
    ├── orchestrator.py           # 完整 Research 循环（流式 yield，每事件附 usage）
    └── logger.py                 # 控制台 + 滚动文件双输出
```

---

## 安装与运行

> 前置要求：**Python ≥ 3.10**（推荐 3.11）。在终端运行 `python --version` 确认。

### 步骤 1：创建 `.venv` 虚拟环境

进入项目根目录后执行：

**PowerShell / cmd（推荐）**
```powershell
python -m venv .venv
```

**如果系统装了多个 Python 版本**，用 `py` launcher 指定：
```powershell
py -3.11 -m venv .venv
```

成功后会在项目根目录生成 `.venv/` 文件夹。

### 步骤 2：激活虚拟环境

**PowerShell**
```powershell
.\.venv\Scripts\Activate.ps1
```

**cmd**
```cmd
.\.venv\Scripts\activate.bat
```

**激活成功的标志**：命令提示符前出现 `(.venv)` 前缀，例如：
```
(.venv) D:\code\agents_project\planning>
```

**验证 Python 指向了 venv 内部**：
```powershell
where.exe python
# 应输出：D:\code\agents_project\planning\.venv\Scripts\python.exe
```

**常见报错**：PowerShell 执行 `Activate.ps1` 提示"无法加载，因为在此系统上禁止运行脚本"。一次性放行当前会话：
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```
或者直接用 cmd 风格的 `activate.bat`，它不受执行策略限制。

### 步骤 3：安装依赖

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

依赖包：

| 包 | 用途 |
|---|---|
| `openai` | DeepSeek 客户端（OpenAI 兼容） |
| `python-dotenv` | 加载 `.env` |
| `pydantic` | 数据模型验证 |
| `requests` | SerpAPI 与 web_fetch |
| `gradio` | 前端 UI |

总下载量约 200 MB（主要是 gradio + 其依赖）。

### 步骤 4：配置 `.env`

项目根目录创建 `.env`（如已存在则跳过），内容如下：

```env
LLM_BASE_URL=url
LLM_MODEL_ID=model_name
LLM_API_KEY="sk-你的-deepseek-key"
LLM_TIMEOUT=60

SERPAPI_API_KEY="你的-serpapi-key"

# 可选：LLM 价格覆盖（USD per 1M tokens；默认按 DeepSeek-chat 定价）
# LLM_INPUT_USD_PER_M=0.27
# LLM_CACHED_INPUT_USD_PER_M=0.07
# LLM_OUTPUT_USD_PER_M=1.10
```

- DeepSeek 密钥申请：<https://platform.deepseek.com/>
- SerpAPI 密钥申请：<https://serpapi.com/>（每月有免费额度）

> `.env` 不应提交到 git。建议在仓库根加一行 `.gitignore`：`.env`。

### 步骤 5：启动 `app.py`

```powershell
python app.py
```

控制台会输出类似：
```
* Running on local URL:  http://127.0.0.1:7860
```

浏览器打开 [http://127.0.0.1:7860](http://127.0.0.1:7860) 即可看到 UI。输入研究请求 → 选择 **分解粒度档位（mode）** / 最大迭代次数 / 主语言 → 点击「开始研究」→ 观察状态条（含累计 token / USD / calls）+ 4 个 Tab 实时更新。

> **mode 三档**：`quick`（2-3 子任务，最省 token）/ `standard`（3-7 子任务，默认）/ `deep`（5-10 子任务，多维度细化）。该参数同时影响子任务个数与 system prompt 中的粒度提示。

**控制台与 `logs/planner.log` 会同时输出完整执行日志**（见 [日志说明](#日志说明)）。

### 步骤 6：退出虚拟环境

工作结束后：
```powershell
deactivate
```
提示符前的 `(.venv)` 会消失。

### 完整流程一次性复制

如果你想一次性走完，复制下面这段（PowerShell）：

```powershell
cd D:\code\agents_project\planning
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
# 此时请确认 .env 已配置好
python app.py
```

### 常见问题

| 现象 | 解决 |
|---|---|
| `Activate.ps1 cannot be loaded ...` | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` 后重试，或改用 `activate.bat` |
| `pip install` 速度很慢 | 用国内镜像：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `KeyError: 'LLM_API_KEY'` | `.env` 未在项目根目录，或编辑后未保存 |
| 端口 7860 被占用 | 改 [app.py:191](app.py:191) 的 `server_port` 为其他端口 |
| Gradio 6.0 警告/报错 | 已在 `requirements.txt` 中固定 `>=4.36`；若手动升级到 6.x 请保留 `theme` 在 `launch()` 中传入 |

---

## 当 query 输入时，系统执行什么

以默认查询 **`研究 Anthropic 公司，给出 2000 字的商业与技术分析`** 为例，端到端流程如下。

### 总览

```
用户输入 query
       │
       ▼
┌────────────────────────────────────────────────────────────────┐
│ 阶段 1：任务分解   decompose_task(query)                       │
│   - LLM 输出 DecompositionResult (subtasks, strategy, ...)    │
│   - 子任务声明 Produces / Consumes / Boundaries               │
└────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────┐
│ 阶段 2：拓扑分层执行   topological_layers(subtasks)            │
│   - 按依赖关系分层；每层内并行（ThreadPoolExecutor）          │
│   - 每个子任务：web_search → web_fetch → LLM 生成             │
│   - produces 字段写入 context 供下游 consume                  │
└────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────┐
│ 阶段 3：初始综合   synthesize(query, results)                 │
│   - 跨子任务做整合，生成首版报告                              │
└────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────┐
│ 阶段 4：迭代评估循环（最多 max_iterations 轮）                │
│                                                                │
│   ┌──> evaluate_coverage()                                     │
│   │      └─ LLM 评估 + 4 条确定性护栏修正                     │
│   │                                                            │
│   │    should_continue == False ? ──Yes──> break              │
│   │            │ No                                            │
│   │            ▼                                               │
│   │    generate_subqueries(critical_gaps)                      │
│   │            │                                               │
│   │            ▼                                               │
│   │    把每个补充查询作为临时 Subtask 执行                    │
│   │            │                                               │
│   │            ▼                                               │
│   └─── synthesize(query, all_results) （重新综合）            │
└────────────────────────────────────────────────────────────────┘
       │
       ▼
┌────────────────────────────────────────────────────────────────┐
│ final 事件                                                     │
│   - UI 顶部状态条变绿，gr.Info() 弹通知                       │
│   - 日志写 === END research === 横幅                          │
└────────────────────────────────────────────────────────────────┘
```

### 阶段 1：任务分解

**入口**：[planner/decompose.py:65](planner/decompose.py:65) `decompose_task(query, available_tools, mode="standard")`

**做了什么**：
1. 把 query 和 `available_tools=["web_search", "web_fetch"]` 拼成 user message
2. 调用 [planner/llm.py:108](planner/llm.py:108) `chat_json()`，传入 `response_format={"type": "json_object"}` 强制 JSON 输出
3. LLM 的 system prompt（[planner/decompose.py:11](planner/decompose.py:11) `_decompose_system(mode)`）要求：
   - 子任务粒度按 `mode` 切换：`quick` 2-3 / `standard` 3-7 / `deep` 5-10
   - 每个子任务必须声明 `produces` / `consumes` / `dependencies` / `estimated_tokens`
   - 用 `boundaries.in_scope` / `out_of_scope` 防止子任务内容重叠
   - 给出 `complexity_score` / `mode` / `execution_strategy`
   - **Shannon 借鉴字段**：`concurrency_limit` / `cognitive_strategy` / `confidence` / `fallback_strategy` / `agent_types` / `token_estimates` / `total_estimated_tokens`
4. 用 Pydantic `DecompositionResult.model_validate(data)` 解析

**典型 LLM 输出**（示意）：
```json
{
  "mode": "standard",
  "complexity_score": 0.65,
  "execution_strategy": "dag",
  "concurrency_limit": 3,
  "cognitive_strategy": "plan_execute",
  "confidence": 0.82,
  "fallback_strategy": "react",
  "agent_types": ["researcher", "analyst"],
  "total_estimated_tokens": 12800,
  "token_estimates": {"subtask-1": 2400, "subtask-2": 3200},
  "subtasks": [
    {
      "id": "subtask-1",
      "description": "收集 Anthropic 公司基本信息（创始人、成立时间、融资）",
      "dependencies": [],
      "produces": ["company_basics"],
      "consumes": [],
      "suggested_tools": ["web_search", "web_fetch"],
      "boundaries": {
        "in_scope": ["founders", "founding_date", "funding rounds"],
        "out_of_scope": ["products", "competitors"]
      }
    },
    {
      "id": "subtask-2",
      "description": "分析 Claude 产品矩阵",
      "dependencies": ["subtask-1"],
      "produces": ["products"],
      "consumes": ["company_basics"],
      "suggested_tools": ["web_search", "web_fetch"],
      "boundaries": {
        "in_scope": ["Claude API", "Claude.ai", "model versions"],
        "out_of_scope": ["funding", "competitors"]
      }
    }
  ]
}
```

**日志**（含用量与 Shannon 字段）：
```
[INFO] planner.orchestrator: [decompose] running mode=standard
[INFO] planner.orchestrator: [decompose] done | subtasks=5 | strategy=dag | complexity=0.65 | concurrency_limit=3 | cognitive=plan_execute (conf=0.82, fb=react) | est_tokens=12800 | usage_tokens=1240 cost=$0.000845
```

### 阶段 2：拓扑分层执行

**入口**：[planner/execute.py:9](planner/execute.py:9) `topological_layers(subtasks)` + [planner/execute.py:123](planner/execute.py:123) `execute_layer()`

**做了什么**：

1. **拓扑排序**：把子任务按依赖关系分层。例如对依赖图：
   ```
   subtask-1 (无依赖)         ─┐
   subtask-2 (依赖 1)         ─┤
   subtask-3 (依赖 1)         ─┤
   subtask-4 (依赖 2,3)
   subtask-5 (依赖 1)
   ```
   分层结果：
   ```
   layer 0: [subtask-1]
   layer 1: [subtask-2, subtask-3, subtask-5]   ← 并行
   layer 2: [subtask-4]
   ```
   循环依赖会抛 `ValueError("Cyclic dependency detected ...")`。

2. **逐层执行**，每层用 `ThreadPoolExecutor(max_workers=min(concurrency_limit, len(layer)))` 并行（`concurrency_limit` 由分解阶段给出，默认 4）：
   - 对每个 Subtask 调用 `execute_subtask(subtask, context, language)`
   - `context` 累积：上一层执行完后，`produces` 字段对应的内容写入 `context`，下一层通过 `consumes` 字段读取

3. **每个子任务内部**：
   - 如果 `suggested_tools` 含 `web_search` → 调用 SerpAPI 搜 4 条结果
   - 如果含 `web_fetch` → 抓取前 2 条 URL 的正文（正则去标签，前 1500 字）
   - 把 **范围边界**、**上游 context**、**搜索结果**、**抓取片段** 全部拼进 prompt（见 [planner/execute.py:34](planner/execute.py:34) `_SUBTASK_TEMPLATE`）
   - 调用 LLM 生成本子任务的结构化输出（`stage="subtask"` 被记入用量子账）
   - 单个子任务失败不阻塞整体：捕获异常，返回带 `error` 字段的 `SubtaskResult`

**日志**：
```
[INFO] planner.orchestrator: [execute] topological plan | layers=[['subtask-1'],['subtask-2','subtask-3','subtask-5'],['subtask-4']]
[INFO] planner.orchestrator: [execute] layer 0/2 running | subtasks=['subtask-1']
[INFO] planner.orchestrator: [execute] layer 0 done | results=1 | errors=0
[INFO] planner.orchestrator: [execute] layer 1/2 running | subtasks=['subtask-2','subtask-3','subtask-5']
[INFO] planner.orchestrator: [execute] layer 1 done | results=3 | errors=0
```

### 阶段 3：初始综合

**入口**：[planner/synthesize.py:21](planner/synthesize.py:21) `synthesize(query, results)`

**做了什么**：
- 跳过 `error` 字段非空的子任务结果
- 把所有有效结果拼成 markdown，附原始 query
- 通过 LLM 完成"综合分析（不是简单拼接）"：发现跨子任务洞察、矛盾、趋势
- 关键结论用 **粗体** 突出，引用来源保留 `[来源 N]`

**日志**：
```
[INFO] planner.orchestrator: [synthesize] iter=0 running
[INFO] planner.orchestrator: [synthesize] iter=0 done | length=2150
```

### 阶段 4：迭代评估循环

每轮迭代执行 4 个子步骤：**评估 → (终止判断) → 补充查询 → 执行补充 → 重新综合**。

#### 4.1 覆盖度评估

**入口**：[planner/evaluate.py:32](planner/evaluate.py:32) `evaluate_coverage(query, synthesis, iteration, max_iterations)`

**做了什么**：
1. LLM 判断 `overall_coverage` (0-1)、`critical_gaps` / `optional_gaps`、`should_continue`、`confidence_level`
2. **应用 4 条确定性护栏**（见下节）覆盖 LLM 输出
3. 把触发的护栏名称写入 `guardrail_triggered` 字段供 UI/日志展示

**典型输出**：
```json
{
  "overall_coverage": 0.62,
  "critical_gaps": [
    {"area": "竞争对手分析", "description": "缺少与 OpenAI / Google DeepMind 的对比", "severity": "critical"},
    {"area": "财务数据", "description": "未涵盖最新一轮融资规模", "severity": "critical"}
  ],
  "should_continue": true,
  "recommended_action": "continue",
  "confidence_level": "high",
  "guardrail_triggered": ["rule2_critical_gaps_remaining_budget"]
}
```

#### 4.2 终止判断

如果 `coverage.should_continue == False`：
- 立刻 yield `complete` 事件
- 跳出迭代循环，进入 final
- 终止原因（`reason`）有四种：
  - `complete` — 质量已达标（覆盖度 ≥ 85% 且无 critical 缺口）
  - `complete` — 护栏 3 触发（达最大迭代）
  - `no_subqueries_generated` — LLM 没生成补充查询
  - `max_iterations_loop_end` — 循环自然结束（理论上不应到达）

#### 4.3 补充查询生成

**入口**：[planner/subqueries.py:30](planner/subqueries.py:30) `generate_subqueries(query, critical_gaps, max_n=3)`

**做了什么**：
- 只针对 `critical_gaps` 生成（最多 3 个）
- system prompt 显式要求：
  - 优先级排序、避免与历史查询重复
  - **多语言感知**：研究亚洲公司时使用本地语言（`language_hint: "zh"|"ja"|"ko"`）
  - 备选策略：标准搜索失败时建议 `web_fetch` 直接抓公司域名 / LinkedIn / Crunchbase

#### 4.4 执行补充查询

每个补充查询包装成临时 `Subtask` 调用 `execute_layer([ad_hoc], context, language=sq_lang)`。注意 `sq_lang` 优先用 `language_hint`，否则回退到全局 `language` 参数。

#### 4.5 重新综合

把**所有**（原始 + 累积的补充）结果重新交给 `synthesize()`，得到本轮新的 `current_synthesis`。

**循环示例日志**：
```
[INFO] planner.orchestrator: [evaluate] iter=1 done | coverage=62% | critical_gaps=2 | continue=True | guardrails=['rule2_critical_gaps_remaining_budget']
[INFO] planner.orchestrator: [subqueries] iter=1 done | count=2
[INFO] planner.orchestrator:   subquery sq-1 [en] running: Anthropic vs OpenAI competitive landscape 2025
[INFO] planner.orchestrator:   subquery sq-1 done | content_len=1820
[INFO] planner.orchestrator: [synthesize] iter=1 running
[INFO] planner.orchestrator: [synthesize] iter=1 done | length=2540
[INFO] planner.orchestrator: [evaluate] iter=2 done | coverage=88% | critical_gaps=0 | continue=False | guardrails=['rule3_max_iterations','quality_threshold_met']
[INFO] planner.orchestrator: [complete] reason=complete | iteration=2
[INFO] planner.orchestrator: === END research | iterations=2 | elapsed=78.4s | coverage=88% | reason=complete ===
```

### final 事件 → UI 反馈

`orchestrator.run_research()` 最后 yield：
```python
{
  "stage": "final",
  "synthesis": "...",
  "iterations": 2,
  "elapsed_seconds": 78.4,
  "final_coverage": 88.0,
  "reason": "complete"
}
```

`app.py` 接收到该事件：
1. 顶部状态条切换为**绿色**："研究已完成 · 迭代 2 次 · 最终覆盖度 88% · 耗时 78.4s · 终止原因 complete"
2. 触发 `gr.Info("研究已完成（2 轮迭代，覆盖度 88%）")` 右上角通知
3. "最终报告" Tab 显示综合结果

---

## 4 条确定性护栏详解

文章作者的核心观点："LLM 的判断不稳定，必须用规则覆盖。"

实现位置：[planner/evaluate.py:32](planner/evaluate.py:32) `evaluate_coverage()`

| # | 条件 | 行为 | 目的 |
|---|---|---|---|
| 1 | `iteration == 1 and overall_coverage < 0.5` | 强制 `should_continue=True` | 防止首轮就过早乐观停止 |
| 2 | `len(critical_gaps) > 0 and iteration < max_iterations` | 强制 `should_continue=True` | 还有预算就必须填补关键缺口 |
| 3 | `iteration >= max_iterations` | 强制 `should_continue=False` | 防止无限迭代烧 token |
| 4 | `len(synthesis) < 500 and overall_coverage > 0.7` | `confidence_level="low"` | 综合结果太短但 LLM 自信，标记不可信 |

额外加了一条质量达标提前停止：覆盖度 ≥ 85% 且无 critical 缺口 → 即使还有预算也停止（节省 token）。

每条护栏触发时把名字加入 `guardrail_triggered` 列表，UI 的"② 覆盖度迭代" Tab 会显示出来便于排查。

---

## Shannon plan_schema_v2 借鉴字段

`DecompositionResult` 在原始字段（`mode` / `complexity_score` / `execution_strategy` / `subtasks`）之外，借鉴 Shannon plan_schema_v2 增加了一组"执行规划"元数据，使 orchestrator 能基于 LLM 的判断动态调度，而不是写死并发数与策略。

实现位置：[planner/types.py:27](planner/types.py:27) `DecompositionResult` + [planner/decompose.py:11](planner/decompose.py:11) system prompt。

| 字段 | 类型 | 默认 | 作用 |
|---|---|---|---|
| `concurrency_limit` | int | 4 | 当前 DAG 推荐的最大并发数；传给 `execute_layer(max_concurrency=...)` 控制 `ThreadPoolExecutor` |
| `cognitive_strategy` | `plan_execute` / `react` / `cot` / `tot` / `auto` | `plan_execute` | 当前 query 的推荐推理模式（目前仅展示，尚未驱动分支） |
| `confidence` | float | 0.0 | LLM 对策略选择的置信度，UI 直接展示 |
| `fallback_strategy` | 同 `cognitive_strategy` 枚举 | `react` | 主策略失败时的回退候选 |
| `agent_types` | list[str] | `[]` | 每个子任务建议的 agent 角色（如 `["researcher", "analyst"]`） |
| `estimated_tokens`（Subtask） | int | 0 | LLM 预估的单个子任务总 token，UI 表格展示 |
| `token_estimates` | dict[str, int] | `{}` | 子任务 id → 预估 token 的映射 |
| `total_estimated_tokens` | int | 0 | 全部子任务 token 预估之和；用作 "**预估 token**" 在 UI 头部展示 |

UI 在「① 任务分解」Tab 顶部一行渲染这些字段，子任务表格新增 **Est.tokens** 列。

---

## Token 用量与成本统计

`planner/llm.py` 内置 `UsageTracker`，对每一次 LLM 调用记录 `prompt_tokens` / `completion_tokens` / `cached_tokens` / `cost_usd` / `calls`，并维护"总账 + stage 子账"两份：

- **总账**：累计所有 stage 的用量
- **stage 子账**：按调用方传入的 `stage` 字段分桶，目前的 stage 取值包括：`decompose` / `subtask` / `evaluate` / `subqueries` / `synthesize`

| 关键点 | 代码位置 |
|---|---|
| 线程安全累加器（带 lock） | [planner/llm.py:32](planner/llm.py:32) `UsageTracker` |
| `prompt_cache_hit_tokens` / `prompt_tokens_details.cached_tokens` 兼容 | [planner/llm.py:63](planner/llm.py:63) `_extract_usage` |
| 价格计算（fresh vs cached input 分别计费） | [planner/llm.py:23](planner/llm.py:23) `_calc_cost` |
| 每个 yield 事件附带 `usage` 快照 | [planner/orchestrator.py:20](planner/orchestrator.py:20) `_usage_snapshot` |
| `run_research` 起点先 `tracker.reset()` | [planner/orchestrator.py:51](planner/orchestrator.py:51) |

**价格默认值**（DeepSeek-chat 标准价，可用 env 覆盖）：

| 环境变量 | 默认 (USD per 1M tokens) |
|---|---|
| `LLM_INPUT_USD_PER_M` | `0.27` |
| `LLM_CACHED_INPUT_USD_PER_M` | `0.07` |
| `LLM_OUTPUT_USD_PER_M` | `1.10` |

**UI 呈现**：
- 状态条右侧实时显示 `X tokens · $Y · N calls`，完成态额外显示 `cache K`
- 「③ 最终报告」末尾追加一张 **LLM 用量分布（by stage）** 表格，列出各 stage 的 tokens / cost / calls
- 完成通知带成本：`研究已完成（X 轮迭代，覆盖度 Y%，花费 $Z）`

---

## UI 四个 Tab 的含义

| Tab | 内容 | 数据来源 |
|---|---|---|
| ① 任务分解 | 顶部摘要（复杂度 / mode / 策略 / **并发上限** / **预估 token** / **认知策略** / **agent 类型**）+ 子任务表格（ID / 描述 / Produces / Consumes / 依赖 / **Est.tokens** / InScope / OutOfScope） | `decompose` 阶段的 `decomposition` 字段 |
| ② 覆盖度迭代 | 每轮迭代的覆盖度、缺口、置信度、**触发了哪条护栏** | `evaluate` 阶段的 `coverage` 字段 |
| ③ 最终报告 | LLM 综合后的 markdown 报告 + **LLM 用量分布表（by stage）** | `synthesize` / `final` 阶段的 `synthesis` + `usage` |
| ④ 事件日志 | 带时间戳的 UI 内审计日志（最近 80 行） | 每个 yield 事件的紧凑摘要 |

顶部还有一个**状态条**（`gr.HTML`），右侧带 `tokens · $cost · calls` 实时标签：
- 灰 = 空闲
- 黄 = 运行中（实时阶段名 + 耗时 + 累计用量）
- 绿 = 已完成（迭代次数 / 覆盖度 / 耗时 / 终止原因 / 用量 + cache 命中）
- 红 = 失败（错误信息）

---

## 日志说明

**双输出**（见 [planner/logger.py](planner/logger.py)）：

1. **控制台**：实时人眼可读
2. **文件** `logs/planner.log`：滚动 5MB × 3 个备份，用于排查与审计

**日志级别**：
- `INFO`（默认）：阶段开始/结束、子任务统计、覆盖度、护栏触发、迭代终止原因
- `WARNING`：子任务执行失败、补充查询失败
- `DEBUG`：每个子任务的 deps/produces/consumes

**调成 DEBUG** 看更细：
```powershell
$env:PLANNER_LOG_LEVEL = "DEBUG"
python app.py
```

**改日志目录**：
```powershell
$env:PLANNER_LOG_DIR = "D:\my-logs"
python app.py
```

---

## 配置项

`.env`：

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` | OpenAI 兼容端点（默认 DeepSeek `https://api.deepseek.com/v1`） |
| `LLM_MODEL_ID` | 模型 ID（默认 `deepseek-chat`） |
| `LLM_API_KEY` | LLM 密钥 |
| `LLM_TIMEOUT` | LLM 请求超时秒数（默认 60） |
| `SERPAPI_API_KEY` | SerpAPI 密钥（用于 `web_search`） |
| `LLM_INPUT_USD_PER_M` | 输入 token 单价（USD/1M），默认 `0.27` |
| `LLM_CACHED_INPUT_USD_PER_M` | 缓存命中输入 token 单价，默认 `0.07` |
| `LLM_OUTPUT_USD_PER_M` | 输出 token 单价，默认 `1.10` |

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `PLANNER_LOG_LEVEL` | `INFO` | 日志级别 |
| `PLANNER_LOG_DIR` | `logs` | 日志输出目录 |

代码内可调常量：

| 常量 | 位置 | 默认 | 说明 |
|---|---|---|---|
| `MAX_ITERATIONS_DEFAULT` | [planner/orchestrator.py:14](planner/orchestrator.py:14) | 3 | 默认最大迭代数（UI 滑杆默认 2） |
| `_COVERAGE_THRESHOLD` | [planner/evaluate.py:26](planner/evaluate.py:26) | 0.85 | 质量达标阈值 |
| `_LOW_CONFIDENCE_LEN` | [planner/evaluate.py:27](planner/evaluate.py:27) | 500 | 护栏 4 字数阈值 |
| `max_workers` | [planner/execute.py:137](planner/execute.py:137) | `min(concurrency_limit, len(layer))` | 并行执行并发上限（`concurrency_limit` 来自分解结果） |

---

## 已知限制

1. **`web_fetch` 只做正则去标签**，遇到复杂 SPA / JS 渲染的页面会拿到空内容。生产场景建议换 `trafilatura` / `readability-lxml`，或用 Playwright 抓取。
2. **没有缓存**：同一 query 重跑会重新付费调用 LLM/SerpAPI。生产场景建议加结果级缓存（按 `query + subtask_id` 做 key）。
3. **没有持久化**：每次重启 UI，研究记录丢失。
4. **重试机制简单**：单个子任务失败仅记录 `error`，不会自动重试。
5. **Token 预算护栏未实现**：虽然已可实时统计 token / USD（见 [Token 用量与成本统计](#token-用量与成本统计)），但终止仍由 `max_iterations` 与覆盖度护栏控制，没有按预算硬性截断。`total_estimated_tokens` 仅用于展示。
6. **`cognitive_strategy` / `fallback_strategy` 仅展示**：LLM 输出的推荐推理模式与回退策略目前只在 UI 显示，尚未在 orchestrator 中分支驱动不同执行路径。
7. **价格默认按 DeepSeek-chat**：换用其他模型时需手动通过 `LLM_*_USD_PER_M` env 覆盖，否则成本数值不准确。

