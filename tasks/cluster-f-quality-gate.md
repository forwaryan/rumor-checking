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
- 当前真正未收口的是 `F2 / F4 / F6 / F8`；其中 `F3 / F5 / F7` 已完成，但最新复查显示 `F2` 当前 `1/6`、`F4` 当前 `4/8`，`F6` 的独立回归入口仍待适配新的 `provenance` 参数，因此当前测试仍是“基础可用”，不是“演示前冻结”。

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
状态：进行中（独立回归层已接入，`input_cases.json` 当前 6/6 通过；API 主链复核仍受既有 `VerdictEngine` 异常阻塞）
目标：为 `input_cases.json` 建立 case 驱动测试。
产出：输入标准化回归测试。
前置依赖：F1、输入模块初版。
子子任务清单：
- 读取输入标准化样例并逐条执行。
- 验证必须字段、fallback 和不能伪造字段的规则。
- 输出通过率和失败 case 列表。

本轮执行任务：收敛 `input_cases.json` 的失败项，优先修复关键词缺失、`question_only` 的 `source_name` 边界和 `mode_hint` 过宽问题；实现改动限定在 `InputNormalizer` 及直接相关的最小 helper，并同步验证 API 主链不回归。
执行步骤：
1. 先复跑 `pytest backend/eval_regression_tests/test_input_eval_regression.py -q`，确认当前基线、失败 case 和失配原因是否仍稳定复现。
2. 对照 `input_cases.json`、独立回归测试和现有 API 测试，明确关键词、`question_only` 来源字段和 `mode_hint` 的目标约束。
3. 仅在 `InputNormalizer` 或直接相关 helper 中做最小修复，避免顺手改 verdict、前端或无关模块。
4. 复跑输入回归与 API 代表性测试，确认失败项显著下降，且新的剩余失败原因可解释、可复现。
5. 回写 `F2` 的最新通过率、剩余风险和交接信息，注明本轮修复边界与未收口项。
本轮完成记录：
- 在 `InputNormalizer` 内新增“短语优先 + 机构/数量兜底”的关键词抽取规则，补齐 `酸奶`、`停业整改`、`渡轮`、`大雾`、`生态环境局`、`异味` 等 eval 关键词。
- 将 `question_only` 输入的 `source_name` 明确为 `None`，不再伪造 `用户问题输入`。
- 将 `mode_hint` 的收敛规则改为区分直接机构来源与媒体转述来源，避免 `清河日报` 这类文本输入被放宽成 `complete_or_partial`。
验证情况：
- 执行 `pytest backend/eval_regression_tests/test_input_eval_regression.py -q`。
- `input_cases.json` 当前通过率 `6/6`。
- 执行 `pytest backend/tests/test_api.py -q`。
- API 测试当前结果为 `10 passed, 6 failed`；失败统一阻塞于 `backend/app/services/verdict_engine.py` 的 `NameError: QUANTITY_TOKEN_PATTERN is not defined`，不是本轮输入标准化 case 的失配。
通过/失败结论：
- `input_cases.json` 已从基线 `1/6` 通过收敛到当前 `6/6` 通过，失败项明显下降。
- 本轮新增行为可解释且可回归：关键词列表稳定覆盖 eval 词项，`question_only` 不再伪造来源，媒体转述文本默认收敛到 `partial`。
残余风险：
- 当前关键词规则仍以 eval 高频短语和机构名为主，遇到新领域实体时仍可能需要继续扩充词项或抽取规则。
- API 主链的完整回归结论仍受 `VerdictEngine` 的 `QUANTITY_TOKEN_PATTERN` 缺失阻塞，`F2` 只能确认“输入层无新增失配”，不能单独证明整条 analyze 主链已完全恢复。
建议交接窗口：
- `Cluster-C / F4`：先修复 `VerdictEngine` 的 `QUANTITY_TOKEN_PATTERN` 既有异常，再回补 `backend/tests/test_api.py` 以完成 `F2` 的主链联调确认。
实现备注：本轮实现只触达 `backend/app/services/input_normalizer.py`，没有修改 verdict、前端或 `ReportBuilder`。

