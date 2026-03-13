# Prompt History

### 📅 2026-03-13 11:00
> **💡 原始指令摘要**: 根据当前系统已有的原型文档，结合需求，整理它们的实现逻辑、实现思路和实现技术，并把总结文档放到 `requirements/` 目录下。

- **🎯 核心意图 (Context & Goal)**: 用户希望先对现有原型进行统一梳理，明确当前仓库里已经定义了哪些产品目标、AI 协作流程和工程规范，为后续从原型进入系统实现阶段建立一致认知。
- **⚙️ AI 采用的策略 (AI Approach)**: 先枚举仓库中的原型相关文件，分别分析其定位、输入输出和隐含技术约束，再把它们归并成产品层、AI 编排层和研发治理层三部分，最后将总结沉淀为新的需求文档，并同步创建 Prompt 日志文件记录本次任务。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 11:25
> **💡 原始指令摘要**: 调研 GitHub 和各大公司是否有与题目类似的实现，重点包括腾讯新闻“较真AI”等产品，列举并分析对比这些产品，进而反推出我们自己的设计目标。

- **🎯 核心意图 (Context & Goal)**: 用户希望先完成一轮外部竞品与开源调研，确认“新闻传播链还原 + 内容核查”方向在市场上已有怎样的产品形态和技术路线，再据此收敛后续自有产品的设计目标，避免闭门造车。
- **⚙️ AI 采用的策略 (AI Approach)**: 先通过公开网络检索收集可验证的同类产品与 GitHub 项目，优先采用官方页面、官方文档和项目仓库作为依据；再按媒体产品、平台工具、研究型开源实现和数据底座四类做能力拆解，围绕传播链、claim 核查、证据透明度、工程可落地性进行横向对比，最后把结论沉淀为新的 `requirements` 文档并补充 Prompt 日志。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 11:15
> **💡 原始指令摘要**: 总结一份需要向改题目/出题方确认的问题清单，重点关注数据集、题目边界和实施约束。

- **🎯 核心意图 (Context & Goal)**: 用户准备与提供题目修改方案的人沟通，希望提前把最容易导致项目失控或后续返工的关键问题问清楚，尤其是数据来源、评价口径、外部依赖和交付边界。
- **⚙️ AI 采用的策略 (AI Approach)**: 先结合仓库内对“传播链还原 + 内容核查”题目的需求分析，提炼出最关键的澄清维度；再把这些维度整理成可直接向对方提问的清单，优先覆盖数据集、标签与指标、联网和 API 限制、Demo 验收方式及合规要求，并同步追加 Prompt 日志。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 15:49
> **🧵 线程标识**: `T-research`
> **🏷️ 窗口职责**: 调研
> **🔗 上下文来源**: `rules/random_news_demo_rules.md`、`requirements/guides/03_random_news_eval_template.md`、`rules/evidence_and_verdict_rules.md`、`rules/failure_handling_rules.md`、FEVER、FEVEROUS、AVeriTeC、MuMiN、Google Fact Check Tools API、GDELT 公开资料
> **💡 原始指令摘要**: 判断是否存在可用于测试当前工程效果与评分表现的数据集或 benchmark，并分析哪些能直接复用、哪些只能做代理评测。

