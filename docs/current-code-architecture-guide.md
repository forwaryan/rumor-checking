# 当前代码结构与项目架构说明

更新时间：2026-07-23（Asia/Shanghai）

这份文档只讲三件事：

1. 现在这套代码是怎么分层的。
2. 现在这个项目的主架构是怎么跑的。
3. 用一个真实能在当前代码里跑通的例子，把整条链路讲清楚。

---

## 1. 一句话先讲清楚

`rumor-checking` 现在是一套 **Next.js 单页前端 + FastAPI 后端 + 共享 Report 契约 + 可流式观测的分析流水线**。

它不是“前端调一个黑盒模型然后等答案”，而是：

- 前端负责输入、实时过程展示、结构化结果展示。
- 后端负责把输入拆成标准化事件、检索、消歧、判定、时间线和最终报告。
- `contracts/` 负责把前后端都要认的字段结构固定下来。
- `evals/` 和 `mock` 检索负责给这条链路提供稳定、可回归的样例。

---

## 2. 先看当前运行路径

项目现在存在三层可叠加的运行选择：

| 维度 | 稳定基线（默认） | 增强路径 | 关键开关 |
| --- | --- | --- | --- |
| 分析 provider | 规则兜底 | LLM 综合判断 | `ANALYSIS_PROVIDER=off\|kimi` |
| 检索 provider | mock | playwright 抓取 / gdelt / LLM 内建联网 | `RETRIEVAL_PROVIDER=mock\|playwright\|gdelt\|kimi\|off` |
| 主编排 | 固定 pipeline | 可插拔 agent 循环 | `AGENT_ORCHESTRATOR_ENABLED=false\|true` |

三个开关都默认取"稳定基线"一侧，所以**开箱即 `off + mock + 固定 pipeline`**，零 key、可复现、可回归。

> 说明：`ANALYSIS_PROVIDER` / `RETRIEVAL_PROVIDER` 的枚举值 `kimi` 只是历史遗留的**配置开关字面量**，不代表具体供应商；LLM 调用层已做成供应商中立（见 §6.4），真实模型/端点/密钥全部由 git 忽略的 `backend/.env` 决定。`playwright` 是纯 httpx 抓取百度/Bing 的独立联网检索路径（不依赖浏览器二进制，也不依赖 LLM 内建搜索）。

`backend/.env.example` 是模板（key 字段留空）；真实运行时把密钥和覆盖项放进 **git 忽略的 `backend/.env`**（该文件不进版本库）。理解架构时分两层看：

- **代码结构层**：始终是“输入标准化 -> 检索 -> 消歧 -> agent/规则判定 -> 报告组装”。
- **运行配置层**：只是决定“这一步走 mock 还是走真实 provider、agent 是否启用”。

下面这份说明主图会把两条分支都画出来。贯穿示例则使用稳定的 `off + mock` 路径，因为它最容易复现，也最符合当前仓库里的回归资产。

---

## 3. 仓库结构总览

```text
rumor-checking/
├─ backend/
│  ├─ app/
│  │  ├─ api/                # FastAPI 路由与接口入口
│  │  ├─ core/               # 配置、日志、异常
│  │  ├─ models/             # Pydantic 数据模型
│  │  └─ services/           # 真正的业务流水线与能力组件
│  ├─ tests/                 # 后端测试
│  └─ eval_regression_tests/ # 回归相关脚本
├─ frontend/
│  ├─ app/                   # Next.js 页面入口与全局样式
│  ├─ components/            # 页面编排与展示组件
│  ├─ lib/                   # API client、工具函数、demo case
│  └─ types/                 # 前端侧 Report 类型
├─ contracts/                # 前后端共享 schema
├─ docs/                     # 项目级说明文档
├─ evals/minimal_v1/         # mock 检索与最小回归用例
├─ data/cache/               # 运行期缓存
└─ README.md                 # 仓库总入口
```

### 3.1 各目录在当前架构里的角色