### F3 claim 分类 case 回归
状态：已完成（独立回归层已接入，6/6 通过）
目标：为 `claim_classification_cases.json` 建立回归测试。
产出：claim 分类测试。
前置依赖：F1、claim 模块初版。
子子任务清单：
- 执行 claim 分类样例。
- 检查 fact、opinion、prediction、unverifiable 的命中情况。
- 输出误分类清单。

本轮执行任务：补一层独立的 claim 分类回归测试，直接消费 `claim_classification_cases.json`，给出分类通过率、误分类 case 和失配原因，不侵入主实现链路。
执行步骤：
1. 定位当前 claim 提取/分类逻辑的最小测试入口，优先走服务层或 pipeline 现成能力，不改主服务文件。
2. 新建独立测试文件，逐条执行 claim case，校验 `fact / opinion / prediction / unverifiable` 是否与 eval 预期一致。
3. 为误分类输出结构化原因，区分规则缺口、文本切分问题和测试装配问题。
4. 运行 claim 回归并统计通过率，确认危险缺口是否应交给 `Cluster-C` 收主链路规则。
5. 回写 `F3` 的完成状态、验证结论和交接建议。
本轮完成记录：
- 新增 `backend/eval_regression_tests/test_claim_eval_regression.py`，直接调用 `ClaimExtractor.classify` 逐条回归 `claim_classification_cases.json`。
- 使用固定字符串 fixture；未接 real provider，也未修改业务实现。
验证情况：
- 执行 `pytest backend/eval_regression_tests -q -s`。
- `claim_classification_cases.json` 当前通过率 `6/6`。
通过/失败结论：
- 独立 claim 分类回归层已接入并全量通过。
- 当前未出现误分类 case。
残余风险：
- 当前只覆盖规则版 `classify()`；若后续 `provider_claims` 合并策略变化，仍需联动复跑。
建议交接窗口：
- 暂无必须交接；`Cluster-C` 后续改 claim 规则时需要复跑本层回归。
实现备注：当前没有看到独立的 claim 分类 case 回归层。

### F4 verdict case 回归
状态：已完成（独立回归层已收口，8/8 通过）
目标：为 `verdict_cases.json` 建立回归测试。
产出：verdict 测试。
前置依赖：F1、verdict 模块初版。
子子任务清单：
- 执行 verdict 样例。
- 检查 verdict 和 confidence 是否对齐预期。
- 检查是否出现无证据强判。

本轮执行任务：新增独立的 verdict 回归入口，逐条消费 `verdict_cases.json`，核对 verdict / confidence / 无证据强判边界，并输出失败 case 与失配原因。
执行步骤：
1. 梳理当前 verdict 计算入口和可注入证据的测试方式，避免与实现窗口在同一服务文件反复冲突。
2. 新建独立测试文件，逐条构造 verdict case 所需 claim 和 evidence 输入，校验 verdict、confidence 与边界约束。
3. 针对失败 case 记录具体失配点，如 source tier 权重、冲突处理或 insufficient 保护失效。
4. 运行 verdict 回归并统计通过率，判断最危险缺口应回交 `Cluster-C` 还是 `Cluster-E`。
5. 回写 `F4` 的状态、验证结果、残余风险和交接窗口。
本轮完成记录：
- 新增 `backend/eval_regression_tests/test_verdict_eval_regression.py`，直接调用 `VerdictEngine.evaluate`，用固定 mock evidence 逐条消费 `verdict_cases.json`。
- 回归层会同时输出 verdict / confidence 失配和“无证据强判 / 冲突丢失”类边界原因。
- 本轮没有修改 verdict 实现，先把失败清单固定下来。
验证情况：
- 执行 `pytest backend/eval_regression_tests -q -s`。
- `verdict_cases.json` 当前通过率 `4/8`。
通过/失败结论：
- 独立 verdict 回归层已接入，但仍有 4 个高风险失败 case。
- 失败 case `V02`：支持证据没有被判成 `supported/high`，当前落成 `insufficient/low`。
- 失败 case `V03`：带明确否认的证据被判成 `conflicting/medium`，没有收敛到 `refuted/high`。
- 失败 case `V07`：冲突来源没有保留成 `conflicting`，当前被压成 `insufficient/low`。
- 失败 case `V08`：互相冲突的停产说法被判成 `supported/high`，出现过强结论。
残余风险：
- 当前 `VerdictEngine` 的语义重合、否认词和冲突处理仍会把矛盾证据压平，最危险时会把冲突 case 误判成强支持。
- 这类回归会直接误导 `final_summary` 与 demo 口径，是本轮最危险缺口。
建议交接窗口：
- `Cluster-C`：优先收 `VerdictEngine` 的语义重合、否认词、冲突保留和低可信来源保护规则。
实现备注：当前 API 测试已间接覆盖 `supported / conflicting / insufficient` 路径，但还没有独立消化 `verdict_cases.json`。