- **🎯 本线程目标 (Context & Goal)**: 回答“当前项目能否用现成 benchmark 来测工程表现”这个问题，并把可直接评测的能力与必须人工验收的能力拆开。
- **🧩 已知约束 (Known Context)**: 当前项目评分不只看 claim/verdict 正确性，还看产品体验、Demo 稳定性、工程质量与边界感，因此不存在一个单一公开 benchmark 能直接还原总评分。
- **⚙️ AI 采用的策略 (AI Approach)**: 先对照仓库内已有随机新闻评测规则与模板，明确当前项目已经在评哪些维度；再补充外部事实核查 benchmark，区分 verdict/evidence、传播链代理、随机输入稳定性和人工答辩评分四类评测来源，避免把学术 benchmark 误当成完整工程评分。
- **📦 产出与落点 (Artifacts)**: 本次对话中的 benchmark 适配结论与建议；`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议由 `T-main` 或 `T-doc` 把本次结论沉淀成一份 `benchmark_strategy` 文档，明确“公开 benchmark + 随机新闻评测 + 人工评分 rubric”三层评测方案。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 15:53
> **🧵 线程标识**: `T-doc`
> **🏷️ 窗口职责**: 文档
> **🔗 上下文来源**: `overview/01_current_goal_and_layers.md`、`overview/02_folder_rationale.md`、`requirements/analysis/01_scope_and_v1_design.md`、`requirements/analysis/02_prototype_review_and_alignment.md`、`requirements/analysis/03_high_score_gap_analysis.md`、`requirements/analysis/04_implementation_difficulty_analysis.md`、`requirements/analysis/05_difficulty_summary_and_boundary_confirmation.md`、`requirements/analysis/06_propagation_vs_verification_depth_review.md`、`requirements/analysis/07_v1_execution_plan.md`
> **💡 原始指令摘要**: 基于现有 overview 和最小可行方案，制定一版 V1 文档，要求除大模型 API key 调用外尽量做到零额外 key，并将文档与现有分析文档全部关联起来。

- **🎯 本线程目标 (Context & Goal)**: 把当前仓库的总览层和分析层压缩成一份可执行的 V1 蓝图，明确“当前第一版到底做什么、不做什么、哪些能力不应再额外依赖新 key、实现时还要同步维护哪些文档”。
- **🧩 已知约束 (Known Context)**: 当前仓库仍是实现前阶段的文档仓库；V1 必须优先保证传播链时间线和 claim 核查表的最小闭环；用户已决定 V1 先接 Kimi API，后续再对比其他模型；需要避免覆盖已有未提交改动。
- **⚙️ AI 采用的策略 (AI Approach)**: 先读取 overview、分析文档和三份硬规则，整理出一份兼顾边界、能力矩阵、流程图、页面骨架和文档交付物的桥接蓝图；再把该蓝图放进 `overview/`，作为从“项目地图”走向“V1 实施”的过渡文档，并更新入口索引与日志。
- **📦 产出与落点 (Artifacts)**: `overview/03_v1_zero_key_blueprint.md`、`overview/README.md`、`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议 `T-main` 基于本蓝图冻结 V1 边界；随后可由 `T-impl` 按文中 schema 与模块顺序搭后端骨架，再由 `T-doc` 补根目录 README 和样例文档。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 17:01
> **🧵 线程标识**: `T-main`
> **🏷️ 窗口职责**: 主控
> **🔗 上下文来源**: `overview/01_current_goal_and_layers.md`、`overview/03_v1_zero_key_blueprint.md`、`requirements/analysis/07_v1_execution_plan.md`、`rules/evidence_and_verdict_rules.md`、`rules/propagation_chain_rules.md`、`rules/failure_handling_rules.md`、`evals/minimal_v1/README.md`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 按照当前分析好的 V1 版本，给出完整的前后端与整体实现方案，拆成详细 task，在开始写代码前先形成可持续更新的任务清单。

- **🎯 本线程目标 (Context & Goal)**: 把现有仓库从“文档与规则冻结阶段”进一步推进到“可执行的实现规划阶段”，给出明确的前后端分工、共享协议、实施里程碑与 task board，作为后续编码的统一基线。
- **🧩 已知约束 (Known Context)**: 当前仓库仍然以文档、规则和最小测试集为主，尚无正式代码骨架；V1 必须优先保证文本输入、claim/verdict、关键时间线和三档模式，不应直接跳入重型检索或复杂前端；用户希望每完成一个目标就同步更新 task 状态。
- **⚙️ AI 采用的策略 (AI Approach)**: 先复核当前 V1 蓝图、执行清单、三份硬规则和最小测试集，确认可承诺边界；再选择“Next.js 前端 + FastAPI 后端 + Kimi API + 本地缓存”的默认实现路径；最后按 mock 先行、真实能力后接的思路拆出可落地的里程碑和细粒度任务，避免边写边漂移 scope。
- **📦 产出与落点 (Artifacts)**: `overview/05_v1_architecture_and_task_board.md`；`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议先由 `T-main` 认可并冻结当前 task board，随后由 `T-impl-api` 优先启动 `T01`、`T03`、`T04`，先搭后端骨架、共享 schema 和最小测试接入，再进入 mock 闭环开发。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 17:12
> **🧵 线程标识**: `T-main`
> **🏷️ 窗口职责**: 主控
> **🔗 上下文来源**: `overview/05_v1_architecture_and_task_board.md`、`requirements/analysis/07_v1_execution_plan.md`、`evals/minimal_v1/README.md`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 进一步细化当前 V1 的并行方案，要求把能并行的前后端任务拆得更细，并为每个分工方案起明确名字，方便直接分配给不同窗口或集群执行。

- **🎯 本线程目标 (Context & Goal)**: 把已有 task board 从“里程碑级任务”细化为“可直接派发的并行工作包”，让前端、后端、检索、测试和文档类任务都有明确 owner、边界、输入输出和启动条件，降低多窗口协作时的冲突成本。
- **🧩 已知约束 (Known Context)**: 当前仓库仍处于实现前与实现初期的规划阶段；用户准备按窗口/集群并行推进；前后端都需要明确分工；schema 只能有单一 owner，前端不应等待真实后端，测试线程应尽量与实现线程解耦。
- **⚙️ AI 采用的策略 (AI Approach)**: 基于现有 `T00 ~ T26` task board，重新组织成多个具名 cluster，把原任务映射到更细的子任务和阶段波次中；同时补上启动条件、依赖关系和不该做的事项，让每个 cluster 可以被单独下发而不互相踩边界。
- **📦 产出与落点 (Artifacts)**: `overview/05_v1_architecture_and_task_board.md`；`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议由 `T-main` 先按 cluster 数量决定窗口分配；如果窗口足够，优先单独启动 `Cluster-B / Contract Forge`、`Cluster-C / API Foundation`、`Cluster-E / Experience Shell`、`Cluster-F / Quality Gate`；如果窗口较少，则按文档中的 3 窗口或 4 窗口组合方案合并执行。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 17:19
> **🧵 线程标识**: `T-main`
> **🏷️ 窗口职责**: 主控
> **🔗 上下文来源**: `overview/05_v1_architecture_and_task_board.md`、`tasks/`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 在已有并行 cluster 方案基础上，创建独立的 `tasks/` 文件夹，并为每个可独立并行的任务单独建立 md 文件，文件内说明任务目的、必要性、并行原因和未完成的细分子任务。

