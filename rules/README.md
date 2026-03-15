# Rules

本目录用于存放项目执行过程中的核心规则和题目原始约束。

- `origin_problem_statement.md`：原始题目说明、时间安排和评分标准
- `score_alignment_rules.md`：`[scores]` 触发后的评分对齐与打分规则
- `commit_rules.md`：`[Commit]` 触发后的提交识别、Commit Message 生成与真实提交规则
- `scoped_task_file_update_rules.md`：`[task_file_rules]` 触发后的共享任务文档安全更新规则；配合 `[TARGET_TASK_FILE: ...]` 使用，默认追加不删除，支持可追溯修正
- `prompt_and_eval_rules.md`：Prompt 版本、schema、幻觉防控、上下文超限与 eval 资产规则
- `random_news_demo_rules.md`：随机新闻输入下的分流、降级、输出边界与 Demo 应对规则
- `evidence_and_verdict_rules.md`：证据字段、来源分级、verdict 标签与强约束规则
- `propagation_chain_rules.md`：传播链节点定义、去重归并与可承诺边界规则
- `failure_handling_rules.md`：输入失败、检索失败、超长文本、证据冲突等异常处理规则
- `task_overview_progress_rules.md`：任务总览表维护规则；按规则名唤醒后，主 task 依赖多个子 task 时必须展开依赖项与各自进度
