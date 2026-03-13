# V1 架构方案与任务看板

## 1. 这份文档解决什么问题

这份文档不是重复需求分析，而是把当前仓库已经完成的 V1 边界、规则和测试样例，翻译成一份可以直接按 task 执行的实现方案。

它解决 4 个问题：

1. V1 代码层面到底怎么拆前后端和共享模块
2. 先做哪些，后做哪些，哪些必须 mock 先行
3. 每个 task 的完成标准是什么
4. 后续每完成一个目标，任务状态应该怎么更新

一句话定义：

> **先用 mock 与最小测试集跑通“输入 -> claim/verdict -> 报告 -> 单页展示”的闭环，再逐步接入真实 URL 抽取、真实检索和缓存能力。**

## 2. 推荐技术方案

## 2.1 总体建议

推荐采用：

- 前端：`Next.js + TypeScript`
- 后端：`FastAPI + Pydantic`
- LLM 接入：`Kimi API`
- 缓存与 demo 数据：`SQLite + 本地 JSON`
- 评测：后端用 `pytest`，前端做最小交互 smoke test

## 2.2 为什么这样选

### 选择 `FastAPI`

- 当前 V1 的核心难点在输入抽取、规则化 verdict、检索与降级，这些更适合放在 Python 服务中实现
- URL 抽取、文本清洗、评测脚本、本地 JSON case 驱动都更偏 Python 生态
- `Pydantic` 适合把 `Event / ClaimResult / TimelineNode / Report` 固定成强 schema

### 选择 `Next.js`

- V1 明确是 Web Demo，而不是 CLI
- 单页展示时间线、claim 表、证据列表时，React 组件化会比模板页更容易维护
- 后续如果需要演示 loading / partial / safe_mode，多状态页面更容易表达

### 不优先选“全栈单语言”

- 当前项目最不确定的是后端链路，不是页面壳子
- 如果一开始把所有问题都压到一个技术栈里，会让输入抽取、检索和评测工具选型变窄
- 先把“前端展示”和“后端核查流水线”解耦，更符合当前 V1 的风险控制方式

## 2.3 V1 非目标

V1 不做：

- 多页后台系统
- 多用户体系
- 实时任务队列
- 向量数据库
- 社交媒体全量传播图
- 多模型路由平台

## 3. 系统边界与实现原则

## 3.1 V1 主链路

```text
用户输入 -> 输入标准化 -> 事件理解 -> claim 抽取/分类
         -> 证据组织 -> verdict 生成 -> 时间线构建
         -> 报告组装 -> Web 单页展示
```

## 3.2 三条硬原则

1. 没有证据，不输出 `supported / refuted`
2. URL 输入始终是增强能力，文本输入必须先稳定
3. 先做 mock 可跑闭环，再接真实外部能力

## 3.3 模式切换原则

- `complete_mode`
  - 输入、claim、evidence、timeline 都基本可用
- `partial_mode`
  - 主链路部分成功，但证据或时间线不完整
- `safe_mode`
  - 关键链路失败，或证据不足，只能输出边界化结果

## 4. 推荐目录结构

```text
frontend/
  app/
  components/
  lib/
  types/

backend/
  app/
    api/
    core/
    models/
    services/
    providers/
    repositories/
  tests/

contracts/
  report.schema.json
  event.schema.json
  claim_result.schema.json
  timeline_node.schema.json
  demo_payloads/

data/
  evals/
  cache/
  demos/
```

## 4.1 目录职责

- `frontend/`
  - 页面、组件、状态切换、请求调用
- `backend/`
  - 核查流水线、providers、缓存、API
- `contracts/`
  - 前后端共享的数据协议和示例 payload
- `data/evals/`
  - 复制或软链接当前 `evals/minimal_v1` 的开发期样例
- `data/cache/`
  - URL 抽取结果、检索结果、demo case 缓存

## 5. 前后端模块方案

## 5.1 后端模块

### `input_normalizer`

职责：

- 识别输入类型：`text_news / url_news / url_unknown / question_only`
- 做正文清洗与事件摘要前的结构化预处理
- 在 URL 抽取失败时给出 fallback 信息

输入：

- 原始文本或 URL

输出：

- `EventDraft`

### `claim_extractor`

职责：

- 从事件正文或摘要中抽取 3 到 5 条 claim
- 对 claim 做 `fact / opinion / prediction / unverifiable` 分类

输入：

- `EventDraft`

输出：

- `ClaimDraft[]`

### `retriever`

职责：

- 根据事件和 claim 生成 query
- 调用 mock 检索或真实检索 provider
- 标准化搜索结果

输入：

- `EventDraft`
- `ClaimDraft[]`

输出：

- `SearchResult[]`

### `verdict_engine`

职责：

- 基于 rules 选择 evidence
- 生成 `supported / refuted / insufficient / conflicting`
- 输出 `confidence`

输入：

- `ClaimDraft`
- `Evidence[]`

输出：

- `ClaimResult`

### `timeline_builder`

职责：