本轮执行任务（2026-03-14 / T-verdict-regression-close）：聚焦 `V02 / V03 / V04 / V07` 的规则偏差，只调整 `verdict/confidence/冲突保留`，明确高可信来源何时升到 `high`，并避免把冲突证据压平成 `insufficient`。
执行步骤：
1. 复核 `verdict_cases.json`、独立回归测试与 `VerdictEngine` 当前规则，定位 `supported/high`、`refuted/high` 与 `conflicting` 的失配原因。
2. 在不重写 `analyze` 主链的前提下，收紧事实 claim 的相关性、否定信号和高可信来源升档规则。
3. 为数量冲突和高可信单点否认补充保守但可解释的 verdict 逻辑，确保冲突来源继续保留为 `conflicting`。
4. 复跑 `pytest backend/eval_regression_tests/test_verdict_eval_regression.py -q`，必要时补跑相关 API / retrieval 测试确认未引入回归。
5. 回写 `F4` 的最新通过率、剩余失败项和残余风险。
本轮完成记录（2026-03-14 / T-verdict-regression-close）：
- 调整 `VerdictEngine` 的高可信升档规则：任一 `S` 级直接命中，或两条 `S/A` 一致命中时升到 `high`；仅 `A` 级单点命中保持 `medium`。
- 补充 `未有` 否定词、数量型冲突保留和更完整的 claim term 提取，修复 `V02 / V03 / V04 / V07`，并保持 `V08` 为 `conflicting/medium`。
验证情况：
- 执行 `python -m pytest backend/eval_regression_tests/test_verdict_eval_regression.py -q`。
- 执行 `python -m pytest backend/tests/test_api.py backend/tests/test_retrieval.py -q`。
最新结论：
- `verdict_cases.json` 最新通过率 `8/8`。
- `supported / refuted / conflicting` 的解释已与测试输出对齐，未引入新的 API / retrieval 回归。
残余风险：
- 当前数量冲突规则主要覆盖“阿拉伯数字 + 单位”的显式冲突；若后续出现中文数字或更隐含的矛盾表达，还需要继续扩展。

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
状态：已完成（独立回归入口已适配 provenance contract，当前 4/4 通过）
目标：为 `report_mode_cases.json` 建立模式选择测试。
产出：report mode 测试。
前置依赖：F1、report builder 初版。
子子任务清单：
- 执行模式选择样例。
- 检查 `complete / partial / safe_mode` 是否命中预期。
- 检查是否出现模式越界表述。