- **🎯 本线程目标 (Context & Goal)**: 把“可并行分工方案”进一步沉淀为可直接分发的任务资产，让每个窗口都能拿到一份独立任务文档开始执行，并且后续可由用户手动更新完成状态。
- **🧩 已知约束 (Known Context)**: 用户希望每个并行任务都有独立 md 文件；每个文件必须说明做什么、为什么需要、为什么能并行；每个子任务都要初始化为“未完成”；当前仓库还没有正式代码骨架，但已有 cluster 级任务拆分文档。
- **⚙️ AI 采用的策略 (AI Approach)**: 以 cluster 为单位创建 `tasks/` 目录和独立 md 文件，而不是把所有任务塞进一个总表；每个文件使用统一模板，保证跨窗口阅读体验一致，并保留足够细的子任务颗粒度，方便后续逐项手动更新。
- **📦 产出与落点 (Artifacts)**: `tasks/README.md`、`tasks/cluster-a-control-tower.md`、`tasks/cluster-b-contract-forge.md`、`tasks/cluster-c-api-foundation.md`、`tasks/cluster-d-retrieval-lab.md`、`tasks/cluster-e-experience-shell.md`、`tasks/cluster-f-quality-gate.md`、`tasks/cluster-g-demo-ops.md`；`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议用户直接按 `tasks/` 中的 cluster 文件分配窗口；若准备开始编码，可优先分发 `cluster-b-contract-forge.md`、`cluster-c-api-foundation.md`、`cluster-e-experience-shell.md`、`cluster-f-quality-gate.md` 作为第一波。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 17:28
> **🧵 线程标识**: `T-main`
> **🏷️ 窗口职责**: 主控
> **🔗 上下文来源**: `tasks/README.md`、`tasks/cluster-a-control-tower.md`、`tasks/cluster-b-contract-forge.md`、`tasks/cluster-c-api-foundation.md`、`tasks/cluster-d-retrieval-lab.md`、`tasks/cluster-e-experience-shell.md`、`tasks/cluster-f-quality-gate.md`、`tasks/cluster-g-demo-ops.md`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 检查当前各 task 是否足够详细，并继续把每个子 task 细化成列表化的“子子 task”，让任务颗粒度更小，便于并行分工和手动更新状态。

- **🎯 本线程目标 (Context & Goal)**: 把 `tasks/` 目录中的 cluster 任务从“子 task 级别”继续下钻到“子子 task 级别”，让每个并行窗口都能拿到更细的可执行步骤，不必自行再次拆解任务。
- **🧩 已知约束 (Known Context)**: 用户希望每个 cluster 文件内的每个子 task 都有更小颗粒度的列表步骤；所有子任务默认保持“未完成”；当前 `tasks/` 已经存在独立 cluster 文件，但此前粒度还偏粗。
- **⚙️ AI 采用的策略 (AI Approach)**: 先通读所有 cluster 文件，确认当前结构一致但步骤不够细；再统一为每个子 task 增加“子子任务清单”，确保每一项都具备可直接执行的最小动作，同时保留目标、产出和前置依赖，方便不同窗口并行推进。
- **📦 产出与落点 (Artifacts)**: `tasks/README.md`、`tasks/cluster-a-control-tower.md`、`tasks/cluster-b-contract-forge.md`、`tasks/cluster-c-api-foundation.md`、`tasks/cluster-d-retrieval-lab.md`、`tasks/cluster-e-experience-shell.md`、`tasks/cluster-f-quality-gate.md`、`tasks/cluster-g-demo-ops.md`；`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议用户现在直接按 `tasks/` 目录分发窗口；每个窗口只需围绕自己任务文件中的“子子任务清单”推进，并在完成后手动更新状态，不需要再额外拆分第一轮任务。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 17:49
> **🧵 线程标识**: `T-main`
> **🏷️ 窗口职责**: 主控
> **🔗 上下文来源**: `tasks/README.md`、`tasks/cluster-a-control-tower.md`、`tasks/cluster-b-contract-forge.md`、`tasks/cluster-c-api-foundation.md`、`tasks/cluster-d-retrieval-lab.md`、`tasks/cluster-e-experience-shell.md`、`tasks/cluster-f-quality-gate.md`、`tasks/cluster-g-demo-ops.md`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 在 `tasks/README.md` 中明确标出各个窗口负责什么、对应拿哪个任务文件，以及不同窗口数量下应该如何分配。