| 目录 | 当前职责 | 关键文件 |
| --- | --- | --- |
| [backend/app/api](../backend/app/api) | 定义 HTTP 接口与流式响应入口 | [backend/app/api/v1/endpoints/analyze.py](../backend/app/api/v1/endpoints/analyze.py) |
| [backend/app/core](../backend/app/core) | 读取配置、安装异常处理、配置日志 | [backend/app/core/config.py](../backend/app/core/config.py) |
| [backend/app/models](../backend/app/models) | 定义 `AnalyzeRequest`、`Report` 等结构 | [backend/app/models/schemas.py](../backend/app/models/schemas.py) |
| [backend/app/services](../backend/app/services) | 实现输入标准化、检索、判定、时间线、报告组装 | [backend/app/services/analyze_pipeline.py](../backend/app/services/analyze_pipeline.py) |
| [frontend/components](../frontend/components) | 把最终 `Report` 和流式事件拆成多个 UI 面板 | [frontend/components/analyze-page.tsx](../frontend/components/analyze-page.tsx) |
| [frontend/lib](../frontend/lib) | 前端请求后端、解析 NDJSON、整理展示逻辑 | [frontend/lib/api-client.ts](../frontend/lib/api-client.ts) |
| [contracts](../contracts) | 固定共享协议，避免前后端各说各话 | [contracts/report.schema.json](../contracts/report.schema.json) |
| [evals/minimal_v1](../evals/minimal_v1) | 提供 mock 检索和最小回归样例 | [evals/minimal_v1/retrieval_cases.json](../evals/minimal_v1/retrieval_cases.json) |
| [data/cache](../data/cache) | 存真实检索缓存，而不是把缓存散落在业务目录 | [data/README.md](../data/README.md) |

---

## 4. 项目总架构图

```mermaid
flowchart LR
    U["用户"] --> FE["Next.js 前端"]
    FE --> API["FastAPI 接口层"]
    API --> PIPE["AnalyzePipeline"]

    PIPE --> NORM["InputNormalizer"]
    PIPE --> RET["RetrievalService"]
    PIPE --> RESOLVE["QuestionResolver / Agent question resolution"]
    PIPE --> SYN["LlmAgentReasoner.synthesize"]
    PIPE --> FALLBACK["ProviderEnricher + ClaimExtractor + VerdictEngine + TimelineBuilder"]
    PIPE --> BUILD["ReportBuilder + ContentCheckBuilder + PipelineTraceBuilder"]

    RET --> CACHE["data/cache/retrieval"]
    RET --> EVAL["evals/minimal_v1 mock cases"]
    BUILD --> CONTRACT["contracts/report.schema.json"]

    API --> STREAM["NDJSON 流式事件"]
    STREAM --> FE
    CONTRACT --> FE
```

这张图里最重要的三个点是：

1. **后端主链路不在路由层，在 `AnalyzePipeline`。**
2. **检索和判定是分开的。**
3. **前端不是只拿最终 JSON，而是同时消费实时事件流和最终 `Report`。**

---

## 5. 前端架构

### 5.1 前端现在的定位

前端现在是一个**面向普通用户的核查产品**，而不是内部工作台。它承担两件事：

- 一个“输入框”：像搜索引擎首页一样，居中一个输入框加几个示例。
- 一个“结果页”：大号判定卡片打头，下面把逐条核查、证据、时间线折叠成可展开区块；执行过程轨迹默认折叠在最底部。

也就是说，普通用户先看到一句话结论和判定色块，需要时再逐层展开细节；开发/调试信息（执行 trace）不占据主视线。

### 5.2 前端核心文件

当前前端已从早期的“多面板工作台”（十余个组件）**收敛为单一页面组件**。核心文件如下：

