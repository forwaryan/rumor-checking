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
- 但顶层 README 仍旧过时，replay 数据和演示脚本没有真正落地，因此 `Cluster-G` 目前属于“资料有了不少，但还没形成最终交付包”。

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
状态：进行中
目标：说明前后端如何启动、需要哪些环境变量、如何跑 demo。
产出：README 运行说明初稿。
前置依赖：前后端项目已初始化。
子子任务清单：
- 写清前端启动步骤。
- 写清后端启动步骤和环境变量要求。
- 写清如何跑 demo 和如何使用 replay。
实现备注：已新增 `overview/11_runtime-and-env-outline.md` 作为第一阶段骨架；顶层 README 先补入口链接，不抢写 `C10 / C11 / F8` 未稳定的最终运行口径。
本轮执行任务：
- 把“怎么跑、环境变量放哪里、怎样做演示前检查”的说明拆成清晰章节骨架，而不是继续堆在顶层 README。
- 明确顶层 README、前端 README、后端 README、Smoke Checklist 在运行说明里的角色边界。
- 把 replay 运行方式先留成占位章节，只说明落点和后续依赖，不伪造尚未落地的使用流程。
执行步骤：
1. 对照顶层 README、前端 README、后端 README 和 smoke checklist，梳理哪些说明已经存在，哪些还只是分散在不同文档里。
2. 设计一份独立的运行与环境变量章节骨架，覆盖启动路径、环境变量矩阵、验证入口和演示路径。
3. 在骨架里标出“当前引用来源”和“最终定稿依赖”，避免后续窗口重复搬运或提前写死结论。
4. 回写 `G3` 状态和交接建议，说明哪些章节能先补，哪些必须等 `C10 / C11 / F8`。
本轮完成记录：
- 修改文件：`tasks/cluster-g-demo-ops.md`、`overview/11_runtime-and-env-outline.md`、`overview/README.md`、`README.md`
- 完成方式：新增运行方式与环境变量的章节骨架文档，拆出“启动路径矩阵 / 环境变量矩阵 / 演示前检查 / replay 运行占位 / 待冻结章节”等明确落点，并在 README 中补了入口链接。
- 验证如何：逐项对照 `README.md`、`backend/README.md`、`frontend/README.md`、`SMOKE_CHECKLIST.md` 现有内容，确认本轮只做结构拆分，不覆盖现有实现说明。
- 剩余问题：URL 输入主路径、真实检索默认建议、provider/retrieval/replay 的最终推荐组合，仍待 `C10 / C11 / F8` 验证后再落最终文案。
交接建议：
- 顶层 README 继续只保留“第一次进仓库先看什么”，不要再把全部运行细节重新复制一遍。
- 后续窗口补运行说明时，优先往 `overview/11_runtime-and-env-outline.md` 的既有章节里填，不再新开平行文档。
- `F8` 完成前，不要把“推荐默认启动路径”写成已经通过随机 case 验收的口径。

