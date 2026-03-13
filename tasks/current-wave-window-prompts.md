# 当前波次窗口执行 Prompt

更新时间：2026-03-13 23:01（Asia/Shanghai）

这份文档只服务当前一波并行推进，覆盖 4 个窗口：

- `C10`
- `D5 ~ D7`
- `F7`
- `G5 / G6`

使用方式：

1. 给每个窗口分配一个 prompt。
2. 窗口拿到 prompt 后，先阅读对应 task 文件和指定上下文。
3. 窗口必须先把“本轮执行任务 / 执行步骤”写回对应 task 文件，再开始真正修改。
4. 完成后回写任务状态、完成记录、验证结果和交接建议。

## 窗口 1：C10 / URL 正文抽取

建议线程名：`T-impl-api-url`

```text
你现在负责窗口 `T-impl-api-url`，对应 `Cluster-C / API Foundation` 的 `C10`。

你的唯一目标是：完成 URL 正文抽取与 fallback，让系统对 URL 输入不再只有保守占位，而是在可抽取时拿到标题、正文摘要、来源和时间，在失败时仍然清楚降级。

开始前必须先读：
- `tasks/cluster-c-api-foundation.md`，重点看 `C10`
- `backend/docs/api-foundation-implementation-record.md`
- `backend/README.md`
- `backend/app/services/input_normalizer.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/models/schemas.py`
- `backend/app/services/contract_utils.py`
- `backend/tests/test_api.py`
- `rules/failure_handling_rules.md`

开始执行前，必须先在 `tasks/cluster-c-api-foundation.md` 的 `C10` 下补：
- `本轮执行任务`
- `执行步骤`

执行要求：
- 只围绕 `C10` 推进，不去扩真实检索系统，不去改前端页面。
- 优先选轻量、无额外 key、本地可跑的 URL 抽取路线。
- 允许新增后端依赖、辅助模块、配置项和测试，但要保持 fallback 清晰。
- 如果 URL 页面抽取失败，必须继续输出保守结果，而不是让 analyze 直接崩掉。
- 不要破坏当前文本输入、问题输入和现有 demo case 的行为。

本轮至少要完成这些事：
1. 明确 URL 抽取策略和边界：抓什么，不抓什么，失败如何降级。
2. 接入 URL 抽取实现，产出可供 `InputNormalizer` 使用的结构化结果。
3. 把抽取结果接到现有 analyze 主链路里，确保 `title / summary / source_name / published_at` 能被使用。
4. 补测试：至少覆盖 URL 抽取成功、抽取失败、超时/异常 fallback、文本输入不回归。
5. 更新文档：至少同步 `backend/README.md` 或 `backend/docs/api-foundation-implementation-record.md`。

验收标准：
- 对可抽取 URL，`POST /api/v1/analyze` 能返回不再是纯占位的事件信息。
- 对不可抽取或失败 URL，仍然进入保守模式并给出明确风险提示。
- 现有文本/问题输入主链路不回归。
- 至少有一轮可复现验证：接口调用、pytest 或两者都有。

完成后必须回写：
- `tasks/cluster-c-api-foundation.md`
- 必要的后端说明文档
- 如果用户要求 `[log]`，同步更新 `prompt-history.md`

如果你发现需要真实检索或时间线配合，先只把接口边界和需要交给 `Cluster-D` 的点写清楚，不要自己越界去做 `D5 ~ D7`。
```

## 窗口 2：D5 ~ D7 / 真实检索、缓存、真实时间线

建议线程名：`T-impl-retrieval-real`

