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

总看板使用英文状态，cluster 子任务文件使用中文状态；两者必须按下列映射保持一致：

- `todo` = `未完成`
- `doing` = `进行中`
- `blocked` = `阻塞`
- `done` = `已完成`

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

## 8.2 推荐并行分工包

下面不是泛泛的“谁做前端谁做后端”，而是可以直接分发给不同窗口的独立工作包。

每个工作包都尽量满足：

- 改动目录边界清晰
- 依赖关系明确
- 可以单独验收
- 不会在第一天就频繁冲突

### `Cluster-A / Control Tower`

线程名建议：

- `T-main`

职责：

- 冻结目录结构、技术方案和依赖边界
- 维护 task board 状态
- 审核 schema 变更
- 处理跨线程冲突和优先级调整

主任务：

- `T00`
- 审核 `T03`
- 追踪 `T01 ~ T26` 状态
- 执行 `T26`

可直接拆出去的子任务：

- `A1` 确认第一阶段只做 mock 闭环，不提前接真实检索
- `A2` 冻结前后端目录结构和命名
- `A3` 维护 task 状态表与里程碑说明
- `A4` 负责每轮集成验收和 go / no-go 决策

输入：

- 当前方案文档
- 各线程汇报的完成情况

输出：

- 最新 task 状态
- 是否允许进入下一波开发的决策

不应该做：

- 大量改业务代码
- 与其他线程并行改同一个实现文件

### `Cluster-B / Contract Forge`

线程名建议：

- `T-contract`

职责：

- 作为前后端共享协议 owner
- 固定 schema，避免前后端各自漂移

主任务：

- `T03`

可直接拆出去的子任务：

- `B1` 定义 `Event` schema
- `B2` 定义 `TimelineNode` schema
- `B3` 定义 `ClaimResult` schema
- `B4` 定义 `Report` schema
- `B5` 产出 demo payload 示例
- `B6` 给前后端分别提供字段说明和最小示例

输入：

- `rules/`
- `evals/minimal_v1/`
- 当前 V1 蓝图

输出：

- `contracts/` 下的共享 schema
- 前端 mock payload
- 后端响应模型

启动条件：

- `T00` 完成后即可开始

依赖关系：

- 会阻塞 `T05 ~ T16`

不应该做：

- 接真实 provider
- 改前端 UI 组件

### `Cluster-C / API Foundation`

线程名建议：

- `T-impl-api-foundation`

职责：

- 起后端骨架
- 负责 mock 闭环主链路
- 把输入、claim、verdict、report 串起来

主任务：

- `T01`
- `T05`
- `T06`
- `T07`
- `T10`
- `T11`
- `T19`
- `T20`

可直接拆出去的子任务：

- `C1` 初始化 FastAPI 项目结构、配置、日志、中间件
- `C2` 建立统一错误响应和状态码规范
- `C3` 实现 `input_normalizer` mock 版
- `C4` 实现 `claim_extractor` mock 版
- `C5` 实现 `verdict_engine` mock 版
- `C6` 实现 `report_builder` 和 mode 判断
- `C7` 实现 `POST /api/v1/analyze`
- `C8` 接入真实 Kimi provider
- `C9` 实现 URL 抽取和失败 fallback

输入：

- `contracts/` schema
- `evals/minimal_v1` case
- `rules/evidence_and_verdict_rules.md`
- `rules/failure_handling_rules.md`

输出：

- 可运行后端服务
- mock 与真实模式都可用的分析接口

启动条件：

- `T01` 在 `T00` 后即可开始
- `T05 ~ T07` 需要 `T03`、`T04`

依赖关系：

- 会阻塞 `T11` 之后的大多数前端联调

不应该做：

- 负责前端页面细节
- 主导检索和时间线的真实 provider 设计

### `Cluster-D / Retrieval Lab`

线程名建议：

- `T-impl-api-retrieval`

职责：

- 负责检索、结果标准化、去重归并和时间线
- 与主链路后端解耦并行推进

主任务：

- `T08`
- `T09`
- `T21`
- `T22`

可直接拆出去的子任务：

- `D1` 统一 `SearchResult` 与 `Evidence` 结构
- `D2` 实现 mock 检索结果读取与标准化
- `D3` 实现去重归并规则
- `D4` 实现 `origin / turn` 候选识别
- `D5` 接真实公开来源检索 provider
- `D6` 接本地缓存与 replay 支持
- `D7` 强化真实时间线构建逻辑

输入：

- `retrieval_cases.json`
- 传播链规则
- 共享 schema

输出：

- `retriever`
- `timeline_builder`
- 检索缓存层

启动条件：

- `T08` 在 `T03`、`T04` 后可启动
- `T21` 需要 `T19` 基本稳定

依赖关系：

- `T09` 依赖 `T08`
- `T22` 依赖 `T21`
- 结果提供给 `T10`、`T24`

不应该做：

- 修改前端渲染逻辑
- 改写 claim/verdict 规则

### `Cluster-E / Experience Shell`

线程名建议：

- `T-impl-web`

职责：

- 负责单页 Web Demo 的全部用户界面
- 不等待真实后端，先基于 mock `Report` 开发

主任务：

- `T02`
- `T12`
- `T13`
- `T14`
- `T15`
- `T16`
- `T23`

可直接拆出去的子任务：

- `E1` 初始化 Next.js 项目与页面骨架
- `E2` 定义前端类型和 API client
- `E3` 实现输入区与 loading/error 状态
- `E4` 实现事件概览卡片和结论展示
- `E5` 实现时间线视图
- `E6` 实现 claim 表与 evidence 列表
- `E7` 联通 `complete / partial / safe_mode`
- `E8` 增加 demo 边界说明、空态和失败提示

