# Cluster-G / Demo Ops

## 这个子 task 是干什么的

这个工作包负责 demo case、回放能力、README、演示说明和交付口径。

## 为什么要有这个子 task

项目“能跑”不等于“能演示”。如果没有单独的 demo 与文档 owner，最后很容易出现系统勉强能用，但没人能稳定复现、稳定讲解、稳定给别人跑起来。

## 为什么这个子 task 可以并行

它不主导核心业务逻辑，而是消费前后端和测试已经通过的结果做收口。因此它可以在前后端推进时提前整理 demo case 和 README 结构，在后期再完成最终填充。

## 窗口执行 Prompt（全局）

```text
你现在负责 Cluster-G / Demo Ops。
你的目标是把当前“能跑”的状态整理成“能演示、能交付、能让别人复现”的状态，优先处理本文件中“进行中/未完成”的子任务。
请先完整阅读本文件、README.md、frontend/README.md、backend/README.md、frontend/IMPLEMENTATION_SUMMARY.md，以及当前 demo / smoke / tasks 状态说明，再决定本轮具体改动。
执行时必须先把当前要处理的子任务拆成 3 到 7 个更细步骤，并先把“本轮执行任务 / 执行步骤”写回本文件对应子任务下，再开始改文档或演示资产。
你可以修改 README、data/demos/、演示说明、replay 格式说明和交付文档，但不要把自己变成后端实现或前端重构窗口。
完成后必须：
1. 回写本文件中对应子任务的状态，并补充本轮完成记录：改了哪些文件、怎么完成、验证如何、剩余问题是什么。
2. 给出文档/演示资产的落点和使用方式。
3. 说明是否已经足够支撑演示，还是仍需 Cluster-F 或 A 继续收口。
如果用户要求 [log]，同步更新 prompt-history.md。
```

## 当前实现判断

- 当前已经有 3 条稳定 demo case，并且前端本地 payload 与后端 scenario 已基本对齐。
- 前端 README、前端实现总结、后端 README 和后端实现记录都已经存在。
- 顶层 README、`DEMO_SCRIPT.md` 和 `SMOKE_CHECKLIST.md` 已经落地；当前 `Cluster-G` 真正未收口的是把 `F8` 的结论同步到最终文档与演示口径，以及继续推进 `G2` replay 定稿。

## 详细子任务

### G1 整理稳定 demo case
状态：已完成
目标：挑选 3 到 5 条最稳的输入案例，作为展示主案例。
产出：稳定 demo case 列表。
前置依赖：mock 闭环至少打通。
子子任务清单：
- 从最小测试集和现有样例中筛选稳定输入。
- 为每个 demo case 记录预期模式和亮点。
- 确定最终演示优先顺序。
实现备注：当前前端已稳定使用 `expired-yogurt / chemical-odor / morningstar-layoff` 三条 demo。

### G2 设计 replay 数据格式
状态：进行中
目标：定义 demo 回放所需的数据结构和读取方式。
产出：replay 数据格式方案。
前置依赖：schema 和主接口基本稳定。
子子任务清单：
- 定义 replay 文件结构和命名规则。
- 决定是按输入回放还是按完整报告回放。
- 给前后端约定 replay 数据读取方式。
实现备注：已新增 `data/demos/README.md` 和 `data/demos/replays/` 作为第一阶段骨架；当前先冻结文件级 replay 草案，不提前承诺后端 replay 接口。
本轮执行任务：
- 把 `data/demos/` 从空壳目录补成可交接的 replay 落点，明确文件放哪里、命名怎么定、最小字段草案怎么写。
- 只定义文件级 replay bundle 草案，不抢先设计 `POST /api/v1/replay` 或新的前后端消费接口。
- 在 task 和文档里标清楚哪些 replay 字段必须等 `C10 / C11 / F8` 收口后再冻结。
执行步骤：
1. 复核当前 demo 资产、README 和 smoke 文档里已经存在的输入/模式/回退口径，避免 replay 草案与现状打架。
2. 为 `data/demos/` 选定最小目录落点，优先先冻结文件路径和命名规则，而不是先发明接口。
3. 写出单文件 replay bundle 的字段草案和示例，并把“暂不冻结字段”单独列出来。
4. 回写 `G2` 状态和交接建议，说明后续应由谁在 `C10 / C11 / F8` 后补最终字段。
本轮完成记录：
- 修改文件：`tasks/cluster-g-demo-ops.md`、`data/README.md`、`data/demos/README.md`、`README.md`
- 完成方式：把 replay 第一阶段落点收口到 `data/demos/replays/`，并在 `data/demos/README.md` 中定义了命名规则、单文件 replay bundle 草案、暂不冻结字段和后续收口依赖。
- 验证如何：对照现有 `README.md`、`SMOKE_CHECKLIST.md`、`DEMO_SCRIPT.md` 与 `data/README.md` 的目录说明，确认本轮只落结构，不新增伪接口或伪运行说明。
- 剩余问题：`response.provenance`、URL 抽取结果、真实检索命中信息、最终 replay 读取方式仍待 `C10 / C11 / F8` 冻结后再定稿。
交接建议：
- 后续若需要正式 replay 文件，先按 `data/demos/replays/<case_id>--<mode>--<source_tag>--<date>.json` 落库，避免再把样例散落到别的目录。
- `C11` 收口前不要锁死 provenance、fallback 层级和 request-level 调试字段的最终命名。
- `F8` 完成后，再决定哪些 replay 应升级为“正式验收记录”，哪些只保留为演示辅助资产。