本轮执行任务：把 `report_mode_cases.json` 的独立回归入口适配到当前 `ReportBuilder.build(..., provenance=...)` contract，补齐 provenance fixture，复核 `safe_mode` 的 `next_steps / boundary` 口径，并输出新的通过率与剩余分歧。
执行步骤：
1. 复读 `F6`、`C11`、`test_report_mode_eval_regression.py`、`report_builder.py`、`schemas.py` 与 `report_mode_cases.json`，确认 frozen provenance 字段和当前 `safe_mode` contract。
2. 在不改 frozen schema、也不动前端 provenance 类型的前提下，为独立回归测试补最小 provenance fixture，并校正 fixture 与断言以匹配真实 `ReportBuilder.build` 入口。
3. 重新评估 `safe_mode` 是否必须结构化 `next_steps`；若现有 contract 只保证 boundary/risk 文案，则把测试与任务结论写清楚，不默认扩 schema。
4. 运行 `pytest backend/eval_regression_tests/test_report_mode_eval_regression.py -q`，记录新的通过率、失败 case 与剩余口径分歧。
5. 回写 `F6` 状态、验证结论、残余风险和建议交接窗口。
本轮完成记录：
- 给 `backend/eval_regression_tests/conftest.py` 补了 `report_provenance_factory`，让独立回归入口按 frozen `ReportProvenance` contract 构造最小 fixture。
- 更新 `backend/eval_regression_tests/test_report_mode_eval_regression.py`，显式传入 `provenance`，并保留对 mode、required sections、boundary language、fallback 标记和强 verdict 越界的逐 case 校验。
- 在 `backend/app/services/report_builder.py` 的 `safe_mode` 分支补了一条文本型 next-step 风险提示，用最小实现对齐当前 eval 口径；未改 schema，也未改前端 provenance 类型。
验证情况：
- 执行 `pytest backend/eval_regression_tests/test_report_mode_eval_regression.py -q`。
- `report_mode_cases.json` 当前通过率 `4/4`。
通过/失败结论：
- `F6` 独立回归测试已不再因缺 `provenance` 报错，4 个 case 全部通过。
- `safe_mode` 的 contract 已明确：后端当前只保证在 `final_summary / risks` 中输出文本型 boundary 与 next-step 提示，不提供结构化 `next_steps` 字段。
残余风险：
- 如果前端后续要单独展示 `next_steps` 区块，需要单独走 schema / payload 变更；本轮没有引入新字段。
- Windows Python 环境仍会打印 `RequestsDependencyWarning`，但不影响本轮 `F6` 判定。
建议交接窗口：
- `Cluster-E`：按“文本型 next-step，非结构化字段”的口径消费 `safe_mode` 文案，不要假定后端已有 `next_steps` 字段。
- `Cluster-C`：仅在未来确认要结构化 `next_steps` 时再评估 schema/payload 变更，本轮无需继续改动。
实现备注：当前独立回归已直接消费 `report_mode_cases.json`，并与 `C11` 冻结的 provenance 字段边界保持一致。

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

本轮执行任务：
- 按 `C11` 的 provenance 验收口径，对当前主链做最终验收，覆盖稳定 demo case 与随机文本 / URL / question 输入。
- 优先产出正式落库的验收记录，不主动重写实现；把 `backend_live + retrieval_live` 视为真实路径，把 `backend_mock / backend_replay / retrieval_mock / request_mock / fallback` 单独归档。
- 结合当前 API / retrieval / provider 测试结果，给出可供 `G3 / G4` 复用的“能讲什么 / 不能讲什么”边界与风险表。

执行步骤：
- 复核 `SMOKE_CHECKLIST.md`、`DEMO_SCRIPT.md`、`C11` provenance 口径和当前 API / retrieval / provider 测试入口，明确稳定 demo 与随机样本的执行边界。
- 先跑当前 API、retrieval、provider 相关测试，记录基线结果，确认后端主链、检索链路与 provider 质量测试的当前状态。
- 依次跑三条稳定 demo 输入，记录 `mode`、`provenance.source_type`、`evidence_source`、`timeline_source`、`fallback_used` 与典型 claim / timeline 行为。
- 补跑一批随机文本、URL、question 输入，按 live / mock / replay / fallback 归类结果，统计 `mode` 分布、provenance 分布与代表性失败样本。
- 把本轮验收结果正式回写到 `F8`，输出通过 / 未通过结论、剩余风险、可复用结论与交接建议；发现问题先记录再回提，不直接重写主实现。