- 对检索结果去重归并
- 识别 `origin / amplification / peak / turn / clarification`
- 构造时间线节点

输入：

- `SearchResult[]`

输出：

- `TimelineNode[]`

### `report_builder`

职责：

- 决定 `complete_mode / partial_mode / safe_mode`
- 聚合事件、时间线、claim 结果、证据和风险提示

输入：

- `Event`
- `ClaimResult[]`
- `TimelineNode[]`

输出：

- `Report`

## 5.2 前端模块

### 页面层

- `AnalyzePage`
  - 单页容器，调度提交、轮询和渲染

### 组件层

- `InputPanel`
  - 文本 / URL 输入、示例 case 快捷填充
- `StatusBanner`
  - `loading / partial / safe_mode / error`
- `EventCard`
  - 事件概览与一句话结论
- `TimelinePanel`
  - 时间线展示
- `ClaimTable`
  - claim 分类、verdict、confidence
- `EvidenceList`
  - 证据来源列表
- `RiskPanel`
  - 边界提示、风险说明、下一步建议

### 前端状态

- `idle`
- `submitting`
- `complete`
- `partial`
- `safe_mode`
- `error`

## 5.3 共享协议

后端作为协议源头，前端消费稳定 schema。

V1 必须先冻结 4 个对象：

### `Event`

- `title`
- `summary`
- `source_url`
- `source_name`
- `published_at`
- `keywords`
- `mode`

### `TimelineNode`

- `node_type`
- `title`
- `url`
- `source_name`
- `published_at`
- `summary`
- `why_selected`

### `ClaimResult`

- `claim`
- `claim_type`
- `verdict`
- `confidence`
- `evidence[]`
- `notes`

### `Report`

- `mode`
- `event`
- `timeline[]`
- `claim_results[]`
- `final_summary`
- `risks[]`
- `sources[]`

## 6. API 方案

## 6.1 第一批接口

### `POST /api/v1/analyze`

用途：

- 提交一条文本、URL 或问题输入

请求体：

```json
{
  "input": "原始输入",
  "input_type": "auto",
  "use_demo_case": false
}
```

返回：

- `Report`

### `GET /api/v1/health`

用途：

- 健康检查

### `GET /api/v1/demo-cases`

用途：

- 前端读取 3 到 5 条稳定 demo case

### `POST /api/v1/replay`

用途：

- 基于本地 demo/cache 直接回放报告，保证演示稳定

## 6.2 第二批内部调试接口

仅开发期需要：

- `POST /api/v1/debug/input-normalize`
- `POST /api/v1/debug/claims`
- `POST /api/v1/debug/verdict`
- `POST /api/v1/debug/timeline`

这些接口的目的是让我们在集成前先验证单模块，而不是长期暴露给最终用户。

## 7. 实施阶段拆分

## 7.1 里程碑

### `M0` 方案冻结

目标：

- 技术方案确认
- 目录结构确认
- task board 建立

### `M1` Mock 闭环

目标：

- 不接真实外部能力
- 用最小测试集与 demo 数据跑通完整页面

### `M2` 文本输入真实链路

目标：

- 文本输入可稳定生成真实 `Report`
- claim/verdict 规则可用

### `M3` URL 与检索增强

目标：

- URL 抽取接入
- 真实检索与时间线增强
- 缓存与 replay 生效

### `M4` 演示就绪

目标：

- 3 个稳定 demo case
- 文档、README、运行说明、回归记录齐备

## 7.2 Task 状态定义

统一只用 4 种状态：

- `todo`
- `doing`
- `blocked`
- `done`

## 7.3 Task Board

