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
执行时必须先把当前要处理的子任务拆成 3 到 7 个更细步骤，并先把“本轮执行任务 / 执行步骤”写回本文件对应子任务下，再开始写测试或 smoke 文档。
你可以修改测试代码、测试工具、smoke checklist 和测试说明文档，但不要把自己变成主实现窗口；只有在测试暴露出明确问题且为让测试可执行所必需时，才最小化修正实现代码。
完成后必须：
1. 回写本文件中对应子任务的状态，并补充本轮完成记录：改了哪些文件、怎么完成、验证如何、剩余问题是什么。
2. 给出通过/失败结论和残余风险。
3. 说明结果应交给 Cluster-A、C、D 或 G 哪个窗口继续处理。
如果用户要求 [log]，同步更新 prompt-history.md。
```

## 当前实现判断

- 后端测试已经接上 `evals/minimal_v1`，并覆盖了 health、analyze、模式、provider 回退和错误响应等核心 API 路径。
- `F5` 已完成，`backend/tests/test_retrieval.py` 已能基于 `retrieval_cases.json` 回归 mock 检索标准化、去重 canonical、`origin` / `turn` 节点识别和时间线构建。
- 但 `F2 / F3 / F4 / F6 / F7 / F8` 仍未形成按 eval 文件分层的完整验收闭环，因此当前测试仍是“基础可用”，不是“演示前冻结”。

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
状态：已完成
目标：为 `retrieval_cases.json` 建立检索与时间线测试。
产出：retrieval / timeline 测试。
前置依赖：F1、检索模块初版。
子子任务清单：
- 执行检索样例并统计相关结果数。
- 检查高可信来源、origin 候选、turn 候选识别。
- 输出检索与时间线的失败原因。
实现备注：已新增 `backend/tests/test_retrieval.py`，直接消费 `evals/minimal_v1/retrieval_cases.json`，覆盖 mock 检索标准化、去重 canonical、`origin` / `turn` 节点识别与 `timeline_builder` 集成；当前 `pytest backend/tests -q` 通过。真实公开检索 provider 仍待 `D5 ~ D7` 完成后继续扩展。

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
状态：已完成
目标：定义一套演示前必须检查的接口、页面、demo case 和 fallback 检查单。
产出：smoke checklist。
前置依赖：mock 闭环打通。
子子任务清单：
- 列出演示前必须检查的页面和接口。
- 列出必须跑过的 demo case 和失败 case。
- 形成可重复执行的 smoke checklist。
本轮执行任务：基于现有前后端 README、测试样例与 demo 注册表，补一份面向主控或演示者的可执行 smoke checklist，覆盖环境启动、三条 demo、接口检查、失败回退与已知限制确认，并回写当前可通过项与依赖项。
执行步骤：
1. 阅读 F7 相关任务说明与必读文档，确认当前 demo 目标、三档模式和前后端启动方式。
2. 对齐后端 API 测试、retrieval 测试和前端 demo case，提炼可直接输入的 smoke 样例与预期结果。
3. 设计仓库内显眼且可交付的 checklist 文档落点，按顺序组织环境、后端、前端、demo、fallback、限制确认。
4. 视需要补最小命令或脚本入口，确保非开发者能按文档启动、检查和失败处理。
5. 回写 F7 完成记录、验证结论、残余风险及后续交接窗口。
本轮完成记录：
- 新增根目录 `SMOKE_CHECKLIST.md`，按主控 / 演示者执行顺序整理环境、后端、前端、三条 demo、fallback 和已知限制确认。
- 复核 `overview/08_origin_problem_gap_and_demo_strategy.md`、`overview/07_quality-and-demo-baseline.md`、`backend/README.md`、`frontend/README.md`、`frontend/IMPLEMENTATION_SUMMARY.md`、`backend/tests/test_api.py`、`backend/tests/test_retrieval.py`、`frontend/lib/demo-cases.ts`、`rules/origin_problem_statement.md`，把三档模式、输入样例、页面提示和失败处理口径收进 checklist。
- 采用仓库现有 `frontend/start-local-windows.ps1` 作为 Windows / `\\wsl.localhost` 环境下的推荐前端启动入口，没有新增业务脚本。
- 为验证 checklist 尝试执行 `pytest backend/tests/test_api.py -q` 与 `pytest backend/tests/test_retrieval.py -q`；两项都在应用导入阶段失败，暴露出 retrieval 侧实现版本漂移，本轮未继续扩改该链路，避免越界进入主实现窗口。
验证情况：
- checklist 文档：已产出，可直接交给非开发者照着执行。
- 三条 demo 与 fallback 预期：已依据前端代码、demo payload 和测试样例逐项对齐。
- 后端自动 smoke：未通过，当前被 retrieval 侧导入错误阻断。
通过/失败结论：
- `F7` 交付物通过，smoke checklist 已形成。
- 当前仓库“真实后端 smoke 可通过”结论未通过，仍需依赖 `Cluster-D / D5 ~ D7` 收口后复跑。
残余风险：
- `C10` 未完成，URL 输入仍是保守 fallback，不能把 URL 正文抽取讲成已完成能力。
- `D5 ~ D7` 相关 retrieval 文件当前存在接口版本漂移，已直接阻断后端导入与自动化 smoke。
- `G5 / G6` 尚未最终收口，因此 checklist 还没有同步并入最终口播脚本和 README。
建议交接窗口：
- `Cluster-D`：先统一 retrieval 相关实现与测试接口，恢复后端可启动和回归可跑。
- `Cluster-C`：在 retrieval 修复后复跑 `health / analyze` 主链路，确认三档模式没被回归破坏。
- `Cluster-G`：把 `SMOKE_CHECKLIST.md` 纳入最终 demo 口播脚本与 README。
实现备注：此前缺少独立 smoke checklist 文档；本轮已补齐文档，但真实后端 smoke 仍受 retrieval 侧未收口影响。
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



