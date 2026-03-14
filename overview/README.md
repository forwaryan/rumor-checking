# Overview

本目录用于解释“这个仓库现在到底在做什么、处于什么阶段、各个文件夹为什么存在”。

它不是新的需求分析，也不是新的规则集合，而是一个给人快速建立全局认知的“项目地图”。

建议阅读顺序：

1. `01_current_goal_and_layers.md`
2. `02_folder_rationale.md`
3. `03_v1_zero_key_blueprint.md`
4. `04_prompt_inventory.md`
5. `05_v1_architecture_and_task_board.md`
6. `06_current_code_implementation.md`
7. `07_quality-and-demo-baseline.md`
8. `08_origin_problem_gap_and_demo_strategy.md`
9. `09_stage-progress-and-task-audit.md`
10. `10_unfinished-task-priority-and-parallel-analysis.md`
11. `11_runtime-and-env-outline.md`
12. `12_limits-and-degradation-outline.md`

补充说明：

- `overview/04_prompt_inventory.md` 侧重项目历史中实际出现过的 Prompt 轨迹与上下文脉络
- 可复用的 Prompt 资产与规范化入口以 `requirements/guides/04_prompt_inventory.md` 为准
- `overview/10_unfinished-task-priority-and-parallel-analysis.md` 侧重当前剩余任务的优先级、并行边界和 Kimi 相关推进路线
- `overview/11_runtime-and-env-outline.md` 是 `G3` 第一阶段的运行说明与环境变量章节骨架，先固定目录和章节，不提前写死最终推荐路径
- `overview/12_limits-and-degradation-outline.md` 是 `G4` 第一阶段的限制与降级边界骨架，后续按 `C10 / C11 / F8` 结果收口

适合以下场景：

- 刚进入仓库，想先建立整体理解
- 需要向别人解释当前项目到底发展到了哪一步
- 想知道某个文件夹为什么存在、应该去哪找某类信息
- 想把 `overview/` 直接翻译成“当前 V1 到底怎么做、做到什么边界”
- 想回看当前项目里到底用过哪些 Prompt、触发词和对话主题
- 想快速理解当前已经落地的代码结构、测试基线和 demo 基线
- 想快速决定下一波未完成任务应该如何拆窗口并行