```text
你现在负责窗口 `T-impl-retrieval-real`，对应 `Cluster-D / Retrieval Lab` 的 `D5 ~ D7`。

你的目标是：把当前基于 mock retrieval 的基础链路，推进成“真实公开来源检索 + 本地缓存 + 更可信时间线构建”的后端能力，并保持当前 analyze 主链路可降级、可解释。

开始前必须先读：
- `tasks/cluster-d-retrieval-lab.md`，重点看 `D5`、`D6`、`D7`
- `backend/app/services/mock_retriever.py`
- `backend/app/services/retrieval_models.py`
- `backend/app/services/timeline_builder.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/tests/test_retrieval.py`
- `evals/minimal_v1/retrieval_cases.json`
- `data/README.md`
- `rules/propagation_chain_rules.md`
- `backend/docs/api-foundation-implementation-record.md`

开始执行前，必须先在 `tasks/cluster-d-retrieval-lab.md` 的 `D5`、`D6`、`D7` 下补：
- `本轮执行任务`
- `执行步骤`

执行要求：
- 只围绕检索、标准化、缓存和时间线推进，不重写前端，不重做主 API 框架。
- 优先选择公开来源、低额外依赖、易演示的检索路线；如果受环境限制，至少把 provider 抽象、缓存、测试夹具和降级逻辑搭完整。
- 必须保留 fallback：真实检索失败时，不要让 analyze 主流程完全不可用。
- 缓存落点优先使用 `data/cache/`，并说明 key、格式和失效策略。
- timeline 不是简单时间排序，必须体现为什么选这些节点。

本轮至少要完成这些事：
1. 落一个真实检索 provider 接口与配置方式，支持超时、失败和标准化输出。
2. 把真实检索结果映射到现有 `SearchResult / RetrievalBundle`，不要发明第二套结构。
3. 为真实检索接本地缓存，支持命中缓存、跳过缓存、失败回退。
4. 强化 `TimelineBuilder`，让真实结果也能产出 `origin / amplification / turn / clarification` 这类关键节点，并保留 `why_selected`。
5. 补测试和说明：至少覆盖 provider 失败回退、缓存基本行为、真实 bundle 时间线选择逻辑。

验收标准：
- 有一条真实检索路径可以跑，不必全场景完美，但必须可配置、可回退。
- `data/cache/` 下的缓存策略清晰，且文档里说得明白。
- timeline 在真实 bundle 下不只是“能出结果”，而是能解释“为什么选这些节点”。
- 当前 mock retrieval 与现有测试不被破坏。

完成后必须回写：
- `tasks/cluster-d-retrieval-lab.md`
- 相关后端文档和数据目录说明
- 如果用户要求 `[log]`，同步更新 `prompt-history.md`

如果执行中发现需要 `Cluster-C` 配合主链路接线，先做最小集成点并把交接边界写明，不要接管 `C10`。
```

## 窗口 3：F7 / 演示前 Smoke Checklist

建议线程名：`T-test-smoke`

```text
你现在负责窗口 `T-test-smoke`，对应 `Cluster-F / Quality Gate` 的 `F7`。

你的目标是：产出一份真正可执行的演示前 smoke checklist，让主控或演示者在复试前能按清单逐项确认“接口、页面、demo、fallback、边界”都处于可演示状态。

开始前必须先读：
- `tasks/cluster-f-quality-gate.md`，重点看 `F7`
- `overview/08_origin_problem_gap_and_demo_strategy.md`
- `overview/07_quality-and-demo-baseline.md`
- `backend/README.md`
- `frontend/README.md`
- `frontend/IMPLEMENTATION_SUMMARY.md`
- `backend/tests/test_api.py`
- `backend/tests/test_retrieval.py`
- `frontend/lib/demo-cases.ts`
- `rules/origin_problem_statement.md`

开始执行前，必须先在 `tasks/cluster-f-quality-gate.md` 的 `F7` 下补：
- `本轮执行任务`
- `执行步骤`

执行要求：
- 这轮重点是“验收清单”，不是大规模补业务实现。
- 允许补少量测试脚本、检查命令、清单文档和说明，但不要把自己变成主实现窗口。
- 清单必须让非开发者也能照着执行，不能只有工程术语。
- 清单必须覆盖 happy path，也要覆盖至少一类 fallback / 失败场景。

本轮至少要完成这些事：
1. 设计 smoke checklist 文档落点，优先放在仓库里显眼、可交付的位置。
2. 把演示前必须检查的内容列成顺序化步骤：环境、后端、前端、三条 demo、接口、fallback、已知限制确认。
3. 给每一项写清“怎么检查、预期看到什么、失败后怎么处理”。
4. 如果需要，补最小命令或脚本入口，但重点仍是 checklist 本身可读、可执行。
5. 回写任务状态和残余风险：哪些项现在能通过，哪些还依赖 `C10`、`D5 ~ D7` 或 `G5 / G6`。

验收标准：
- 至少形成一份可直接照着走的 smoke checklist 文档。
- 文档能让不熟代码的人也知道：先启动什么、打开哪里、输入什么、预期看到什么。
- 覆盖三档模式和至少一个失败 / 降级场景。
- 明确标出当前仍受哪些未完成能力影响。

完成后必须回写：
- `tasks/cluster-f-quality-gate.md`
- 产出的 smoke checklist 文档
- 如果用户要求 `[log]`，同步更新 `prompt-history.md`

如果你在清单执行中发现确定性 bug，可以最小化修复，但必须把“为什么修”写进完成记录，不要顺手扩展功能。
```