| 文件 | 当前职责 |
| --- | --- |
| [frontend/app/page.tsx](../frontend/app/page.tsx) | 页面入口，只挂载 `AnalyzePage` |
| [frontend/app/layout.tsx](../frontend/app/layout.tsx) | 根布局与站点标题（“较真核查”） |
| [frontend/app/globals.css](../frontend/app/globals.css) | 全站样式，移动端优先，约 300 行 |
| [frontend/components/analyze-page.tsx](../frontend/components/analyze-page.tsx) | **唯一的页面组件**：搜索态 / 结果态两个视图，内联判定卡片、逐条核查、证据、时间线、执行 trace，并维护输入、流式事件、报告状态 |
| [frontend/lib/api-client.ts](../frontend/lib/api-client.ts) | 请求 `/health`、`/analyze`、`/analyze/stream`，并解析后端返回 |
| [frontend/lib/report-utils.ts](../frontend/lib/report-utils.ts) | 展示层二次整理，例如 verdict 标签、置信度格式化、证据收集 |
| [frontend/lib/report-high-score.ts](../frontend/lib/report-high-score.ts) | 整体可信度、评分拆解等派生指标 |
| [frontend/lib/agent-run.ts](../frontend/lib/agent-run.ts) | 从流式事件派生 agent 调查动作视图 |
| [frontend/lib/demo-cases.ts](../frontend/lib/demo-cases.ts) | 提供搜索态的示例输入卡片 |
| [frontend/types/report.ts](../frontend/types/report.ts) | 前端侧 `Report`、`AnalysisLiveEvent` 类型定义 |

### 5.3 前端结构图

早期把 `Report` 拆给十几个面板组件；现在这些展示逻辑全部内联在 `AnalyzePage` 里，按“搜索态 / 结果态”两个分支渲染，结果态内部再分区块。

```mermaid
flowchart TD
    PAGE["app/page.tsx"] --> ANALYZE["AnalyzePage（单组件）"]

    ANALYZE --> IDLE["搜索态：输入框 + 示例 + 服务状态点"]
    ANALYZE --> RESULT["结果态"]

    RESULT --> VERDICT["判定卡片（色块 + 一句话结论）"]
    RESULT --> CLAIMS["逐条核查（可折叠）"]
    RESULT --> EVIDENCE["证据来源（可折叠）"]
    RESULT --> TIMELINE["传播时间线（可折叠）"]
    RESULT --> TRACE["执行过程 trace（默认折叠）"]

    ANALYZE --> CLIENT["api-client.ts"]
    CLIENT --> STREAM["/api/v1/analyze/stream"]
    CLIENT --> HEALTH["/api/v1/health"]
```

### 5.4 前端请求和渲染流程

```mermaid
sequenceDiagram
    participant U as 用户
    participant A as AnalyzePage
    participant C as api-client
    participant B as Backend

    U->>A: 在搜索框输入文本 / URL / 问题
    A->>A: validateInput()
    A->>C: analyzeReportStream(request)
    C->>B: POST /api/v1/analyze/stream
    B-->>C: NDJSON 事件流
    C-->>A: session / stage / retrieval / log / report / complete
    A->>A: 更新 liveEvents / report / status
    A-->>U: 结果态（判定卡片 + 可折叠区块 + 底部 trace）
```

前端这层最值得讲给面试官的点是：

- `AnalyzePage` 其实就是一个轻量状态机，搜索态和结果态是它的两个视图。
- `api-client.ts` 读的是 **NDJSON 流**，不是等到最后一次性读 JSON。
- 执行过程 trace 直接内联在结果态底部（默认折叠），流式事件仍能让后端每个阶段被追溯。

---

## 6. 后端架构

### 6.1 后端分层

| 层级 | 当前职责 | 关键文件 |
| --- | --- | --- |
| 应用层 | 创建 FastAPI、挂中间件、挂路由 | [backend/app/main.py](../backend/app/main.py) |
| 接口层 | 提供同步分析与流式分析接口 | [backend/app/api/v1/endpoints/analyze.py](../backend/app/api/v1/endpoints/analyze.py) |
| 配置层 | 读取 `.env` / `.env.example` 对应的运行开关 | [backend/app/core/config.py](../backend/app/core/config.py) |
| 协议层 | 定义 `AnalyzeRequest`、`Report`、`PipelineTrace` | [backend/app/models/schemas.py](../backend/app/models/schemas.py) |
| 流水线层 | 串起所有业务步骤 | [backend/app/services/analyze_pipeline.py](../backend/app/services/analyze_pipeline.py) |
| 能力组件层 | 输入标准化、检索、判定、时间线、报告、内容核查 | [backend/app/services](../backend/app/services) |