### G4 写已知限制与降级边界
状态：进行中
目标：把当前 V1 的不做范围、失败模式、fallback 逻辑明确写出来。
产出：README 中的限制说明和边界说明。
前置依赖：真实能力与 fallback 基本确定。
子子任务清单：
- 列出 V1 不做和弱化的能力。
- 列出 partial/safe 模式的触发场景。
- 列出已知风险和临时规避办法。
实现备注：已新增 `overview/12_limits-and-degradation-outline.md` 作为第一阶段骨架；当前只整理章节和占位，不提前定稿 `C10 / C11 / F8` 尚未验证的最终边界口径。
本轮执行任务：
- 把“不要过度宣称什么、哪些会降级、哪些只是 demo/fallback”整理成可直接收口的章节骨架。
- 先统一边界的分类方式：输入边界、检索边界、模式边界、fallback 边界、演示口径边界、待验收风险。
- 在 task 文档里明确哪些段落必须等 `C10 / C11 / F8` 后再最终落笔。
执行步骤：
1. 复核现有 README、后端 README、前端 README、DEMO_SCRIPT 和 smoke checklist 里已经出现的边界表述，避免再出现多套说法。
2. 设计限制与降级说明的章节顺序，让后续窗口可以直接按章节补最终内容。
3. 把“必须等待后续任务”的段落单独列出来，避免文档窗口提前替实现窗口做结论。
4. 回写 `G4` 状态和交接建议，说明最终定稿依赖哪些窗口结果。
本轮完成记录：
- 修改文件：`tasks/cluster-g-demo-ops.md`、`overview/12_limits-and-degradation-outline.md`、`overview/README.md`、`README.md`
- 完成方式：新增限制与降级边界骨架文档，按“不应过度宣称 / 输入与主链边界 / 模式与回退 / 演示与 replay 边界 / 已知风险 / 待冻结章节”拆出落点，并补充了后续依赖说明。
- 验证如何：对照 `README.md`、`backend/README.md`、`frontend/README.md`、`DEMO_SCRIPT.md`、`SMOKE_CHECKLIST.md` 中现有边界表述，确认骨架没有越界去宣布 `C10 / C11 / F8` 尚未稳定的结论。
- 剩余问题：URL 输入最终能力边界、真实检索与 verdict 的最终关系、provenance / replay / fallback 的正式展示口径仍待 `C10 / C11 / F8`。
交接建议：
- 最终边界定稿必须以 `F8` 验收记录为准，不能只根据 README 或 smoke checklist 的历史描述。
- `C11` 冻结 provenance 之前，不要把“真实后端 / demo payload / replay / frontend safe fallback”的最终术语写死。
- 后续窗口补边界文案时，优先复用 `overview/12_limits-and-degradation-outline.md` 的章节，不再在多个 README 里各写一套。

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
- 基于现有三条稳定 demo case，整理一份 5 到 10 分钟可复用的演示顺序与口播提纲。
- 在演示文档中写清每个 case 的输入、亮点、推荐讲法，以及不要说过头的边界提醒。
- 同步判断当前材料是否已足够支撑演示，并把需要 `Cluster-F` 或 `Cluster-C / D` 继续补的点写清楚。
执行步骤：
1. 复核现有 demo case、payload 与演示边界文档，确认 `complete / partial / safe_mode` 的真实可讲范围。
2. 设计适合面试场景的演示顺序，明确每一段先看哪里、讲什么、控制在多久。
3. 形成可直接给演示者使用的口播提纲，并补充“亮点 / 边界 / 不要过度宣称”的提醒。
4. 回写 G5 状态、完成记录和交接建议，说明当前演示材料是否还依赖 smoke checklist 或核心能力补强。
本轮完成记录：
- 修改文件：`DEMO_SCRIPT.md`、`README.md`、`tasks/cluster-g-demo-ops.md`
- 完成方式：基于现有三条稳定 demo case、前后端 README、实现总结、demo strategy 与三份 demo payload，整理出一份可直接复用的 5 到 10 分钟演示顺序与口播稿。
- 验证如何：逐项对照 `frontend/lib/demo-cases.ts`、`contracts/demo_payloads/*.json`、`overview/08_origin_problem_gap_and_demo_strategy.md`、`overview/07_quality-and-demo-baseline.md` 的现有边界口径；本轮未改主实现，也未新增运行命令验证。
- 剩余问题：`F7` 独立 smoke checklist 仍未完成；若要扩展到随机开放输入演示，仍依赖 `Cluster-C / D` 继续补真实 URL / retrieval / timeline 能力。
交接建议：
- 当前材料已经足够支撑一场 5 到 10 分钟的稳定演示，优先按 `DEMO_SCRIPT.md` 使用三条稳定 case。
- 请 `Cluster-F` 优先补 `F7` 独立 smoke checklist，作为演示前最后一轮验收入口。
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
- 剩余问题：`G2` replay 仍未落地，`F7` 仍待补齐，后续仍需由主控或 `Cluster-F` 在 README 中补正式清单链接。
交接建议：
- 当前顶层 README 已经足够作为“第一次进仓库的人”和“面试演示者”的统一入口。
- 待 `Cluster-F / F7` 交付后，应优先把正式 smoke checklist 链接补到 README 的“演示前检查清单状态”部分。
- 待 `G2` 明确 replay 方案后，再补 replay 使用说明；当前不要为了看起来完整而写伪说明。




