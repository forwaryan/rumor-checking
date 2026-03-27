# 轻量 Agent 化多 Agent 协作任务记录规范与执行看板

日期：2026-03-27

## 文档目的

这份文档只做一件事：为“轻量 Agent 化”改造提供一份可被多个 Agent 共同维护、共同认领、共同更新的任务记录文档。

当前阶段目标：

- 先把任务记录体系搭起来。
- 先把任务拆到足够细。
- 先把并行执行和认领规则写清楚。
- 当前不启动任何新的执行 Agent 去真正完成代码任务。

当前结论：

- 这份文档已经完成任务治理层的初始化。
- 当前没有任何代码实现任务被认领。
- 当前已经冻结第一轮写入边界、认领顺序和 Agent 命名规范。

## 1. 使用规则

## 1.1 Agent 命名约定

所有执行 Agent 在认领任务时必须使用稳定的 Agent 标识。

首批保留 Agent ID：

| Agent ID | 角色定位 | 默认负责范围 | 备注 |
| --- | --- | --- | --- |
| `main` | 主控 Agent | 跨模块整合、关键契约拍板、冲突收口 | 默认唯一 |
| `backend-1` | 后端 Agent | 基础模块、schema、policy、runner 辅助任务 | 非主链整合任务优先 |
| `backend-2` | 后端 Agent | Tool 层封装、后端测试 | 可与 `backend-1` 并行 |
| `frontend-1` | 前端 Agent | 类型、解析器、组件 | 不负责后端主流程 |
| `frontend-2` | 前端 Agent | 样式、局部 UI 组件、前端测试 | 与 `frontend-1` 分文件并行 |
| `qa-1` | 验证 Agent | 后端/前端测试补齐、回归验证 | 不参与主架构拍板 |
| `docs-1` | 文档 Agent | 过程记录、说明文档、Demo 更新 | 不改业务代码 |
| `subagent-*` | 子 Agent | 明确指定的独立子任务 | 必须带职责前缀 |

子 Agent 命名规则：

- 命名格式：`subagent-<域>-<职责>-<序号>`
- 例子：
  - `subagent-backend-tool-01`
  - `subagent-backend-tool-02`
  - `subagent-frontend-ui-01`
  - `subagent-test-01`
  - `subagent-docs-01`

约束：

- 同一个 Agent 在整份文档中始终使用同一个名字。
- 不允许在一个任务上同时写多个 `Owner`。
- 一个任务同一时刻只能有一个 `Owner`。
- 一个子 Agent 只负责一个连续任务簇，不要跨域切换。

## 1.2 任务认领规则

任一 Agent 认领任务前，必须按以下顺序执行：

1. 重新读取这份任务记录文档的最新版本。
2. 确认目标任务是叶子任务，而不是父任务。
3. 确认任务状态为 `ready`，且 `Owner` 为 `-`。
4. 确认该任务的 `Write Scope` 没有和其他已认领任务冲突。
5. 修改该任务行：
   - `Status` 改为 `claimed`
   - `Owner` 写入当前 Agent 名
   - `Claimed At` 写入时间
   - `Updated At` 写入时间
6. 在文档末尾“任务变更日志”新增一条记录，写明是谁认领了什么任务。

禁止行为：

- 不允许直接认领 `todo` 状态的任务。
- 不允许认领 `Owner` 非空的任务。
- 不允许认领与已认领任务存在写入范围冲突的任务。
- 不允许越过依赖直接开工。

## 1.3 任务状态流转规则

推荐状态流转：

- `todo`
  - 任务存在，但依赖未满足，不可认领。
- `ready`
  - 依赖已满足，可认领。
- `claimed`
  - 已被某个 Agent 认领，但尚未进入实作。
- `in_progress`
  - Agent 已开始实际执行。
- `blocked`
  - 执行中遇到阻塞，需要等待依赖、接口定稿或冲突解除。
- `done`
  - 任务完成，且任务表已更新。
- `cancelled`
  - 任务被废弃或并入其他任务。

状态更新规则：

- Agent 开始实作前，应把 `claimed` 改为 `in_progress`。
- Agent 做完后，应把状态改为 `done`。
- Agent 如果被阻塞，应改为 `blocked`，并在 `Notes` 写明阻塞原因和依赖任务。
- 只有在依赖满足后，`todo` 才能改成 `ready`。

## 1.4 父任务和叶子任务规则

本任务表分为“阶段父任务”和“叶子执行任务”。

规则：

- 只有叶子任务可以被认领。
- 父任务不允许被直接认领。
- 父任务的进度由子任务聚合得出。
- 谁更新叶子任务，谁同时更新所属阶段汇总表。

## 1.5 写入范围冲突规则

为了支持多 Agent 并行，这份任务表明确记录每个任务的 `Write Scope`。

认领时必须遵守：