### 6.2 后端主链路图

```mermaid
flowchart TD
    REQ["AnalyzeRequest"] --> N1["InputNormalizer"]
    N1 --> N2["RetrievalService"]
    N2 --> N3["Question Resolution"]
    N3 --> N4{"是否需要 follow-up?"}
    N4 -->|是| N5["Follow-up Retrieval"]
    N4 -->|否| N6["跳过"]
    N5 --> N7["Agent Synthesis"]
    N6 --> N7
    N7 -->|成功| N8["直接拿到 event / claims / verdict / timeline"]
    N7 -->|失败或关闭| N9["ProviderEnricher"]
    N9 --> N10["ClaimExtractor"]
    N10 --> N11["VerdictEngine"]
    N11 --> N12["TimelineBuilder"]
    N8 --> N13["ReportBuilder"]
    N12 --> N13
    N13 --> N14["ContentCheckBuilder"]
    N13 --> N15["PipelineTraceBuilder"]
    N14 --> OUT["Report"]
    N15 --> OUT
```

### 6.3 流式观测是怎么做的

这里有一个很关键但容易忽略的结构：

- [backend/app/api/v1/endpoints/analyze.py](../backend/app/api/v1/endpoints/analyze.py) 用线程包了一层 `AnalyzePipeline`
- [backend/app/services/progress.py](../backend/app/services/progress.py) 用 `ContextVar` 维护当前请求的回调
- `AnalyzePipeline` 和各服务调用 `emit_stage()`、`emit_log()`、`emit_api_call()`、`emit_retrieval()`
- 前端于是能持续收到 `stage / log / retrieval / report / complete` 等事件

这意味着：

- 流式接口不是把 LLM token 原样回传
- 它回传的是“流水线执行事件”

这正是当前项目和普通聊天页最大的架构区别之一。

### 6.4 核心服务职责表

| 服务 | 当前职责 | 说明 |
| --- | --- | --- |
| [backend/app/services/input_normalizer.py](../backend/app/services/input_normalizer.py) | 识别 `text / url / question`，抽取标题、摘要、关键词、来源 | URL 输入还会尝试正文抽取 |
| [backend/app/services/retrieval_service.py](../backend/app/services/retrieval_service.py) | 生成 query plan，决定走 mock / playwright / gdelt / LLM 内建联网，做缓存与 fallback | 检索不是一条 query，而是一组 query |
| [backend/app/services/question_resolver.py](../backend/app/services/question_resolver.py) | 对问句做事件收束 | 只在 `question_only` 路径生效 |
| [backend/app/services/agent_reasoner.py](../backend/app/services/agent_reasoner.py) | `LlmAgentReasoner`：用 LLM 做 question resolution 和 synthesis | 配置关闭时整段分支失效 |
| [backend/app/services/provider_enricher.py](../backend/app/services/provider_enricher.py) | 给事件补结构化标题/摘要/claim | 属于 fallback 链的一部分 |
| [backend/app/services/claim_extractor.py](../backend/app/services/claim_extractor.py) | 把一句话拆成原子 claim | 规则抽取是默认兜底 |
| [backend/app/services/verdict_engine.py](../backend/app/services/verdict_engine.py) | 给 claim 打 `supported/refuted/insufficient/conflicting` | 依据是 retrieval evidence |
| [backend/app/services/timeline_builder.py](../backend/app/services/timeline_builder.py) | 从检索结果挑时间线节点 | 形成 `origin / amplification / peak / turn / clarification` |
| [backend/app/services/report_builder.py](../backend/app/services/report_builder.py) | 组装最终 `Report`，决定 `safe/partial/complete` | 还负责 investigation 和评分 |
| [backend/app/services/content_check_builder.py](../backend/app/services/content_check_builder.py) | 生成“哪些更像真/假/争议/观点”视图 | 主要为了前端展示 |
| [backend/app/services/pipeline_trace_builder.py](../backend/app/services/pipeline_trace_builder.py) | 把流水线压缩成用户可读的步骤摘要 | 给前端结果区复盘用 |