### G3 写运行方式与环境变量说明
状态：已完成
目标：说明前后端如何启动、需要哪些环境变量、如何跑 demo。
产出：README 运行说明终稿、运行路径与环境变量文档终稿。
前置依赖：前后端项目已初始化；`F8` 验收记录已落库。
子子任务清单：
- 写清前端启动步骤。
- 写清后端启动步骤和环境变量要求。
- 写清如何跑 demo 和如何使用 replay。
实现备注：已按 `overview/13_f8-random-acceptance.md` 更新 `README.md`、`overview/README.md` 与 `overview/11_runtime-and-env-outline.md`，运行说明不再沿用骨架占位，而是直接区分 `mock demo / live probe / replay / frontend fallback`。
本轮执行任务：
- 基于 `overview/13_f8-random-acceptance.md` 的正式验收结论，重写当前可交付的运行路径，明确区分 `mock demo / live probe / replay / frontend fallback`。
- 把环境变量建议收敛到“默认验收快照 / live probe 专用 / 前端 API 指向”三组，只保留仓库里已经存在的真实变量和启动方式。
- 同步顶层 README、`overview/11_runtime-and-env-outline.md` 与 `overview/README.md` 的入口，让协作者先看到今天能交付哪条路径、不能把哪条路径讲成已验收通过。
执行步骤：
1. 先以 `F8` 验收记录冻结默认环境快照和 live probe 结论，避免继续引用旧波次描述。
2. 对照 README、前后端 README 与 `SMOKE_CHECKLIST.md` 中已存在的启动命令和环境变量，只保留当前真实可跑的路径。
3. 更新顶层 README 与 `overview/11_runtime-and-env-outline.md` 的最终运行说明，明确 replay 仍无公开接口，frontend fallback 只算保底演示。
4. 回写 `G3` 完成记录，标出哪些路径可以交付、哪些只应用于内部诊断。
本轮完成记录：
- 修改文件：`tasks/cluster-g-demo-ops.md`、`README.md`、`overview/README.md`、`overview/11_runtime-and-env-outline.md`、`SMOKE_CHECKLIST.md`、`DEMO_SCRIPT.md`
- 完成方式：以 `F8` 验收记录为唯一运行口径来源，收口为四类路径矩阵：`mock demo`、`live probe`、`replay`、`frontend fallback`；同时补齐默认环境快照、live probe 专用变量和前端 API 指向。
- 验证如何：逐项对照 `overview/13_f8-random-acceptance.md`、`backend/README.md`、`frontend/README.md` 与 `SMOKE_CHECKLIST.md`，确认所有运行说明都明确区分 live / mock / replay / fallback，且没有新增伪接口或伪运行步骤。
- 剩余问题：`live probe` 仍停留在内部诊断阶段，`backend_live + retrieval_live` 的正式通过样本仍待 `Cluster-D` 修复 live retrieval 后重新验收。
交接建议：
- 对外交付默认只讲 `mock demo + provenance 边界`，不要再把默认环境讲成真实检索路径。
- 如果后续要恢复 `live` 口径，必须先有新的正式验收记录，再同步更新 README、Smoke 与口播。
- replay 继续只保留为内部预留能力，除非后端实现公开接口，否则不要新增交付说明。

