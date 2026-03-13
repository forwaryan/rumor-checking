# Cluster-F / Quality Gate

## 这个子 task 是干什么的

这个工作包负责最小测试集接入、case 驱动回归、阶段验收和演示前检查。

## 为什么要有这个子 task

当前 V1 最大的风险不是“写不出来”，而是“写出来但不稳”。如果没有一个独立的测试与验收工作包，主链路很容易边改边漂，最后没人知道哪些能力真的过线了。

## 为什么这个子 task 可以并行

它主要消费 `evals/minimal_v1` 和后端接口，不需要主导业务实现。测试线程可以在主链路开发过程中同步补测试和记录结果，而不是等实现全部完成后再一次性发现问题。

## 窗口执行 Prompt（全局）

```text
你现在负责 Cluster-F / Quality Gate。
你的目标是把当前“基础可用”的测试状态推进成“按 eval 资产可回归、演示前可验收”的状态，优先处理本文件中“进行中/未完成”的子任务。
请先完整阅读本文件、evals/minimal_v1/、backend/tests/、frontend/lib/__tests__/、backend/README.md、frontend/README.md，再决定本轮具体改动。
执行时必须先把当前要处理的子任务拆成 3 到 7 个更细步骤，再开始写测试或 smoke 文档。
你可以修改测试代码、测试工具、smoke checklist 和测试说明文档，但不要把自己变成主实现窗口；只有在测试暴露出明确问题且为让测试可执行所必需时，才最小化修正实现代码。
完成后必须：
1. 回写本文件中对应子任务的状态和实现备注。
2. 给出通过/失败结论和残余风险。
3. 说明结果应交给 Cluster-A、C、D 或 G 哪个窗口继续处理。
如果用户要求 [log]，同步更新 prompt-history.md。
```

## 当前实现判断

- 后端测试已经接上 `evals/minimal_v1`，并覆盖了 health、analyze、模式、provider 回退和错误响应等核心 API 路径。
- 前端也已补了最小 Vitest 覆盖，用于保护 parser 和展示辅助函数。
- 但 `Cluster-F` 目标里的“按 eval 文件分层的系统性回归”和“演示前 smoke checklist”目前还没有真正完成，因此当前测试是“基础可用”，不是“验收闭环”。

## 详细子任务

### F1 接入最小测试集目录
状态：已完成
目标：把 `evals/minimal_v1` 接到后端测试能够直接消费的位置。
产出：统一的测试数据入口。
前置依赖：无。
子子任务清单：
- 确认测试目录中的样例文件组织方式。
- 让测试代码可直接读取最小 case 数据。
- 补一个统一的 case 加载工具。
实现备注：`backend/tests/conftest.py` 已能直接读取 `evals/minimal_v1/*.json`。

### F2 输入标准化 case 回归
状态：进行中
目标：为 `input_cases.json` 建立 case 驱动测试。
产出：输入标准化回归测试。
前置依赖：F1、输入模块初版。
子子任务清单：
- 读取输入标准化样例并逐条执行。
- 验证必须字段、fallback 和不能伪造字段的规则。
- 输出通过率和失败 case 列表。
实现备注：`backend/tests/test_api.py` 已覆盖代表性输入 case，但还没有把 `input_cases.json` 全量逐条回归成独立测试组。

### F3 claim 分类 case 回归
状态：未完成
目标：为 `claim_classification_cases.json` 建立回归测试。
产出：claim 分类测试。
前置依赖：F1、claim 模块初版。
子子任务清单：
- 执行 claim 分类样例。
- 检查 fact、opinion、prediction、unverifiable 的命中情况。
- 输出误分类清单。
实现备注：当前没有看到独立的 claim 分类 case 回归层。

### F4 verdict case 回归
状态：进行中
目标：为 `verdict_cases.json` 建立回归测试。
产出：verdict 测试。
前置依赖：F1、verdict 模块初版。
子子任务清单：
- 执行 verdict 样例。
- 检查 verdict 和 confidence 是否对齐预期。
- 检查是否出现无证据强判。
实现备注：当前 API 测试已间接覆盖 `supported / conflicting / insufficient` 路径，但还没有独立消化 `verdict_cases.json`。

### F5 retrieval / timeline case 回归
状态：未完成
目标：为 `retrieval_cases.json` 建立检索与时间线测试。
产出：retrieval / timeline 测试。
前置依赖：F1、检索模块初版。
子子任务清单：
- 执行检索样例并统计相关结果数。
- 检查高可信来源、origin 候选、turn 候选识别。
- 输出检索与时间线的失败原因。
实现备注：由于 `Cluster-D` 仍未闭环，这部分回归也还没有真正建立。

### F6 report mode case 回归
状态：进行中
目标：为 `report_mode_cases.json` 建立模式选择测试。
产出：report mode 测试。
前置依赖：F1、report builder 初版。
子子任务清单：
- 执行模式选择样例。
- 检查 `complete / partial / safe_mode` 是否命中预期。
- 检查是否出现模式越界表述。
实现备注：当前通过 API 测试已覆盖几个代表性模式 case，但仍缺独立的 `report_mode_cases.json` 驱动回归。

### F7 建立演示前 smoke checklist
状态：未完成
目标：定义一套演示前必须检查的接口、页面、demo case 和 fallback 检查单。
产出：smoke checklist。
前置依赖：mock 闭环打通。
子子任务清单：
- 列出演示前必须检查的页面和接口。
- 列出必须跑过的 demo case 和失败 case。
- 形成可重复执行的 smoke checklist。
实现备注：当前还没有独立 smoke checklist 文档，这是演示前最大的测试侧缺口。

### F8 跑随机 case 与稳定 demo case
状态：未完成
目标：做最终随机 case 和预设 demo case 的通过记录。
产出：演示前通过结论和风险清单。
前置依赖：真实能力基本接通。
子子任务清单：
- 跑稳定 demo case 并记录结果。
- 跑随机输入样例并记录模式分布。
- 汇总演示前残余风险。
实现备注：当前还没有形成最终通过记录。