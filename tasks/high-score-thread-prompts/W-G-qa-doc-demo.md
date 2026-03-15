# W-G / QA Doc Demo

你现在负责线程 `W-G`。

你的职责是：

- 冻结 golden cases
- 补回归和 smoke
- 收口 README、DEMO、答辩材料

你是“稳定性和对外表达”的 owner，不是主业务逻辑 owner。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`
- `backend/tests/*`
- `overview/13_f8-random-acceptance.md`
- `rules/origin_problem_statement.md`
- `rules/score_alignment_rules.md`

## 2. 你允许修改的文件

- `backend/tests/*`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`
- 与样本、验收、说明直接相关的文档

## 3. 你默认不要修改的文件

- `backend/app/services/*`
- `frontend/components/*`
- `contracts/*`

## 4. 本线程核心目标

1. 建高分路线专用的 golden cases
2. 建稳定 smoke 和 regression
3. 把 README / Demo / 答辩口径统一
4. 明确哪些能力能讲，哪些不能讲

## 5. 当前优先任务

优先完成：

- `T09` Golden Cases / Regression / Smoke
- `T10` README / Demo / 答辩材料

## 6. 本轮必须完成的事

### Wave-0 / Wave-1

1. 冻结 `complete / partial / safe` 三类主 demo case
2. 建“复杂新闻拆 claim”回归集
3. 建“真假混杂新闻”回归集
4. 建“传播链完整度”回归集

### Wave-2

5. 建“score 标定”回归集
6. 增强 smoke checklist
7. 设计前端验收入口或替代流程

### Wave-3 / Wave-4

8. 重写 README 入口
9. 重写 Demo Script 为三类 case 口播
10. 补“为什么不是直接让 LLM 给真假概率”的答辩话术
11. 统一 `live / mock / replay / fallback` 边界文案
12. 形成最终 smoke 和 final rehearsal 清单

## 7. 不要做的事

1. 不要大改 backend 主逻辑
2. 不要大改 frontend 主组件
3. 不要把 mock / replay 说成 live 能力

## 8. 开始前先写

在对应任务文档下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 9. 完成标准

你这轮完成的标准是：

1. 评委看到的是一套统一说法，而不是几份互相打架的文档
2. 演示路径和 smoke 路径可复用
3. 各线程都能基于 golden cases 对齐判断标准

## 10. 交付物

你结束时必须明确给出：

1. golden cases 总表
2. regression / smoke 入口
3. README 改动摘要
4. Demo Script 改动摘要
5. 答辩时建议怎么讲的提纲