- 如果两个任务写同一个文件，不能并行认领。
- 如果两个任务写同一个核心模块目录，默认不能并行，除非明确标记为允许。
- 如果任务只读某些文件但不写，可以并行。
- 如果任务新增独立文件且与其他任务不冲突，优先划为 `subagent_parallel`。

## 1.6 完成后的更新规则

任务完成后，执行 Agent 必须同步更新：

- 任务行状态
- `Updated At`
- `Notes`
- 对应阶段汇总行的统计数字
- 文档末尾任务变更日志

建议写清楚：

- 修改了哪些文件
- 是否已跑测试
- 是否存在后续阻塞

## 1.7 时间格式规范

这份文档统一使用以下时间格式：

- 展示格式：`YYYY-MM-DD HH:mm CST`
- 解释含义：这里的 `CST` 固定表示 `Asia/Shanghai (UTC+08:00)`，不表示北美时区

示例：

- `2026-03-27 20:16 CST`

填写规则：

- `Claimed At` 只在首次认领时填写。
- `Updated At` 每次状态变化都要刷新。
- 任务变更日志中的 `Time` 必须和本次表格更新时间一致。

## 1.8 变更日志书写规范

每条任务变更日志必须包含：

- 时间
- Agent 名
- Task ID
- 动作
- 简短说明

允许的 `Action`：

- `claimed`
- `in_progress`
- `blocked`
- `done`
- `cancelled`
- `status_sync`

推荐模板：

```text
| 2026-03-27 20:10 CST | backend-1 | TOOL-001 | claimed | 认领 search_news Tool 封装任务 |
| 2026-03-27 20:24 CST | backend-1 | TOOL-001 | in_progress | 已开始修改 backend/app/agent_tools/search_news.py |
| 2026-03-27 20:41 CST | backend-1 | TOOL-001 | done | 已完成 Tool 封装和单测，修改 2 个文件，未发现阻塞 |
```

## 1.9 Notes 字段书写规范

`Notes` 必须写成简短执行摘要，至少包含下面信息中的两项：

- 当前是否可继续
- 写了哪些文件
- 是否已测试
- 是否有阻塞
- 下一步依赖谁

推荐模板：

```text
已完成；修改 backend/app/agent_tools/search_news.py 和 backend/tests/test_agent_tool_search_news.py；已跑定向单测；无阻塞。
```

```text
阻塞中；等待 RUN-006 冻结 Agent 流式事件字段；当前未改代码。
```

## 2. 字段定义

| 字段 | 含义 |
| --- | --- |
| `Task ID` | 任务唯一标识，不可重复 |
| `Parent` | 所属阶段或父任务 |
| `Task` | 任务名称 |
| `Write Scope` | 允许写入的文件或目录范围 |
| `Depends On` | 依赖的前置任务 |
| `Execution Mode` | `serial` / `parallel` / `subagent_parallel` |
| `Recommended Executor` | `main` / `subagent` / `any` |
| `Claim Rule` | 认领前必须满足的条件 |
| `Exit Criteria` | 完成判定标准 |
| `Status` | 当前任务状态 |
| `Owner` | 当前认领人 |
| `Claimed At` | 认领时间 |
| `Updated At` | 最近更新时间 |
| `Notes` | 当前说明、阻塞信息、完成摘要 |

## 3. 并行执行总规划

## 3.1 执行波次说明

这次改造建议按“波次”而不是按“单线顺序”执行。

原因：

- 可以把多个 Agent 的工作切成明确的并行批次。
- 每个波次都能控制依赖边界。
- 更容易在多人/多 Agent 场景下避免文件冲突。

## 3.2 推荐波次表

| 波次 | 性质 | 任务范围 | 是否可并行 | 是否适合子 Agent | 说明 |
| --- | --- | --- | --- | --- | --- |
| Wave 0 | 基础治理 | `BOARD-*` | 部分可并行 | 否 | 先把认领规则、文件边界和命名规范定好 |
| Wave 1 | 后端基础 | `BASE-*` | 部分可并行 | 否 | 定义模块脚手架、开关和后端 schema |
| Wave 2 | Tool 层 | `TOOL-*` | 高并行 | 是 | 最适合拆给多个子 Agent 的阶段 |
| Wave 3 | Runner 层 | `RUN-*` | 中并行 | 部分适合 | 核心集成逻辑由主 Agent 控制更稳 |
| Wave 4 | 前端接入 | `UI-*` | 中并行 | 部分适合 | 类型、解析器、组件和样式可拆分 |
| Wave 5 | 测试验证 | `TEST-*` | 高并行 | 是 | 各测试域基本可以拆分 |
| Wave 6 | 文档收口 | `DOC-*` | 高并行 | 是 | 文档、Demo 和清单可并行完成 |

## 3.3 哪些任务适合并行

适合直接并行的任务：

- 不写同一个文件
- 不依赖同一个未冻结接口
- 有明确独立交付物