### G4 写已知限制与降级边界
状态：已完成
目标：把当前 V1 的不做范围、失败模式、fallback 逻辑明确写出来。
产出：README 中的限制说明和边界说明终稿。
前置依赖：真实能力与 fallback 基本确定；`F8` 已给出正式结论。
子子任务清单：
- 列出 V1 不做和弱化的能力。
- 列出 partial/safe 模式的触发场景。
- 列出已知风险和临时规避办法。
实现备注：已按 `F8` 风险表收口 `README.md`、`overview/12_limits-and-degradation-outline.md`、`SMOKE_CHECKLIST.md` 和 `DEMO_SCRIPT.md`，不再沿用“三条稳定 demo 全部通过”的旧口径。
本轮执行任务：
- 基于 `F8` 的“能讲什么 / 不能讲什么”和风险表，冻结当前对外口径，不再保留骨架式占位。
- 明确 `live / mock / replay / fallback` 的判定方式，以及 `complete / partial / safe_mode` 在当前验收状态下分别能怎么讲。
- 同步 README、`overview/12_limits-and-degradation-outline.md` 与 `SMOKE_CHECKLIST.md` 的 go/no-go 结论，移除“三条稳定 demo 已全部通过”的旧口径。
执行步骤：
1. 复核 `F8` 验收记录、README、前后端 README 与 smoke checklist，抽出必须统一的边界结论与失败样本。
2. 更新 `overview/12_limits-and-degradation-outline.md` 与 README 的最终限制说明，明确哪些是 live 能力、哪些只是 mock/demo 或保守降级。
3. 同步 `SMOKE_CHECKLIST.md` 的演示入口、demo 使用建议与 go/no-go 结论，避免继续把漂移样本当作稳定 demo。
4. 回写 `G4` 完成记录，保留仍需 `Cluster-C / D` 处理的残余风险，但不再把 `F8` 已给出的结论写成“待定”。
本轮完成记录：
- 修改文件：`tasks/cluster-g-demo-ops.md`、`README.md`、`overview/12_limits-and-degradation-outline.md`、`SMOKE_CHECKLIST.md`、`DEMO_SCRIPT.md`
- 完成方式：以 `F8` 的“能讲什么 / 不能讲什么”和风险表为准，明确 `live / mock / replay / fallback` 判定、`complete / partial / safe_mode` 讲法，以及当前 `Go / mock demo + 边界`、`No-Go / 真实检索较真` 的 go/no-go 结论。
- 验证如何：对照 `overview/13_f8-random-acceptance.md`、`README.md`、`SMOKE_CHECKLIST.md`、`DEMO_SCRIPT.md` 与前后端 README，确认 `expired-yogurt` 是唯一默认稳定 demo，`chemical-odor` / `morningstar-layoff` 已从默认主线移除。
- 剩余问题：`chemical-odor` 与 `morningstar-layoff` 的模式漂移仍需 `Cluster-C` 复核；`live retrieval` 的 `0/4 real_live` 仍需 `Cluster-D` 处理。
交接建议：
- 所有对外文案继续以 `F8` 验收记录为上限，不要绕过 provenance 或 mode 漂移结果。
- 若后续修复 demo 漂移或 live retrieval，可在新的验收通过后再升级 Smoke 和 Demo Script。
- 当前任何协作者都应先区分 `mock demo` 与 `frontend fallback`，再决定是否需要做内部 `live probe`。
### G5 写演示顺序与口播要点
状态：已完成
目标：整理“先输入什么、再看哪里、怎么解释 partial/safe_mode”的演示脚本。
产出：演示操作顺序和口播提纲。
前置依赖：页面与 demo case 可用。
子子任务清单：
- 设计演示输入顺序和每一步看点。
- 设计 complete、partial、safe 三类口播解释。
- 形成 5 到 10 分钟可复用的演示流程。
实现备注：已新增根目录 `DEMO_SCRIPT.md`，覆盖 5 到 10 分钟演示顺序、三条 demo case 的输入/亮点/推荐讲法，以及不要说过头的边界提醒。
本轮执行任务：
- 基于当时可用的 demo case 整理一份 5 到 10 分钟可复用的演示顺序与口播提纲，并在 `F8` 后同步到当前 `expired-yogurt + provenance / fallback` 主线。
- 在演示文档中写清每个 case 的输入、亮点、推荐讲法，以及不要说过头的边界提醒。
- 同步判断当前材料是否已足够支撑演示，并把需要 `Cluster-F` 或 `Cluster-C / D` 继续补的点写清楚。
执行步骤：
1. 复核现有 demo case、payload 与演示边界文档，确认 `complete / partial / safe_mode` 的真实可讲范围。
2. 设计适合面试场景的演示顺序，明确每一段先看哪里、讲什么、控制在多久。
3. 形成可直接给演示者使用的口播提纲，并补充“亮点 / 边界 / 不要过度宣称”的提醒。
4. 回写 G5 状态、完成记录和交接建议，说明当前演示材料是否还依赖 smoke checklist 或核心能力补强。
本轮完成记录：
- 修改文件：`DEMO_SCRIPT.md`、`README.md`、`tasks/cluster-g-demo-ops.md`
- 完成方式：先基于当时可用的 demo case、前后端 README、实现总结、demo strategy 与 demo payload 整理出演示口播稿，再在 `F8` 后由 `G3 / G4` 同步成当前单条稳定 mock demo + 边界说明版本。
- 验证如何：逐项对照 `frontend/lib/demo-cases.ts`、`contracts/demo_payloads/*.json`、`overview/08_origin_problem_gap_and_demo_strategy.md`、`overview/07_quality-and-demo-baseline.md` 的现有边界口径；本轮未改主实现，也未新增运行命令验证。
- 剩余问题：若要扩展到随机开放输入演示，仍依赖 `Cluster-D` 继续补 live retrieval 稳定性，并由 `Cluster-C` 继续收口模式漂移。
交接建议：
- 当前材料已经足够支撑一场 5 到 10 分钟的稳定演示，优先按 `DEMO_SCRIPT.md` 使用 `expired-yogurt + provenance / fallback` 主线。
- `Cluster-F` 的 smoke checklist 已可直接复用；后续重点转为把 `F8` 的正式结论同步进演示入口。
- 如果需要演示非预设 case，请交由 `Cluster-C / D` 继续补核心能力，不建议由 `Cluster-G` 直接改主实现。