### 6.5 Agent 编排层（默认关闭，可回退）

上面 6.1–6.4 讲的是**固定 pipeline**。在它之上还有一层**可选的 agent 编排**，由 `AGENT_ORCHESTRATOR_ENABLED` 控制（默认 `false`）。开启后，`AnalyzePipeline.analyze()` 顶部把控制权交给 agent 循环；循环抛错则自动回退固定 pipeline。

关键点是：**agent 编排不是重写业务，而是把 6.4 里那些现成服务当成"工具"来调度。**

| 模块 | 职责 |
| --- | --- |
| [backend/app/agent/state.py](../backend/app/agent/state.py) | `AgentState` 黑板，贯穿所有工具，字段对应固定 pipeline 里的中间产物 |
| [backend/app/agent/planner.py](../backend/app/agent/planner.py) | `Planner` 协议 + `RulePlanner` / `LlmPlanner`；`legal_actions(state)` 是排序的唯一真相源 |
| [backend/app/agent/runner.py](../backend/app/agent/runner.py) | 主循环 `plan -> tool -> observe -> decide -> finalize`，带步数上限与回退 |
| [backend/app/agent_tools/tools.py](../backend/app/agent_tools/tools.py) | 把 `RetrievalService` / `VerdictEngine` / `ReportBuilder` 等薄封装成工具，复用同样的 `emit_stage` |

Planner 可插拔，这是"agent 为主又不破坏基线"的关键取舍：

- `RulePlanner`（默认）：永远取第一个合法动作，复刻固定 pipeline 顺序。在 `off + mock` 上产出与旧链路**逐字节一致**的 `Report`（`backend/tests/test_agent_orchestrator.py` 的 parity 测试保证）。
- `LlmPlanner`（配置 LLM 时启用）：只在真实岔路口调用 LLM；其余强制步骤不浪费 LLM 调用。非法/失败选择一律退回 `RulePlanner`。岔路口的候选动作：`investigate`（补一轮检索）/ `fetch_url`（抓取最权威证据的全文）/ `synthesize`（直接综合）。`fetch_url` 始终排在规则默认动作之后，`RulePlanner`（取第一个）永不选它 → parity 不受影响。

```mermaid
flowchart TD
    REQ["AnalyzeRequest"] --> SW{"AGENT_ORCHESTRATOR_ENABLED?"}
    SW -->|false| PIPE["固定 AnalyzePipeline (6.2)"]
    SW -->|true| RUN["AgentRunner"]
    RUN --> PLAN["Planner.next_action(state)"]
    PLAN --> LEGAL["legal_actions(state)"]
    LEGAL -->|唯一合法| TOOL["执行该工具"]
    LEGAL -->|岔路 & 配置 LLM| LLM["LlmPlanner 调 LLM 决策"]
    LLM --> TOOL
    TOOL --> STATE["写回 AgentState"]
    STATE -->|未完成| PLAN
    STATE -->|finalize| REPORT["Report"]
    RUN -->|抛错| PIPE
```

配合的能力开关：`LIGHTWEIGHT_AGENT_ENABLED`（证据弱时让 LLM planner 追加 1 轮定向检索）、`AGENT_MAX_URL_FETCHES`（允许 planner 抓取几次证据全文，默认 1、0=关）、以及开 LLM 时 `agent_reasoner.synthesize` 接管 grounded verdict（判定必须带证据，否则降级 `insufficient`）。

---

## 7. 核心数据对象

当前代码最重要的四个对象如下：