典型并行任务：

- `TOOL-001` 到 `TOOL-007`
- `TEST-002`、`TEST-004`、`TEST-005`
- `DOC-001`、`DOC-002`、`DOC-003`

## 3.4 哪些任务适合通过子 Agent 并行

最适合子 Agent 的任务特征：

- 写入范围小
- 输入输出清晰
- 与主线集成解耦

推荐交给子 Agent 的任务：

- Tool 封装类任务
- 前端新面板组件任务
- 文档更新任务
- 独立测试任务

不建议交给子 Agent 的任务：

- 核心 Runner 集成
- 主流程 fallback 逻辑
- 后端和前端契约的最终拍板
- 跨多个关键文件的大规模收口任务

## 3.5 第一轮冻结写入边界

这一节用于完成 `BOARD-003` 的核心要求。后续第一轮执行必须遵守下面的写入边界。

| Lane | 允许写入范围 | 独占文件 | 可并行对象 | 说明 |
| --- | --- | --- | --- | --- |
| `governance` | `implementation-log/**` | 当前任务看板文件 | `docs-only` | 只允许任务治理和过程记录任务修改 |
| `backend-config` | `backend/app/core/config.py`, `backend/.env.example`, `backend/README.md` | `backend/app/core/config.py` | `frontend-*`, `docs-*` | 由配置类任务独占 |
| `backend-schema` | `backend/app/models/schemas.py` | `backend/app/models/schemas.py` | `backend-config`, `docs-*` | schema 未冻结前，不允许前端类型任务启动 |
| `backend-agent-base` | `backend/app/agent/**`, `backend/app/agent_tools/**` | 目录初始化文件 | `backend-tests` | `BASE-001` 执行时独占目录初始化 |
| `backend-tool-single-file` | `backend/app/agent_tools/*.py` 对应单文件 | 各自 Tool 文件 | 其他 Tool 文件 | 不同 Tool 文件可并行，不允许改同一个 Tool 文件 |
| `backend-runner-core` | `backend/app/agent/*.py`, `backend/app/services/analyze_pipeline.py`, `backend/app/api/v1/endpoints/analyze.py` | `runner.py`, `analyze_pipeline.py`, `analyze.py` | `frontend-*`, `docs-*` | 核心集成阶段由主 Agent 控制 |
| `backend-tests` | `backend/tests/*.py` 新增或独立测试文件 | 测试文件自身 | 绝大多数非同文件任务 | 不允许两个 Agent 同时写同一测试文件 |
| `frontend-types` | `frontend/types/report.ts` | `frontend/types/report.ts` | `backend-tool-single-file`, `docs-*` | 类型冻结前不启动前端解析和 UI 集成 |
| `frontend-client` | `frontend/lib/api-client.ts`, 对应测试 | `frontend/lib/api-client.ts` | 新增独立组件 | 解析器任务独占 |
| `frontend-component-single-file` | `frontend/components/*.tsx` 对应单文件 | 各自组件文件 | 其他组件文件 | 不同组件文件可并行 |
| `frontend-page-shell` | `frontend/components/analyze-page.tsx` | `frontend/components/analyze-page.tsx` | 样式、测试、文档 | 页面整合任务独占 |
| `frontend-style` | `frontend/app/globals.css` | `frontend/app/globals.css` | 只读分析任务 | 样式任务独占 |
| `docs-only` | `docs/**`, `DEMO_SCRIPT.md`, `SMOKE_CHECKLIST.md` | 各自文档文件 | 大多数代码任务 | 只在对应功能完成后认领 |

冻结规则：

- 第一轮中，凡是落在“独占文件”一栏的文件，同一时刻只能有一个 Agent 写入。
- Tool 文件按单文件拆分，可并行。
- UI 组件按单文件拆分，可并行。
- `analyze_pipeline.py`、`analyze.py`、`frontend/types/report.ts`、`frontend/lib/api-client.ts`、`frontend/components/analyze-page.tsx` 视为高冲突文件，必须独占。

## 3.6 第一轮认领顺序冻结

为了降低冲突，第一轮认领顺序固定如下：

| 顺位 | 可认领任务 | 认领方式 | 说明 |
| --- | --- | --- | --- |
| 1 | `BOARD-002`, `BOARD-003` | `main` 串行完成 | 先把治理规则和边界冻结 |
| 2 | `BASE-001`, `BASE-002`, `BASE-003` | `main + 1 subagent` | 基础目录、配置、schema 先完成 |
| 3 | `TOOL-000` | `main` 独占 | Tool 协议先定稿 |
| 4 | `TOOL-001` 到 `TOOL-007` | 多个 subagent 并行 | 最适合高并发拆分 |
| 5 | `RUN-001`, `RUN-002`, `RUN-003` | `main + 1 subagent` | 先把 state、planner、policy 补齐 |
| 6 | `RUN-004` | `main` 独占 | 核心主循环整合 |
| 7 | `RUN-005`, `RUN-006` | `main` 串行 | 先接 pipeline，再接流式接口 |
| 8 | `UI-001`, `UI-002`, `UI-003`, `UI-005` | `frontend-1 + frontend-2 + subagent` | 前端类型、解析、新面板和旧面板升级并行 |
| 9 | `UI-004` | `main` 或 `frontend-1` 独占 | 页面整合最后做 |
| 10 | `UI-006` | `frontend-2` 或 subagent | 样式收口 |
| 11 | `TEST-*` | `qa-1 + subagent` | 以独立测试文件并行推进 |
| 12 | `DOC-*` | `docs-1 + subagent` | 文档和 Demo 收尾 |