- **🎯 本线程目标 (Context & Goal)**: 让 `tasks/README.md` 不只是索引，而是可以直接指导分工的窗口分配说明，帮助用户一眼判断“哪个窗口负责什么、应该谁来拿”。
- **🧩 已知约束 (Known Context)**: 用户已经有基于 cluster 的任务文件，但缺少顶层 README 中的窗口级分配说明；需要明确职责、推荐 owner 类型，以及 3 窗口、4 窗口、6-7 窗口下的合并策略。
- **⚙️ AI 采用的策略 (AI Approach)**: 在不改动 cluster 任务文件主体的前提下，增强 `tasks/README.md`，新增“窗口分配建议”和“窗口不足时的合并方案”两部分，让 README 本身就能作为分发入口使用。
- **📦 产出与落点 (Artifacts)**: `tasks/README.md`；`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议用户先按 README 中的窗口说明分发 cluster；如果当前窗口足够，优先单独启动窗口 2、3、5、6；如果窗口不足，则按 README 的 4 窗口或 3 窗口组合方案合并分工。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 18:53
> **🧵 线程标识**: `T-impl-web`
> **🏷️ 窗口职责**: 实现
> **🔗 上下文来源**: `tasks/cluster-e-experience-shell.md`、`overview/03_v1_zero_key_blueprint.md`、`overview/05_v1_architecture_and_task_board.md`、`rules/evidence_and_verdict_rules.md`、`rules/propagation_chain_rules.md`、`rules/failure_handling_rules.md`、`contracts/`、`frontend/`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 窗口 5 负责 `T-impl-web`，先实现 `Cluster-E / Experience Shell` 的前端单页壳；随后用户要求在继续后续任务前，对目前修改过的代码补一份详细文件记录。

- **🎯 本线程目标 (Context & Goal)**: 基于 `Cluster-E / Experience Shell` 任务文档落下可运行的 Next.js 单页前端壳，覆盖输入区、状态条、事件概览、风险提示、时间线、claim 表和证据列表，并在继续后续联调前产出可交接的逐文件记录。
- **🧩 已知约束 (Known Context)**: 当前仓库最初只有 `frontend/` 空骨架，前端可先基于 mock `Report` payload 独立开发；三档模式必须明确区分；接口失败时不能伪装成完整结果；当前机器 Node 版本为 `18.19.0`，因此前端依赖需要与 Node 18 兼容；工作区存在其他窗口推进的后端改动，不应串线覆盖。
- **⚙️ AI 采用的策略 (AI Approach)**: 先从 `tasks/cluster-e-experience-shell.md`、`overview/` 与 `rules/` 中抽取最小可用协议、页面结构和模式边界；再补 `contracts/*.schema.json` 与 `contracts/demo_payloads/*.json`，保证前端有稳定输入；随后落 `frontend/` 的 Next.js 配置、类型层、API client、demo 注册、页面组件和全局样式；最后完成依赖安装、类型检查、构建验证，并按用户要求补 `frontend/FILE_RECORD.md` 做逐文件交接记录。
- **📦 产出与落点 (Artifacts)**: `contracts/event.schema.json`、`contracts/timeline_node.schema.json`、`contracts/evidence.schema.json`、`contracts/claim_result.schema.json`、`contracts/report.schema.json`、`contracts/demo_payloads/*.json`、`frontend/package.json`、`frontend/tsconfig.json`、`frontend/next.config.ts`、`frontend/README.md`、`frontend/types/report.ts`、`frontend/lib/demo-cases.ts`、`frontend/lib/report-utils.ts`、`frontend/lib/api-client.ts`、`frontend/components/*.tsx`、`frontend/app/layout.tsx`、`frontend/app/page.tsx`、`frontend/app/globals.css`、`frontend/FILE_RECORD.md`、`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议后续继续任务时，由 `T-impl-web` 先拿 `frontend/FILE_RECORD.md` 作为当前前端状态基线，再与 `T-impl-api` 对齐真实 `Report` 返回结构；如果先做演示稳定性，则优先联通 `demo-cases / replay / analyze` 三类接口，不要先扩 UI 范围。
- **⭐ 效果评估**: [待填写]

---

### 📅 2026-03-13 20:41
> **🧵 线程标识**: `T-impl-web`
> **🏷️ 窗口职责**: 实现
> **🔗 上下文来源**: `tasks/cluster-e-experience-shell.md`、`frontend/README.md`、`frontend/FILE_RECORD.md`、`frontend/components/analyze-page.tsx`、`frontend/lib/api-client.ts`、`frontend/types/report.ts`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 用户以 `[log]` 方式要求前端窗口也补一份“图文并茂”的详细总结，要求讲清这部分前端是怎么设计的、目前实现了什么、底层用了哪些框架、具体有哪些接口、怎么使用，以及其他能帮助他人快速理解代码逻辑框架的内容。

- **🎯 本线程目标 (Context & Goal)**: 产出一份可以直接交给他人阅读的前端实现总结文档，让接手者不必先翻大量源码，也能快速理解 `Cluster-E / Experience Shell` 的设计目标、架构分层、状态流、接口依赖、使用方式和当前边界。
- **🧩 已知约束 (Known Context)**: 当前前端必须围绕真实 `GET /api/v1/health` 和 `POST /api/v1/analyze` 两个接口说明；后端暂未提供 `demo-cases / replay` 接口；总结不能只重复 README 或文件清单，而要补足设计思路、状态流和使用方式；本线程仍处于 `T-impl-web` 窗口，不应越界改动其他线程的后端实现。
- **⚙️ AI 采用的策略 (AI Approach)**: 先回读 Cluster-E 任务定义、现有 README、文件记录和主入口代码，再用一份独立 Markdown 文档把“设计目标、架构图、时序图、模式说明、接口调用、demo 策略、运行方式、验证结果、后续扩展点”系统化串起来，并在 README 顶部补入口链接，保证后续窗口能够从总结文档直接建立整体认知。
- **📦 产出与落点 (Artifacts)**: `frontend/IMPLEMENTATION_SUMMARY.md`、`frontend/README.md`、`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议后续接手 `T-impl-web` 或做联调的窗口先读 `frontend/IMPLEMENTATION_SUMMARY.md`，再按其中“关键文件从哪里看起”和“后续优先级”两节进入真实 `Report` 联调与页面级 smoke test 补强。
- **⭐ 效果评估**: [待填写]

---
### 📅 2026-03-13 20:41
> **🧵 线程标识**: `T-impl-web`
> **🏷️ 窗口职责**: 实现
> **🔗 上下文来源**: `tasks/README.md`、`tasks/cluster-a-control-tower.md`、`tasks/cluster-b-contract-forge.md`、`tasks/cluster-c-api-foundation.md`、`tasks/cluster-d-retrieval-lab.md`、`tasks/cluster-e-experience-shell.md`、`tasks/cluster-f-quality-gate.md`、`tasks/cluster-g-demo-ops.md`、`backend/docs/api-foundation-implementation-record.md`、`backend/README.md`、`backend/tests/`、`contracts/`、`frontend/README.md`、`frontend/IMPLEMENTATION_SUMMARY.md`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 用户以 `[log]` 方式要求盘点 `tasks/` 当前任务状态，分析哪些 cluster 已基本完成、哪些仍有缺口、哪些最关键、哪些当前优先级较低，以及缺了哪些能力会导致项目虽然“有代码”但还不能稳定跑通或稳定演示。

- **🎯 本线程目标 (Context & Goal)**: 基于任务文件与实际代码实现做一次“计划 vs 现状”对照，给出下一步开发优先级和运行阻塞项判断，避免继续按已经过时的 task 状态推进。
- **🧩 已知约束 (Known Context)**: `tasks/` 中多数子任务仍保留初始化时的“未完成”状态，不能直接反映真实进度；后端 `Cluster-C` 和前端 `Cluster-E` 已经比任务文档更靠前；`Cluster-D/F/G` 仍存在明显未闭环项；顶层 `README.md` 仍停留在“实现准备阶段”，已经与当前仓库状态不一致；其他线程的后端文件仍在工作区中，不适合由当前窗口擅自回写 task 状态。
- **⚙️ AI 采用的策略 (AI Approach)**: 先通读 `tasks/` 与窗口分配规则，再交叉读取 `backend/docs/api-foundation-implementation-record.md`、`backend/README.md`、`backend/tests/`、`contracts/`、`frontend/` 等实际落地代码和文档，按 cluster 重新判断“已完成 / 部分完成 / 未完成 / 当前关键性”，并把“会不会阻塞可运行 / 可演示”的原因拆开说明。
- **📦 产出与落点 (Artifacts)**: `prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 建议下一步优先由 `T-main` 或当前主控窗口统一刷新 `tasks/` 状态口径；实现层优先推进 `Cluster-D` 的真实检索/时间线、`Cluster-C` 的 URL 正文抽取、`Cluster-F` 的 case 回归与 smoke checklist、`Cluster-G` 的最终运行/演示 README 收口，再考虑 replay 与缓存等次级能力。
- **⭐ 效果评估**: [待填写]

---
### 📅 2026-03-13 21:23
> **🧵 线程标识**: `T-impl-web`
> **🏷️ 窗口职责**: 实现
> **🔗 上下文来源**: `tasks/README.md`、`tasks/cluster-a-control-tower.md`、`tasks/cluster-b-contract-forge.md`、`tasks/cluster-c-api-foundation.md`、`tasks/cluster-d-retrieval-lab.md`、`tasks/cluster-f-quality-gate.md`、`tasks/cluster-g-demo-ops.md`、`README.md`、`workflows/prompt_logging_rules.md`
> **💡 原始指令摘要**: 用户要求继续处理未完成任务，并补一份能直接支撑并行开发的模块责任分析与执行手册：不仅要说明每个模块负责什么，还要给每个未完成子 task 准备可直接发给窗口的 prompt，并要求窗口在真正执行时再按 task 提示拆成更细步骤完成。

- **🎯 本线程目标 (Context & Goal)**: 把 `tasks/` 从“状态板”升级为“可直接派工”的执行体系，让后续窗口拿到未完成子 task 后不用再自己编 prompt 和拆步骤，就能在边界清晰的前提下并行推进。
- **🧩 已知约束 (Known Context)**: `tasks/cluster-*.md` 当前更适合作为状态基线，不适合塞入过长的复制式 prompt；因此需要用一份独立手册承接模块责任分析、子 task 执行 prompt 和更细执行步骤；同时 `tasks/README.md` 需要补入口说明，避免新手只看到状态文件而看不到执行手册。
- **⚙️ AI 采用的策略 (AI Approach)**: 先识别所有仍未闭环的 cluster 和子 task，再新增 `tasks/parallel-execution-playbook.md` 作为并行执行手册，按 cluster 统一写出“模块责任分析 + 每个未完成子 task 的窗口 prompt + 更细执行步骤”，并在 `tasks/README.md` 中补上使用方式与入口链接，让状态文件和执行手册分层协作。
- **📦 产出与落点 (Artifacts)**: `tasks/parallel-execution-playbook.md`、`tasks/README.md`、`prompt-history.md`
- **➡️ 交接建议 (Next Handoff)**: 之后如果要继续开并行窗口，建议先在 `tasks/cluster-*.md` 里确认状态，再直接从 `tasks/parallel-execution-playbook.md` 复制对应子 task prompt 给新窗口；当前最适合优先派发的是 `D5 / C10 / F2 or F7 / G3-G5 / A3`。
- **⭐ 效果评估**: [待填写]

---