| 对象 | 所在位置 | 作用 |
| --- | --- | --- |
| `AnalyzeRequest` | [backend/app/models/schemas.py](../backend/app/models/schemas.py) | 前端提交给后端的输入 |
| `NormalizedEvent` | [backend/app/models/schemas.py](../backend/app/models/schemas.py) | 后端内部使用的标准化事件草稿 |
| `RetrievalBundle` | [backend/app/services/retrieval_models.py](../backend/app/services/retrieval_models.py) | 一轮检索的聚合结果 |
| `Report` | [backend/app/models/schemas.py](../backend/app/models/schemas.py) | 前端最终消费的统一结构 |

### 7.1 `AnalyzeRequest`

```json
{
  "raw_input": "用户原始输入",
  "input_type": "text | url | question | auto",
  "request_context": {}
}
```

### 7.2 `NormalizedEvent`

后端会先把原始输入压成一个内部事件对象，大致包含：

- `title`
- `summary`
- `keywords`
- `source_name`
- `input_type`
- `mode_hint`
- `event_source`

这一步的价值是：**后面的检索、claim 提取、时间线构建都不再直接啃原始输入。**

### 7.3 `RetrievalBundle`

它不只是“搜索结果数组”，还包括：

- 实际 query
- provider 名称
- cache 状态
- 原始结果和去重后的 canonical 结果
- evidence grade
- fallback 信息

所以它是当前后端里最像“证据中台对象”的东西。

### 7.4 `Report`

最终 `Report` 是一个面向前端展示的聚合对象，至少包含：

- `mode`
- `event`
- `timeline`
- `claim_results`
- `final_summary`
- `risks`
- `sources`
- `retrieval_hits`
- `provenance`

并且还会带上：

- `content_check`
- `pipeline_trace`
- `investigation`
- `score_breakdown`

这也是为什么前端各个面板都只是“消费同一个 Report 的不同切片”。

---

## 8. 用一个真实例子把整条流程讲清楚

### 8.1 例子选型

这里用前端 demo case 里的“海州酸奶抽检”作为贯穿例子：

```text
海州市市场监管局通报称，海州新鲜屋部分酸奶批次超过保质期，涉事门店已停业整改。
```

原因有两个：

1. 它在当前仓库里有稳定 mock 检索数据。
2. 它能完整覆盖“输入标准化 -> 检索 -> claim -> verdict -> timeline -> report”的整条链路。

### 8.2 本例采用的运行配置

为了让例子稳定可复现，这里按默认稳定基线讲解：

```dotenv
ANALYSIS_PROVIDER=off
RETRIEVAL_PROVIDER=mock
RETRIEVAL_FALLBACK_TO_MOCK=true
RETRIEVAL_CACHE_ENABLED=false
```

这意味着本例会走：

- 不启用 LLM synthesis
- 走 mock retrieval
- 走规则型 claim / verdict / timeline 链路

### 8.3 例子在当前代码里的实际中间结果

#### 第一步：输入标准化

`InputNormalizer` 会把输入整理成：

```json
{
  "input_type": "text_news",
  "title": "海州市市场监管局通报称，海州新鲜屋部分酸奶批次超过保质期",
  "summary": "海州市市场监管局通报称，海州新鲜屋部分酸奶批次超过保质期，涉事门店已停业整改。",
  "keywords": ["海州市市场监管局", "海州新鲜屋", "停业整改", "酸奶", "涉事门店已停业"],
  "source_name": "海州市市场监管局",
  "mode_hint": "complete_or_partial",
  "event_source": "input_normalized"
}
```

这一步的含义是：

- 输入已经被识别为“文本新闻”
- 后端已经拿到了标题、摘要、关键词
- 后面不是直接拿原句去判断，而是拿这个标准化结果继续跑

#### 第二步：生成 query plan 并做首轮检索

`RetrievalService` 针对这段文本生成了 3 条主要 query：