## 3.7 推荐同时启动的 Agent 规模

第一轮建议的最大并发规模：

- Wave 0 到 Wave 1：`1 main + 1 subagent`
- Wave 2：`1 main + 4 subagents`
- Wave 3：`1 main + 2 subagents`
- Wave 4：`1 main + 2 frontend/subagents`
- Wave 5：`1 qa + 3 subagents`
- Wave 6：`1 docs + 2 subagents`

不建议一开始就超过 `6` 个并行 Agent。

原因：

- 高冲突文件数量不多。
- 过多 Agent 会导致任务表维护成本高于实现收益。
- 当前仓库的关键整合点仍集中在少数文件上。

## 4. 阶段汇总表

说明：

- 本表用于快速查看整体进度。
- 每次叶子任务状态变化后，负责更新的 Agent 需要同步修改这一节。

| Phase ID | 阶段 | 叶子任务数 | Ready | Claimed/In Progress | Done | Blocked | 阶段状态 | 说明 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| BOARD | 任务治理与协作规范 | 3 | 0 | 0 | 3 | 0 | done | 初始任务表、命名规范、时间格式、写入边界与认领顺序均已冻结 |
| BASE | 后端基础与契约 | 3 | 3 | 0 | 0 | 0 | active | `BOARD-003` 已完成，基础任务现已可认领 |
| TOOL | Tool 层封装 | 8 | 0 | 0 | 0 | 0 | todo | 依赖基础模块和 Tool 协议落地 |
| RUN | Runner 与主流程集成 | 6 | 0 | 0 | 0 | 0 | todo | 依赖 Tool 层和后端 schema |
| UI | 前端接入与展示 | 6 | 0 | 0 | 0 | 0 | todo | 依赖流式事件契约冻结 |
| TEST | 测试与验证 | 6 | 0 | 0 | 0 | 0 | todo | 依赖对应模块初步完成 |
| DOC | 文档与演示收口 | 4 | 1 | 0 | 0 | 0 | active | `DOC-004` 可持续更新，其余文档任务等待功能实现解锁 |

## 5. 详细任务表

## 5.1 BOARD：任务治理与协作规范

| Task ID | Parent | Task | Write Scope | Depends On | Execution Mode | Recommended Executor | Claim Rule | Exit Criteria | Status | Owner | Claimed At | Updated At | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BOARD-001 | BOARD | 创建多 Agent 任务记录规范与执行看板 | `implementation-log/2026-03-27-lightweight-agent-multi-agent-task-board.md`, `implementation-log/README.md` | - | serial | main | 初始任务，可由当前主 Agent 完成 | 任务表、认领规则、并行规划和详细任务表已落盘 | done | main | 2026-03-27 20:00 CST | 2026-03-27 20:00 CST | 已完成；当前仅建立记录体系，不启动代码实现任务。 |
| BOARD-002 | BOARD | 定义 Agent ID、更新时间格式和日志书写规范 | `implementation-log/2026-03-27-lightweight-agent-multi-agent-task-board.md` | BOARD-001 | serial | main | 仅在 `BOARD-001` 完成后可认领 | 文档中补齐稳定命名规范、时间格式和变更日志规范 | done | main | 2026-03-27 20:10 CST | 2026-03-27 20:10 CST | 已完成；新增首批保留 Agent ID、子 Agent 命名规则、时间格式、变更日志模板和 Notes 模板。 |
| BOARD-003 | BOARD | 冻结第一轮文件写入边界和任务认领顺序 | `implementation-log/2026-03-27-lightweight-agent-multi-agent-task-board.md` | BOARD-001 | serial | main | 仅在 `BOARD-001` 完成后可认领 | `BASE-*`、`TOOL-*`、`RUN-*`、`UI-*` 的写入边界明确，不再冲突 | done | main | 2026-03-27 20:16 CST | 2026-03-27 20:16 CST | 已完成；新增第一轮写入边界冻结表、认领顺序冻结表，并解锁 `BASE-*` 与 `DOC-004`。 |

## 5.2 BASE：后端基础与契约