| ID | 层级 | 任务 | 依赖 | 完成标准 | 状态 |
| --- | --- | --- | --- | --- | --- |
| T00 | Main | 冻结技术方案与目录结构 | 无 | 本文档确定为当前执行基线 | `todo` |
| T01 | Backend | 建立 FastAPI 基础骨架、配置、日志、错误处理 | T00 | 后端服务可启动并通过 health check | `todo` |
| T02 | Frontend | 建立 Next.js 单页骨架与基础样式 | T00 | 页面可运行并具备空态布局 | `todo` |
| T03 | Contracts | 定义 `Event / TimelineNode / ClaimResult / Report` schema | T00 | 前后端都能引用同一版协议定义 | `todo` |
| T04 | Data | 整理 `evals/minimal_v1` 到开发可消费的位置 | T00 | 后端测试可直接读取 case 文件 | `todo` |
| T05 | Backend | 实现 `input_normalizer` mock 版 | T01,T03,T04 | `input_cases.json` 通过线达标 | `todo` |
| T06 | Backend | 实现 `claim_extractor` 与 claim 分类 mock 版 | T01,T03,T04 | `claim_classification_cases.json` 通过线达标 | `todo` |
| T07 | Backend | 实现 `verdict_engine` mock 版 | T01,T03,T04 | `verdict_cases.json` 通过线达标 | `todo` |
| T08 | Backend | 实现 `retriever` mock 版与结果标准化 | T01,T03,T04 | `retrieval_cases.json` 可转为统一结果结构 | `todo` |
| T09 | Backend | 实现 `timeline_builder` mock 版 | T08,T03,T04 | 能识别 origin 与 turn 候选 | `todo` |
| T10 | Backend | 实现 `report_builder` 与 mode 选择 | T05,T06,T07,T09,T03,T04 | `report_mode_cases.json` 全部命中预期模式 | `todo` |
| T11 | Backend | 实现 `POST /api/v1/analyze` 编排接口 | T05,T06,T07,T09,T10 | 通过一个 mock 输入返回完整 `Report` | `todo` |
| T12 | Frontend | 实现 `InputPanel + StatusBanner` | T02,T11 | 可提交输入并展示 loading/error 状态 | `todo` |
| T13 | Frontend | 实现 `EventCard + RiskPanel` | T02,T11 | 可渲染事件概览、结论和风险提示 | `todo` |
| T14 | Frontend | 实现 `TimelinePanel` | T02,T11 | 可渲染完整与部分时间线 | `todo` |
| T15 | Frontend | 实现 `ClaimTable + EvidenceList` | T02,T11 | 可渲染 claim、verdict、evidence | `todo` |
| T16 | Frontend | 联通三档模式页面 | T12,T13,T14,T15 | `complete / partial / safe_mode` 都有明确 UI | `todo` |
| T17 | Test | 建立后端 pytest 与 case 驱动回归 | T05,T06,T07,T09,T10 | 5 组最小 case 都能自动执行 | `todo` |
| T18 | Demo | 接入本地 demo case 与 replay | T11,T16 | 可一键回放稳定示例 | `todo` |
| T19 | Backend | 接入真实 Kimi provider（文本输入优先） | T11,T17 | 文本输入可走真实模型链路 | `todo` |
| T20 | Backend | 接入 URL 抽取与 fallback | T19,T17 | URL 失败时能清晰降级为粘贴正文 | `todo` |
| T21 | Backend | 接入真实检索 provider 与本地缓存 | T19,T17 | 至少支持真实公开来源检索与缓存 | `todo` |
| T22 | Backend | 强化 `timeline_builder` 真实模式 | T21,T09 | 真实检索结果可生成关键时间线 | `todo` |
| T23 | Frontend | 增加 demo 边界说明、空态与失败提示 | T16,T18 | 页面不会伪装成“全成功” | `todo` |
| T24 | Test | 跑随机 case 与 3 个稳定 demo case | T19,T20,T21,T22,T23 | 有通过记录，能支撑演示 | `todo` |
| T25 | Docs | 更新 README、运行方式、已知限制 | T24 | 新人可按 README 跑起项目 | `todo` |
| T26 | Main | 复盘并决定是否进入 V1 演示版冻结 | T24,T25 | 给出 go / no-go 结论 | `todo` |

## 7.4 推荐执行顺序

严格按下面顺序推进：

1. `T00 -> T04`
2. `T05 -> T11`
3. `T12 -> T18`
4. `T17`
5. `T19 -> T23`
6. `T24 -> T26`

换句话说：

- 先把 mock 后端链路跑通
- 再把页面接起来
- 再接真实模型和真实检索
- 最后做演示验证与文档收口

## 8. 前后端任务拆分建议

## 8.1 如果按线程并行

- `T-main`
  - 维护 task board、决定优先级、控制 scope
- `T-impl-api`
  - 后端 schema、pipeline、provider、缓存
- `T-impl-web`
  - 前端页面、组件、交互状态
- `T-test`
  - case 回归、随机样例验证、演示前检查
- `T-doc`
  - README、样例说明、运行指南、答辩口径

## 8.2 如果单线程推进

单线程时不建议前后端来回切太早，最稳的顺序是：

1. 后端 mock 与测试
2. 前端页面骨架
3. 前后端联通
4. 真实 provider
5. 回归与文档

## 9. 每次完成一个目标后，task 怎么更新

每次完成 task，至少同步更新 3 件事：

1. 把本文件对应 task 的状态改成 `done`
2. 在该 task 下补一行完成说明
3. 如果是重要阶段，用 `[Log]` 追加到 `prompt-history.md`

推荐追加格式：

```md
- 完成时间：YYYY-MM-DD HH:mm
- 关键文件：...
- 验证结果：...
- 下一任务：Txx
```

## 10. 当前建议的立即开工点

不要直接写复杂前端，也不要先接真实检索。

当前最应该开始的是：

1. `T00`：确认采用本方案
2. `T01`：起后端骨架
3. `T03`：先把 4 个核心 schema 写成代码
4. `T04`：把最小测试集接进后端测试
5. `T05 ~ T10`：用 mock 先跑完最小闭环

## 11. 当前的 go / no-go 判断

结论是：

> **可以开始写代码，但必须按 task board 推进，且第一阶段只做 mock 驱动的最小闭环，不直接跳进真实外部依赖。**

只要我们按这份任务看板推进，每完成一个 task 就更新状态，这个 V1 就会始终处于可控范围内。