输入：

- `Report` mock payload
- `contracts/` schema
- 后端 API 约定

输出：

- 单页可交互 Demo
- 可消费真实或 mock `Report` 的组件层

启动条件：

- `T02` 在 `T00` 后即可开始
- 组件开发最好在 `T03` 后固定字段

依赖关系：

- `T16` 依赖 `T12 ~ T15`
- `T23` 依赖 `T16`、`T18`

不应该做：

- 自己发明新的响应字段
- 等后端完全做好才开始写页面

### `Cluster-F / Quality Gate`

线程名建议：

- `T-test`

职责：

- 维护最小测试集接入
- 负责 case 回归和阶段验收

主任务：

- `T04`
- `T17`
- `T24`

可直接拆出去的子任务：

- `F1` 把 `evals/minimal_v1` 接到开发目录
- `F2` 为输入标准化写 case 驱动测试
- `F3` 为 claim 分类写 case 驱动测试
- `F4` 为 verdict 写 case 驱动测试
- `F5` 为 retrieval / timeline 写 case 驱动测试
- `F6` 为 report mode 写 case 驱动测试
- `F7` 建立演示前 smoke checklist
- `F8` 跑随机 case 和稳定 demo case

输入：

- `evals/minimal_v1/*.json`
- 后端 API 或服务层实现

输出：

- 回归测试
- 阶段验收结论
- 演示前风险清单

启动条件：

- `T04` 在 `T00` 后即可开始
- `T17` 随 `T05 ~ T10` 同步推进

依赖关系：

- 会反向阻塞 `T19 ~ T26`

不应该做：

- 成为主业务实现 owner
- 与实现线程混合修改大量业务逻辑

### `Cluster-G / Demo Ops`

线程名建议：

- `T-doc-demo`

职责：

- 负责 demo case、回放、README、演示说明
- 让项目在“能跑”和“能演示”之间补齐最后一段距离

主任务：

- `T18`
- `T25`

可直接拆出去的子任务：

- `G1` 整理 3 到 5 条稳定 demo case
- `G2` 设计 replay 数据格式
- `G3` 写运行步骤和环境变量说明
- `G4` 写已知限制和降级边界
- `G5` 写演示顺序和口播要点

输入：

- 后端接口
- 前端页面
- 测试线程的通过结论

输出：

- 本地 demo 回放能力
- 对外 README
- 演示材料口径

启动条件：

- `T18` 在 `T11`、`T16` 后可启动
- `T25` 在 `T24` 后收口

依赖关系：

- 支撑 `T23 ~ T26`

不应该做：

- 修改核心业务规则
- 在没有验证的情况下编造 demo 结果

## 8.3 推荐并行波次

### 波次 1：最适合立即并行

- `Cluster-A / Control Tower`
- `Cluster-B / Contract Forge`
- `Cluster-C / API Foundation` 的 `C1 ~ C2`
- `Cluster-E / Experience Shell` 的 `E1 ~ E2`
- `Cluster-F / Quality Gate` 的 `F1`

目标：

- 不互相阻塞地把项目骨架、schema 和测试入口立起来

### 波次 2：mock 闭环并行

- `Cluster-C / API Foundation` 的 `C3 ~ C7`
- `Cluster-D / Retrieval Lab` 的 `D1 ~ D4`
- `Cluster-E / Experience Shell` 的 `E3 ~ E7`
- `Cluster-F / Quality Gate` 的 `F2 ~ F6`

目标：

- 跑通 mock 版 end-to-end

### 波次 3：真实能力并行

- `Cluster-C / API Foundation` 的 `C8 ~ C9`
- `Cluster-D / Retrieval Lab` 的 `D5 ~ D7`
- `Cluster-E / Experience Shell` 的 `E8`
- `Cluster-F / Quality Gate` 的 `F7 ~ F8`
- `Cluster-G / Demo Ops` 的 `G1 ~ G2`

目标：

- 接真实模型、真实检索、时间线增强和演示回放

### 波次 4：演示收口

- `Cluster-G / Demo Ops` 的 `G3 ~ G5`
- `Cluster-A / Control Tower`
- `Cluster-F / Quality Gate`

目标：

- README、演示 case、最终验收和冻结

## 8.4 如果你的集群数量有限

### 3 个窗口

- `窗口 1`
  - `Cluster-A + Cluster-B`
- `窗口 2`
  - `Cluster-C + Cluster-D`
- `窗口 3`
  - `Cluster-E + Cluster-F + Cluster-G`

### 4 个窗口

- `窗口 1`
  - `Cluster-A + Cluster-B`
- `窗口 2`
  - `Cluster-C`
- `窗口 3`
  - `Cluster-D + Cluster-F`
- `窗口 4`
  - `Cluster-E + Cluster-G`

### 6 到 7 个窗口

- 每个 Cluster 单独一个窗口

这时最稳，不容易互相踩文件。

## 8.5 分工时的硬约束

1. `Cluster-B / Contract Forge` 必须是 schema 唯一 owner
2. `Cluster-A / Control Tower` 负责所有跨线程优先级决策
3. `Cluster-E / Experience Shell` 不等待真实后端，先用 mock payload 开发
4. `Cluster-F / Quality Gate` 尽量不直接改业务实现，只提回归结果和问题
5. `Cluster-G / Demo Ops` 只能消费已验证通过的结果，不自己造数据

## 8.6 如果单线程推进

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