| Task ID | Parent | Task | Write Scope | Depends On | Execution Mode | Recommended Executor | Claim Rule | Exit Criteria | Status | Owner | Claimed At | Updated At | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BASE-001 | BASE | 新建 `backend/app/agent/` 与 `backend/app/agent_tools/` 基础目录和模块脚手架 | `backend/app/agent/**`, `backend/app/agent_tools/**` | BOARD-003 | serial | main | `BOARD-003` 完成后才可认领；不能和其他写同目录初始化文件的任务并行 | 目录、`__init__.py` 和基础模块占位文件建立完成 | ready | - | - | 2026-03-27 20:16 CST | 已解锁；建议主 Agent 优先认领。 |
| BASE-002 | BASE | 增加轻量 Agent 配置开关与运行上限配置 | `backend/app/core/config.py`, `backend/.env.example`, `backend/README.md` | BOARD-003 | parallel | any | `BOARD-003` 完成；不能与其他改 `config.py` 的任务并行 | 配置项可控制开启/关闭轻量 Agent、轮数和工具上限 | ready | - | - | 2026-03-27 20:16 CST | 已解锁；可与 `BASE-001`、`BASE-003` 分范围并行。 |
| BASE-003 | BASE | 新增后端 Agent 运行数据模型 | `backend/app/models/schemas.py` | BOARD-003 | parallel | main | `BOARD-003` 完成；不能与其他改 `schemas.py` 的任务并行 | 增加 `AgentRun`、`AgentStep`、`ToolCall`、`Observation`、`AgentTrace` 等模型 | ready | - | - | 2026-03-27 20:16 CST | 已解锁；完成后可开启部分前端类型任务。 |

## 5.3 TOOL：Tool 层封装

| Task ID | Parent | Task | Write Scope | Depends On | Execution Mode | Recommended Executor | Claim Rule | Exit Criteria | Status | Owner | Claimed At | Updated At | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TOOL-000 | TOOL | 定义 Tool 协议、ToolResult 包装和公共错误结构 | `backend/app/agent_tools/base.py` | BASE-001, BASE-003 | serial | main | 依赖 `BASE-001` 和 `BASE-003`；完成前，其他 `TOOL-*` 不可认领 | 所有 Tool 有统一输入输出和错误返回结构 | todo | - | - | - | Tool 层总开关任务。 |
| TOOL-001 | TOOL | 封装 `search_news` Tool | `backend/app/agent_tools/search_news.py`, `backend/tests/test_agent_tool_search_news.py` | TOOL-000 | subagent_parallel | subagent | `TOOL-000` 完成；写入范围不能被占用 | 检索服务包装为标准 Tool，并有对应单测 | todo | - | - | - | 适合子 Agent。 |
| TOOL-002 | TOOL | 封装 `resolve_question` Tool | `backend/app/agent_tools/resolve_question.py`, `backend/tests/test_agent_tool_resolve_question.py` | TOOL-000 | subagent_parallel | subagent | `TOOL-000` 完成；写入范围不能被占用 | 问题消歧能力包装为标准 Tool，并有对应单测 | todo | - | - | - | 适合子 Agent。 |
| TOOL-003 | TOOL | 封装 `fetch_url_content` Tool | `backend/app/agent_tools/fetch_url_content.py`, `backend/tests/test_agent_tool_fetch_url_content.py` | TOOL-000 | subagent_parallel | subagent | `TOOL-000` 完成；写入范围不能被占用 | URL 正文抓取包装为标准 Tool，并有对应单测 | todo | - | - | - | 适合子 Agent。 |
| TOOL-004 | TOOL | 封装 `extract_claims` Tool | `backend/app/agent_tools/extract_claims.py`, `backend/tests/test_agent_tool_extract_claims.py` | TOOL-000 | subagent_parallel | subagent | `TOOL-000` 完成；写入范围不能被占用 | claim 抽取包装为标准 Tool，并有对应单测 | todo | - | - | - | 适合子 Agent。 |
| TOOL-005 | TOOL | 封装 `judge_claims` Tool | `backend/app/agent_tools/judge_claims.py`, `backend/tests/test_agent_tool_judge_claims.py` | TOOL-000 | subagent_parallel | subagent | `TOOL-000` 完成；写入范围不能被占用 | verdict 判断包装为标准 Tool，并有对应单测 | todo | - | - | - | 适合子 Agent。 |
| TOOL-006 | TOOL | 封装 `build_timeline` Tool | `backend/app/agent_tools/build_timeline.py`, `backend/tests/test_agent_tool_build_timeline.py` | TOOL-000 | subagent_parallel | subagent | `TOOL-000` 完成；写入范围不能被占用 | 时间线构建包装为标准 Tool，并有对应单测 | todo | - | - | - | 适合子 Agent。 |
| TOOL-007 | TOOL | 封装 `finalize_report` Tool | `backend/app/agent_tools/finalize_report.py`, `backend/tests/test_agent_tool_finalize_report.py` | TOOL-000 | subagent_parallel | subagent | `TOOL-000` 完成；写入范围不能被占用 | `ReportBuilder` 包装为标准 Tool，并有对应单测 | todo | - | - | - | 适合子 Agent。 |