## 窗口 4：G5 / G6 / 演示脚本与最终 README 收口

建议线程名：`T-demo-readme`

```text
你现在负责窗口 `T-demo-readme`，对应 `Cluster-G / Demo Ops` 的 `G5` 和 `G6`。

你的目标是：把当前“能跑”的状态整理成“能讲、能演、能交付”的状态，重点完成演示顺序 / 口播提纲，以及顶层 README 的最终收口。

开始前必须先读：
- `tasks/cluster-g-demo-ops.md`，重点看 `G5`、`G6`
- `overview/08_origin_problem_gap_and_demo_strategy.md`
- `README.md`
- `frontend/README.md`
- `backend/README.md`
- `frontend/IMPLEMENTATION_SUMMARY.md`
- `backend/docs/api-foundation-implementation-record.md`
- `overview/06_current_code_implementation.md`
- `overview/07_quality-and-demo-baseline.md`

开始执行前，必须先在 `tasks/cluster-g-demo-ops.md` 的 `G5`、`G6` 下补：
- `本轮执行任务`
- `执行步骤`

执行要求：
- 这轮主要做演示表达和交付收口，不去改后端主链路或前端大块逻辑。
- README 面向的是“第一次进仓库的人”和“面试演示场景”，不能默认读者已经知道 task 体系。
- 演示脚本必须适合 5 到 10 分钟复用，并和当前三条 demo case 对齐。
- 不要过度宣称当前还没完成的能力；边界必须写清楚。

本轮至少要完成这些事：
1. 产出演示顺序与口播提纲，覆盖 `complete / partial / safe_mode` 三段演示。
2. 在文档里写清每个 demo case 的输入、亮点、推荐讲法和不要说过头的地方。
3. 收口顶层 `README.md`，让第一次进项目的人能快速理解：项目是什么、能演示什么、怎么跑、当前限制是什么、该先读哪些文档。
4. 如果 `F7` 的 smoke checklist 已经可用，链接进 README；如果还没完成，先预留衔接位并写明。
5. 回写任务状态和交接建议，说明是否已经足够支撑演示。

验收标准：
- 至少有一份演示脚本 / 口播文档可直接给演示人使用。
- 顶层 README 不再只是工程索引，而是兼顾“项目介绍 + 运行方式 + 演示入口 + 边界说明”。
- 文档语言尽量让非开发背景读者也能理解。
- 不夸大未完成能力。

完成后必须回写：
- `tasks/cluster-g-demo-ops.md`
- 顶层 `README.md`
- 新增的演示脚本文档或交付文档
- 如果用户要求 `[log]`，同步更新 `prompt-history.md`

如果你发现仍缺少验证材料，优先把需求回交给 `Cluster-F`；如果发现仍缺核心能力，回交给 `Cluster-C` 或 `Cluster-D`，不要自己去补主实现。
```

## 当前波次建议分发顺序

1. 先发 `窗口 2 / D5 ~ D7`
2. 再发 `窗口 1 / C10`
3. 同时发 `窗口 3 / F7`
4. 最后发 `窗口 4 / G5 / G6`

如果你要四窗同时开，也可以直接并发；只是 `窗口 4` 最终会消费 `窗口 3` 的 smoke checklist 结果，所以它需要在文档里预留一次回收同步。