| query label | 实际 query 作用 |
| --- | --- |
| `event_core` | 用标题、摘要、关键词抓主结果 |
| `event_claim` | 收紧到更接近 claim 的表述 |
| `event_official` | 优先抓官方回应与权威结果 |

在 mock 路径里，这组 query 最终命中了回归样例 `R01`：

```json
{
  "provider": "mock",
  "matched_case_id": "R01",
  "mode_hint": "complete",
  "evidence_grade": "A",
  "canonical_results": 4,
  "high_trust_result_count": 3,
  "independent_source_count": 4
}
```

命中的典型结果包括：

- 海州市市场监管局通报
- 海州日报跟进报道
- 海州新鲜屋致歉说明
- 一条低可信自媒体“多人中毒”说法

这一步的意义是：**后面所有 verdict 和 timeline 都要建立在 `RetrievalBundle` 上，而不是建立在输入句子本身上。**

#### 第三步：问题消歧在本例里会跳过

因为本例是 `text_news`，不是 `question_only`，所以：

- `question_resolution` 跳过
- `retrieval_follow_up` 也跳过

这说明当前后端流水线是 **按输入类型分支** 的，不是每次都把所有步骤跑一遍。

#### 第四步：Agent synthesis 在本例里不会生效

因为本例配置了 `ANALYSIS_PROVIDER=off`，所以：

- `agent_synthesis` 会进入 warning/跳过式路径
- 后端退回规则兜底链路

这也是当前代码里一个很关键的架构特点：

- **流水线始终先保留 agent 分支的位置**
- **但默认稳定演示路径仍然依赖规则兜底保证可交付**

#### 第五步：Claim 抽取

`ClaimExtractor` 在本例里抽出了 3 条事实 claim：

```text
1. 海州市市场监管局通报称。
2. 海州新鲜屋部分酸奶批次超过保质期。
3. 酸奶已停业整改。
```

这里要注意，它抽出来的是“可判定的原子事实”，不是整段原文。

#### 第六步：Claim 判定

`VerdictEngine` 基于 `RetrievalBundle` 给这 3 条 claim 的结果都是：

| claim | verdict | confidence |
| --- | --- | --- |
| 海州市市场监管局通报称。 | `supported` | `high` |
| 海州新鲜屋部分酸奶批次超过保质期。 | `supported` | `high` |
| 酸奶已停业整改。 | `supported` | `high` |

对应证据来源是：

```json
{
  "evidence_source": "retrieval_mock",
  "evidence_grade": "A"
}
```

也就是说，这个例子不是“模型说是真的”，而是：

- 官方通报和主流媒体已经足够支撑核心 claim
- 所以规则引擎可以把它们判成 `supported`

#### 第七步：时间线构建

`TimelineBuilder` 为本例还原出了 3 个节点：

| 节点类型 | 节点内容 |
| --- | --- |
| `origin` | 海州市市场监管局通报海州新鲜屋整改情况 |
| `amplification` | 海州日报：海州新鲜屋两门店停售整改 |
| `turn` | 海州新鲜屋发布致歉说明 |

对应结果：

```json
{
  "source": "retrieval",
  "nodes": 3,
  "completeness": 65,
  "confidence": 92
}
```

这一步把“有证据”进一步提升为“证据之间有传播顺序和角色关系”。

#### 第八步：最终报告组装

`ReportBuilder` 最终给出的核心结果是：

```json
{
  "mode": "complete_mode",
  "overall_credibility_score": 87.4,
  "overall_credibility_label": "high_credibility",
  "provenance": {
    "source_type": "backend_mock",
    "claim_source": "rule",
    "evidence_source": "retrieval_mock",
    "timeline_source": "retrieval"
  }
}
```

最终总结语是：

> 已形成相对完整的公开证据链，当前更倾向于：海州市市场监管局通报称。

同时它还保留了一个重要风险提示：

> 当前结果来自 mock 数据或 mock 回退路径，不能当作真实联网核查结论。

这就是当前项目的设计取舍：

- 结果可以完整
- 但 provenance 也必须老实告诉你它是不是 mock