## 5.4 RUN：Runner 与主流程集成

| Task ID | Parent | Task | Write Scope | Depends On | Execution Mode | Recommended Executor | Claim Rule | Exit Criteria | Status | Owner | Claimed At | Updated At | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RUN-001 | RUN | 实现 Agent 状态记录器和 Trace 聚合器 | `backend/app/agent/state.py`, `backend/app/agent/trace.py`, `backend/tests/test_agent_state.py` | BASE-001, BASE-003 | parallel | any | 依赖基础模块和 schema；不得与同文件写冲突 | 能记录 `run`、`step`、`tool_call`、`observation` 和汇总 `trace` | todo | - | - | - | 可与部分 Tool 并行。 |
| RUN-002 | RUN | 实现 Planner 协议与 Planner Prompt 结构 | `backend/app/agent/planner.py`, `backend/tests/test_agent_planner.py` | BASE-001, BASE-003 | parallel | main | 依赖基础模块和 schema；建议由主 Agent 定调 | Planner 输入输出稳定，能给出下一步动作建议 | todo | - | - | - | Runner 的上游契约。 |
| RUN-003 | RUN | 实现停止条件、轮数限制和决策策略 | `backend/app/agent/policy.py`, `backend/tests/test_agent_policy.py` | RUN-002, BASE-002 | parallel | any | 依赖 Planner 协议和配置开关 | 明确何时继续、何时停止、何时 fallback | todo | - | - | - | 可与部分 Tool 并行。 |
| RUN-004 | RUN | 实现轻量 Agent Runner 主循环 | `backend/app/agent/runner.py`, `backend/tests/test_lightweight_agent_runner.py` | TOOL-000, TOOL-001, TOOL-002, TOOL-003, TOOL-004, TOOL-005, TOOL-006, TOOL-007, RUN-001, RUN-003 | serial | main | 关键集成任务；依赖所有 Tool 和核心策略到位 | 主循环支持 `plan -> tool_call -> observation -> decision -> finalize` | todo | - | - | - | 主 Agent 独占任务。 |
| RUN-005 | RUN | 将 Runner 以可回退方式接入现有 `AnalyzePipeline` | `backend/app/services/analyze_pipeline.py`, `backend/tests/test_lightweight_agent_pipeline_bridge.py` | RUN-004 | serial | main | 依赖 `RUN-004`；不能与其他改 `analyze_pipeline.py` 的任务并行 | 可通过配置切换轻量 Agent；失败时自动回退旧链路 | todo | - | - | - | 主 Agent 独占任务。 |
| RUN-006 | RUN | 扩展流式接口以输出 Agent 事件 | `backend/app/api/v1/endpoints/analyze.py`, `backend/tests/test_api_agent_stream.py` | RUN-004 | serial | main | 依赖 `RUN-004`；不能与其他改 `analyze.py` 的任务并行 | 新流式事件类型稳定且向前兼容 | todo | - | - | - | 前端阶段依赖此任务定稿。 |

## 5.5 UI：前端接入与展示

| Task ID | Parent | Task | Write Scope | Depends On | Execution Mode | Recommended Executor | Claim Rule | Exit Criteria | Status | Owner | Claimed At | Updated At | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| UI-001 | UI | 扩展前端类型定义以支持 Agent Trace 和新流式事件 | `frontend/types/report.ts` | BASE-003, RUN-006 | serial | any | 依赖后端 schema 和事件类型冻结；不能与其他改 `report.ts` 的任务并行 | 前端类型与后端流式事件和 `Report` 契约对齐 | todo | - | - | - | 前端所有任务的基础。 |
| UI-002 | UI | 更新 API Client 以解析 Agent 事件 | `frontend/lib/api-client.ts`, `frontend/lib/__tests__/api-client.test.ts` | UI-001 | parallel | any | 依赖 `UI-001`；不能与其他改 `api-client.ts` 的任务并行 | 新事件可被正确解析并保留旧事件兼容性 | todo | - | - | - | 前端解析层。 |
| UI-003 | UI | 新增 Agent 调查过程面板组件 | `frontend/components/agent-run-panel.tsx` | UI-001 | subagent_parallel | subagent | 依赖 `UI-001`；新增独立组件文件 | 可以渲染 `plan`、`tool_call`、`observation`、`decision`、`final_report` | todo | - | - | - | 适合子 Agent。 |
| UI-004 | UI | 在 `AnalyzePage` 中集成 Agent 面板 | `frontend/components/analyze-page.tsx` | UI-002, UI-003 | serial | main | 依赖解析层和新面板组件；不能与其他改 `analyze-page.tsx` 的任务并行 | 页面能同时展示输入、报告和调查过程 | todo | - | - | - | 主 Agent 独占整合任务。 |
| UI-005 | UI | 升级 `analysis-live-panel` 以兼容 Agent 事件分组 | `frontend/components/analysis-live-panel.tsx` | UI-002 | parallel | any | 依赖新事件解析；不能与其他改同文件任务并行 | 旧 Trace 面板不会因新事件破坏显示 | todo | - | - | - | 和 `UI-003` 可并行。 |
| UI-006 | UI | 为 Agent 面板和新状态补充样式 | `frontend/app/globals.css` | UI-003, UI-005 | parallel | subagent | 依赖至少一个新面板完成；不能与其他大规模改 `globals.css` 的任务并行 | 桌面和移动端样式均可用 | todo | - | - | - | 适合子 Agent。 |

