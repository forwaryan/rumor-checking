# Docs Hub

本仓库保留“代码邻近文档不乱搬、项目级文档统一导航、冲突问题集中登记”这三个原则。

## 先看这里

- [../README.md](../README.md)
  - 仓库总入口，给第一次进入项目的人用。
- [status/current-verified-state.md](status/current-verified-state.md)
  - 2026-03-14 按代码核验后的当前状态。
- [status/document-conflict-register.md](status/document-conflict-register.md)
  - 本轮发现的文档冲突问题、核验结果和处理动作表。

## 1. 演示与运行

- [startup-and-test-runbook.md](startup-and-test-runbook.md)
  - 本次实际启动前后端的完整流程、命令、日志和停止方式。
- [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md)
  - 演示顺序、讲法和不要过度宣称的点。
- [../SMOKE_CHECKLIST.md](../SMOKE_CHECKLIST.md)
  - 演示前检查清单。
- [../backend/README.md](../backend/README.md)
  - 后端运行方式、接口和能力边界。
- [../frontend/README.md](../frontend/README.md)
  - 前端运行方式、当前 provenance 展示和已移除路径说明。
- [../data/demos/README.md](../data/demos/README.md)
  - replay 草案目录与演示输入说明。

## 2. 现状与实现

- [../overview/README.md](../overview/README.md)
  - 项目地图与阶段说明。
- [../overview/06_current_code_implementation.md](../overview/06_current_code_implementation.md)
  - 当前代码实现总览。
- [../overview/09_stage-progress-and-task-audit.md](../overview/09_stage-progress-and-task-audit.md)
  - 当前阶段审计与真实状态。
- [../overview/10_unfinished-task-priority-and-parallel-analysis.md](../overview/10_unfinished-task-priority-and-parallel-analysis.md)
  - 当前剩余任务优先级与并行建议。
- [../overview/14_v1-capability-assessment-and-next-parallel-plan.md](../overview/14_v1-capability-assessment-and-next-parallel-plan.md)
  - 当前 V1 已达到的效果、能否对任意新闻较真，以及下一轮并行波次建议。
- [../backend/docs/api-foundation-implementation-record.md](../backend/docs/api-foundation-implementation-record.md)
  - 后端主链实现记录。
- [../backend/docs/real-retrieval-pipeline.md](../backend/docs/real-retrieval-pipeline.md)
  - retrieval 架构与缓存说明。
- [../backend/docs/entity-drift-fix-and-regression-guard.md](../backend/docs/entity-drift-fix-and-regression-guard.md)
  - `question_only` 主体漂移修复专项文档，含流程图、对比表和回归护栏。
- [question-analysis-end-to-end-flow.md](question-analysis-end-to-end-flow.md)
  - 以“用户提问 -> 流式追踪 -> agent/fallback -> 最终 report”为主线的完整流程讲解文档，适合项目答辩和实现说明。
- [../contracts/README.md](../contracts/README.md)
  - 前后端共享 schema 入口。

## 3. 需求、规则、研究

- [../requirements/README.md](../requirements/README.md)
  - 需求分析、研究和模板入口。
- [../rules/README.md](../rules/README.md)
  - 规则与原题约束入口。

## 4. 任务与协作

- [../tasks/README.md](../tasks/README.md)
  - 当前任务板与 cluster 文档入口。
- [../tasks/origin-problem-goal-matrix.md](../tasks/origin-problem-goal-matrix.md)
  - 全局任务状态矩阵。
- [../workflows/README.md](../workflows/README.md)
  - 协作流程文档入口。
- [../prompt-history.md](../prompt-history.md)
  - 历史 prompt 记录。
- [prompt-history-best-prompts-guide.md](prompt-history-best-prompts-guide.md)
  - `prompt-history.md` 中优秀 prompt 的梳理、讲述角度和可复用模板。
- [prompt-history-core-chain-archive.md](prompt-history-core-chain-archive.md)
  - 按核心链路对 `prompt-history.md` 做的全量归档与过程积累分类。
- [ai-collaboration-lessons-from-rumor-checking.md](ai-collaboration-lessons-from-rumor-checking.md)
  - 结合本项目真实经历总结的 AI 协作开发心得、踩坑与方法论。
- [ai-collaboration-lessons-by-key-points.md](ai-collaboration-lessons-by-key-points.md)
  - 按“我为什么会提出这些点 + 项目中暴露了什么问题”重写的 AI 协作复盘版。

## 5. 数据与评测

- [../data/README.md](../data/README.md)
  - cache、demo、数据目录说明。
- [../evals/README.md](../evals/README.md)
  - eval 资产入口。
- [../evals/minimal_v1/README.md](../evals/minimal_v1/README.md)
  - 最小回归集与 fixture 说明。

## 6. 结构约定

- `backend/`、`frontend/`、`contracts/`、`data/`、`evals/` 下的文档继续贴着代码和资产放。
- `docs/` 负责统一导航、现状核验和冲突问题登记，不替代代码邻近文档。
- 如果旧文档和代码事实冲突，先在 [status/document-conflict-register.md](status/document-conflict-register.md) 中登记问题，再直接更新原文件本身。
