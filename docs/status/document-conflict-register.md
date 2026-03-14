# 文档冲突问题表

更新时间：2026-03-14 22:11（Asia/Shanghai）

| 文件 | 发现的问题 | 代码核验后的结论 | 当前处理 |
| --- | --- | --- | --- |
| `README.md` | 旧版同时存在“`C10` 未完成”和“后端已能演示 URL 输入”的混合口径。 | `C10` 的公开 HTML URL 抽取已接入主链；公开 replay 接口仍不存在。 | 已直接改写当前入口摘要与边界说明。 |
| `overview/06_current_code_implementation.md` | 旧版把 URL 抽取、provenance 展示写成未完成。 | URL 抽取与前端 provenance 展示都已落地。 | 已直接改写为代码实现总览。 |
| `overview/08_origin_problem_gap_and_demo_strategy.md` | 旧版仍按“URL 还没接、provenance 未落地”分析演示策略。 | 这两项都已落地，当前真正缺口是 live 路径稳定性与最终验收。 | 已直接改成“当前差距 + 演示策略”版。 |
| `overview/09_stage-progress-and-task-audit.md` | 旧版把 `F2/F4/F6/F8/E9` 写成待做或未同步。 | `F2/F3/F4/F5/F6/F7` 已完成，`F8` 已落正式记录，`E9` 当前展示已完成。 | 本轮直接更新正文状态。 |
| `overview/10_unfinished-task-priority-and-parallel-analysis.md` | 旧版仍把优先级放在 `F2/F4/F6/E9`。 | 当前下一优先级已转到 live retrieval 稳定性、模式漂移和文档同步。 | 本轮直接更新优先级与窗口建议。 |
| `tasks/README.md` | 旧版还把 `E9` 第二阶段列为当前主优先级之一。 | 前端 provenance 当前主展示已经落地。 | 本轮直接更新任务板摘要与当前窗口。 |
| `tasks/origin-problem-goal-matrix.md` | 上轮被错误简化，且没有保留为可持续观察的全局状态表。 | 该文件应继续作为全局任务状态矩阵，并写入最新状态。 | 本轮恢复为完整矩阵并更新状态。 |
| `tasks/cluster-f-quality-gate.md` | 局部段落仍写着“`C10` 未完成”“`F8` 尚未形成正式记录”。 | `C10` 已完成第一阶段，`F8` 已完成记录但真实 live 路径未通过。 | 本轮直接修正文内陈述。 |
| `tasks/cluster-a-control-tower.md` | 仍沿用旧的全局优先级和冻结条件表述。 | 当前优先级应转到 live retrieval、模式漂移与文档同步。 | 本轮直接修正文内优先级与冻结条件。 |
| `tasks/cluster-g-demo-ops.md` | 开头和部分完成记录仍写“顶层 README 过时”“`F7` 未完成”。 | README、DEMO_SCRIPT、SMOKE_CHECKLIST 都已落地；剩余问题是 live 路径结论同步。 | 本轮直接修正文内状态。 |

说明：

- 这里只登记问题，不保留一份冲突原件。
- 后续再发现冲突，继续往这张表补，并直接更新对应原文件。