## 5.6 TEST：测试与验证

| Task ID | Parent | Task | Write Scope | Depends On | Execution Mode | Recommended Executor | Claim Rule | Exit Criteria | Status | Owner | Claimed At | Updated At | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TEST-001 | TEST | 补充后端配置与 schema 单元测试 | `backend/tests/test_agent_config_and_schema.py` | BASE-002, BASE-003 | parallel | subagent | 依赖基础配置和 schema 完成 | 核心模型和配置新增字段有单测覆盖 | todo | - | - | - | 适合子 Agent。 |
| TEST-002 | TEST | 统一收敛 Tool 层测试缺口 | `backend/tests/test_agent_tool_*.py` | TOOL-001, TOOL-002, TOOL-003, TOOL-004, TOOL-005, TOOL-006, TOOL-007 | subagent_parallel | subagent | 依赖至少对应 Tool 完成；按文件分开认领 | Tool 行为、错误路径和边界情况可回归 | todo | - | - | - | 可继续细分到具体 Tool 测试。 |
| TEST-003 | TEST | 增加 Runner 与 fallback 集成测试 | `backend/tests/test_lightweight_agent_runner.py`, `backend/tests/test_lightweight_agent_pipeline_bridge.py` | RUN-004, RUN-005 | parallel | any | 依赖 Runner 和 Pipeline Bridge 完成 | 主循环、停止条件和 fallback 都有集成测试 | todo | - | - | - | 后端主验证任务。 |
| TEST-004 | TEST | 增加 API 流式事件测试 | `backend/tests/test_api_agent_stream.py` | RUN-006 | parallel | subagent | 依赖新流式事件完成 | 新旧事件流式输出都能通过测试 | todo | - | - | - | 适合子 Agent。 |
| TEST-005 | TEST | 增加前端事件解析和类型契约测试 | `frontend/lib/__tests__/api-client.test.ts`, `frontend/lib/__tests__/report-utils*.test.ts` | UI-001, UI-002 | parallel | subagent | 依赖前端类型和解析层完成 | 解析 Agent 事件时不破坏现有行为 | todo | - | - | - | 适合子 Agent。 |
| TEST-006 | TEST | 增加前端组件渲染与交互测试 | `frontend/components/__tests__/**` 或现有测试目录新增文件 | UI-003, UI-004, UI-005, UI-006 | parallel | subagent | 依赖前端组件和样式集成完成 | 新面板可渲染、切换、回退显示正常 | todo | - | - | - | 适合子 Agent。 |

## 5.7 DOC：文档与演示收口

| Task ID | Parent | Task | Write Scope | Depends On | Execution Mode | Recommended Executor | Claim Rule | Exit Criteria | Status | Owner | Claimed At | Updated At | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DOC-001 | DOC | 更新项目架构说明，补充轻量 Agent 结构 | `docs/current-code-architecture-guide.md`, `docs/question-analysis-end-to-end-flow.md` | RUN-005, RUN-006, UI-004 | parallel | subagent | 依赖核心链路和前端接入完成 | 文档准确描述新架构和主执行链路 | todo | - | - | - | 适合子 Agent。 |
| DOC-002 | DOC | 更新演示脚本，加入 Agent 调查过程口播 | `DEMO_SCRIPT.md` | UI-004, RUN-006 | parallel | subagent | 依赖演示界面和事件流稳定 | 演示脚本能覆盖 Agent 调查路径 | todo | - | - | - | 适合子 Agent。 |
| DOC-003 | DOC | 更新 Smoke Checklist，加入轻量 Agent 验收点 | `SMOKE_CHECKLIST.md` | RUN-005, UI-004, TEST-003, TEST-004 | parallel | subagent | 依赖主流程和关键测试完成 | Smoke 清单可用于轻量 Agent 手工验收 | todo | - | - | - | 适合子 Agent。 |
| DOC-004 | DOC | 按阶段追加实现过程记录和里程碑结论 | `implementation-log/**` | BOARD-001 | parallel | any | 可持续执行；每完成一波任务即更新 | 过程目录持续反映当前真实进度 | ready | - | - | 2026-03-27 20:16 CST | 已解锁；当前文档自身的治理推进也应继续记录在此目录。 |

