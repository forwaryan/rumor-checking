> 先看 `../docs/status/current-verified-state.md`。如果 `overview/` 中任何文件与代码冲突，以这份已核验状态文档和对应实现为准；旧版本归档在 `../docs/archive/conflicts/`。

# Overview

本目录用于解释“这个仓库现在到底在做什么、处于什么阶段、哪些口径已经冻结”。

它不是新的需求分析，也不是新的规则集合，而是一个给人快速建立全局认知的项目地图。

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
13. `13_f8-random-acceptance.md`
14. `14_v1-capability-assessment-and-next-parallel-plan.md`
15. `15_origin-problem-task-overview.md`

补充说明：

- `overview/04_prompt_inventory.md` 侧重项目历史中实际出现过的 Prompt 轨迹与上下文脉络。
- 可复用的 Prompt 资产与规范化入口以 `requirements/guides/04_prompt_inventory.md` 为准。
- `overview/10_unfinished-task-priority-and-parallel-analysis.md` 保留并行拆窗与历史执行背景，适合回看为什么当时要先做 `F8` 再做 `G3 / G4`；它不是当前对外交付口径的最终来源。
- `overview/11_runtime-and-env-outline.md` 记录过运行路径与环境变量的收口过程；若其中仍出现 `replay / frontend fallback` 等旧术语，以 `docs/status/current-verified-state.md` 和当前 README 为准。
- `overview/12_limits-and-degradation-outline.md` 记录过限制与降级边界的收口过程；当前运行时来源标签只保留 `backend_live / backend_mock`，旧术语按历史背景理解即可。
- `overview/13_f8-random-acceptance.md` 是当前最终验收记录来源，README、Smoke 和运行说明都应以它为准。
- `overview/14_v1-capability-assessment-and-next-parallel-plan.md` 总结当前 V1 实际达到的效果、是否已经能“对任意新闻较真”，以及下一轮更合理的并行波次。

适合以下场景：

- 刚进入仓库，想先建立整体理解。
- 需要向别人解释当前项目到底发展到了哪一步。
- 想确认今天能交付哪些 `backend_live / backend_mock` 路径，哪些仍只是内部诊断或历史草案。
- 想理解为什么现在的 README、Smoke 和演示口播必须沿用同一套 `F8` 口径。
- 想回看当前项目里到底用过哪些 Prompt、触发词和对话主题。