### G6 产出最终 README 收口版
状态：已完成
目标：把运行说明、demo case、限制、架构概览整合成最终 README。
产出：可供别人直接使用的 README。
前置依赖：G1 ~ G5 基本完成。
子子任务清单：
- 汇总运行说明、demo 说明和限制说明。
- 补充架构概览与项目入口链接。
- 输出一版面向评审和协作者都能读懂的 README。
实现备注：顶层 `README.md` 已完成收口，现已同时覆盖项目介绍、演示入口、快速启动、当前限制、文档导航，以及 `F7` smoke checklist 的预留衔接位。
本轮执行任务：
- 重写顶层 `README.md`，让第一次进入仓库的人先理解“项目是什么、能演示什么、怎么跑、当前限制是什么”。
- 把三条 demo case 和演示入口放到 README 主路径，而不是只做工程目录索引。
- 判断 `F7` smoke checklist 是否已有可用文档；若未完成，则在 README 预留衔接位并明确说明当前状态。
执行步骤：
1. 汇总前端、后端、overview 文档里的运行方式、能力边界和推荐阅读路径。
2. 以“项目介绍 + 演示入口 + 快速启动 + 当前限制 + 深入文档”重组顶层 README。
3. 在 README 中加入 demo case 说明、演示文档入口，以及 smoke checklist 的链接或预留位。
4. 回写 G6 状态、完成记录和交接建议，说明 README 是否已经达到演示交付所需的清晰度。
本轮完成记录：
- 修改文件：`README.md`、`DEMO_SCRIPT.md`、`tasks/cluster-g-demo-ops.md`
- 完成方式：重写顶层 README，把项目介绍、演示入口、运行方式、当前限制、推荐阅读路径与 demo / smoke 现状整合到一个第一次进仓库即可理解的入口文档中。
- 验证如何：对照 `frontend/README.md`、`backend/README.md`、`overview/06_current_code_implementation.md`、`overview/07_quality-and-demo-baseline.md`、`overview/08_origin_problem_gap_and_demo_strategy.md` 的现有能力与边界描述，并确认仓库内尚无已完成的独立 `F7` smoke checklist 文档，因此 README 仅预留衔接位而未误链。
- 剩余问题：`G2` replay 仍未定稿，README 仍需继续跟随 `F8` 结论和 live 路径状态同步。
交接建议：
- 当前顶层 README 已经足够作为“第一次进仓库的人”和“面试演示者”的统一入口。
- 继续把 `F8` 的正式验收结论同步到 README、运行说明和边界说明中。
- 待 `G2` 明确 replay 方案后，再补 replay 使用说明；当前不要为了看起来完整而写伪说明。