## 6. 推荐执行顺序

## 6.1 最小安全顺序

最小安全顺序如下：

1. `BOARD-002`
2. `BOARD-003`
3. `BASE-001`、`BASE-002`、`BASE-003`
4. `TOOL-000`
5. `TOOL-001` 到 `TOOL-007`
6. `RUN-001`、`RUN-002`、`RUN-003`
7. `RUN-004`
8. `RUN-005`
9. `RUN-006`
10. `UI-001`、`UI-002`、`UI-003`、`UI-005`
11. `UI-004`
12. `UI-006`
13. `TEST-*`
14. `DOC-*`

## 6.2 推荐并行拆分

如果未来一次性启动多个 Agent，推荐这么拆：

主 Agent：

- `BOARD-002`
- `BOARD-003`
- `BASE-001`
- `BASE-003`
- `TOOL-000`
- `RUN-002`
- `RUN-004`
- `RUN-005`
- `RUN-006`
- `UI-004`

子 Agent 第一批：

- `BASE-002`
- `TOOL-001`
- `TOOL-002`
- `TOOL-003`
- `TOOL-004`
- `TOOL-005`
- `TOOL-006`
- `TOOL-007`

子 Agent 第二批：

- `RUN-001`
- `RUN-003`
- `UI-003`
- `UI-005`
- `TEST-001`
- `TEST-004`
- `DOC-004`

子 Agent 第三批：

- `UI-002`
- `UI-006`
- `TEST-002`
- `TEST-005`
- `TEST-006`
- `DOC-001`
- `DOC-002`
- `DOC-003`

## 6.3 第一波可启动 Agent 清单

如果下一轮准备真正启动多个 Agent，建议第一波只启动下面这些 Agent，并严格按此分工。

| Agent | 建议立即认领的任务 | 是否允许再拆 subagent | 说明 |
| --- | --- | --- | --- |
| `main` | `BASE-001` | 否 | 先把基础目录脚手架建立起来 |
| `backend-1` | `BASE-003` | 否 | schema 属于高冲突文件，独占处理 |
| `backend-2` | `BASE-002` | 否 | 配置和 README 改动与 schema 脱钩 |
| `docs-1` | `DOC-004` | 否 | 只负责跟进过程记录，不改业务代码 |

第一波不建议立即启动前端 Agent。

原因：

- 前端类型任务依赖 `BASE-003` 和 `RUN-006`。
- 现在起前端 Agent 会立即空转。

第一波完成后，第二波再启动：

| Agent | 建议认领的任务 | 说明 |
| --- | --- | --- |
| `main` | `TOOL-000` | 先冻结 Tool 协议 |
| `subagent-backend-tool-01` | `TOOL-001` | `search_news` |
| `subagent-backend-tool-02` | `TOOL-002` | `resolve_question` |
| `subagent-backend-tool-03` | `TOOL-003` | `fetch_url_content` |
| `subagent-backend-tool-04` | `TOOL-004` | `extract_claims` |
| `subagent-backend-tool-05` | `TOOL-005` | `judge_claims` |
| `subagent-backend-tool-06` | `TOOL-006` | `build_timeline` |
| `subagent-backend-tool-07` | `TOOL-007` | `finalize_report` |

## 6.4 不建议并行的关键点

以下任务不建议并行：

- `TOOL-000` 与其他 `TOOL-*`
- `RUN-004` 与 `RUN-005`
- `RUN-006` 与 `UI-001`
- `UI-004` 与其他修改 `analyze-page.tsx` 的任务
- 任何同时修改 `backend/app/models/schemas.py`、`frontend/types/report.ts`、`backend/app/services/analyze_pipeline.py` 的任务

## 7. 任务变更日志

说明：

- 每次认领、开始执行、阻塞、完成，都必须在这里追加一条记录。
- 这是多 Agent 协作时的第二层防冲突机制。

| Time | Agent | Task ID | Action | Notes |
| --- | --- | --- | --- | --- |
| 2026-03-27 20:00 CST | main | BOARD-001 | done | 初始化多 Agent 任务记录规范与执行看板；未认领任何代码实现任务 |
| 2026-03-27 20:10 CST | main | BOARD-002 | done | 已补齐首批保留 Agent ID、子 Agent 命名规则、时间格式和变更日志规范 |
| 2026-03-27 20:16 CST | main | BOARD-003 | done | 已冻结第一轮写入边界和认领顺序，并将 `BASE-*` 与 `DOC-004` 解锁为 `ready` |
| 2026-03-27 20:16 CST | main | BASE-001, BASE-002, BASE-003, DOC-004 | status_sync | 依赖已满足，任务状态统一从 `todo` 更新为 `ready` |