### 8.4 这条例子的完整时序图

```mermaid
sequenceDiagram
    autonumber
    participant U as 用户
    participant FE as 前端 AnalyzePage
    participant API as /analyze/stream
    participant PIPE as AnalyzePipeline
    participant N as InputNormalizer
    participant R as RetrievalService
    participant C as ClaimExtractor
    participant V as VerdictEngine
    participant T as TimelineBuilder
    participant B as ReportBuilder

    U->>FE: 提交海州酸奶抽检文本
    FE->>API: POST AnalyzeRequest
    API-->>FE: session 事件

    API->>PIPE: analyze()
    PIPE->>N: normalize()
    N-->>PIPE: NormalizedEvent(text_news)
    PIPE-->>FE: stage(normalize_input)

    PIPE->>R: retrieve_for_event()
    R-->>PIPE: RetrievalBundle(provider=mock, case=R01)
    PIPE-->>FE: stage(retrieval_initial)

    PIPE-->>FE: stage(question_resolution: skipped)
    PIPE-->>FE: stage(retrieval_follow_up: skipped)
    PIPE-->>FE: stage(agent_synthesis: warning)

    PIPE->>C: extract_with_source()
    C-->>PIPE: 3 条 fact claims
    PIPE->>V: evaluate_with_source()
    V-->>PIPE: 3 条 supported verdict
    PIPE->>T: build_with_source()
    T-->>PIPE: 3 个 timeline nodes

    PIPE->>B: build()
    B-->>PIPE: complete_mode Report
    API-->>FE: report 事件
    API-->>FE: complete 事件
    FE-->>U: 实时直播 + 最终结论面板
```

### 8.5 这个例子能说明什么

这个例子把当前系统最核心的设计讲出来了：

1. **输入先标准化，再进入后续链路。**
2. **检索是流水线中枢，claim、verdict、timeline 都围绕它。**
3. **Agent 是可选增强，不是唯一依赖。**
4. **最终输出不是一段话，而是一份结构化 `Report`。**
5. **前端展示的不只是答案，还包括答案是怎么来的。**

---

## 9. 当前项目最适合怎么讲

如果你要向别人解释这个项目，最稳的表述是：

> 这是一个带执行过程可视化的谣言核查工作台。前端负责把一次分析过程完整展示出来，后端把输入加工成标准化事件，再做检索、消歧、claim 判定、时间线构建和报告组装。当前代码同时支持稳定 mock 基线和 LLM 增强路径，但无论走哪条路径，最终都统一收敛到一份带 provenance 的 `Report`。

再压缩一点，可以直接说：

> 当前架构的关键词不是“大模型”，而是“结构化流水线 + 流式可观测 + 契约化输出”。 

---

## 10. 你看代码时的推荐阅读顺序

如果你要自己继续深入，推荐按这个顺序读：

1. [frontend/components/analyze-page.tsx](../frontend/components/analyze-page.tsx)
2. [frontend/lib/api-client.ts](../frontend/lib/api-client.ts)
3. [backend/app/api/v1/endpoints/analyze.py](../backend/app/api/v1/endpoints/analyze.py)
4. [backend/app/services/analyze_pipeline.py](../backend/app/services/analyze_pipeline.py)
5. [backend/app/services/input_normalizer.py](../backend/app/services/input_normalizer.py)
6. [backend/app/services/retrieval_service.py](../backend/app/services/retrieval_service.py)
7. [backend/app/services/claim_extractor.py](../backend/app/services/claim_extractor.py)
8. [backend/app/services/verdict_engine.py](../backend/app/services/verdict_engine.py)
9. [backend/app/services/timeline_builder.py](../backend/app/services/timeline_builder.py)
10. [backend/app/services/report_builder.py](../backend/app/services/report_builder.py)
11. [contracts/report.schema.json](../contracts/report.schema.json)

按这个顺序读，最容易把“页面怎么发请求”一路连到“报告是怎么长出来的”。
