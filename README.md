# rumor-checking

面向“较真”的新闻观察员题目的文档、实现与协作仓库。

当前仓库已经从“实现准备阶段”进入“最小闭环已成形、关键能力待补齐”的阶段：

- `contracts/` 已形成前后端共享 schema 和三份稳定 demo payload
- `backend/` 已提供 `GET /api/v1/health` 与 `POST /api/v1/analyze`，并具备规则链路 + 可选 Kimi enrichment
- `frontend/` 已提供单页工作台，支持真实 analyze 优先、本地 demo 回退和三档模式展示
- 前后端都已有最小测试覆盖
- 但真实检索/时间线、URL 正文抽取、系统性回归和最终演示收口仍未完成

## 目录总览

- `evals/`
  - 开发期最小测试集、回归样本和评测数据
- `frontend/`
  - 前端单页 Demo、组件、样式、类型、最小单元测试与实现总结
- `backend/`
  - FastAPI 服务、分析流水线、provider 接入、测试与实现记录
- `contracts/`
  - 前后端共享 schema、字段约定和 demo payload
- `data/`
  - 开发期复制数据、缓存和 demo / replay 数据目录
- `overview/`
  - 仓库总览、项目地图、分层解释和文件夹职责说明
- `requirements/analysis/`
  - 核心需求、方案边界、原型对齐、实现难点和高分缺口分析
- `requirements/research/`
  - 竞品、开源资源和设计目标调研
- `requirements/guides/`
  - 辅助说明文档，例如方括号触发指令总览
- `rules/`
  - 评分对齐、提交规范和原始题目说明
- `workflows/`
  - AI 协作流程规则，例如 Prompt 日志记录规则
- `prompt-history.md`
  - Prompt 任务日志沉淀
- `tasks/`
  - 按 cluster 拆分的并行工作包与当前任务状态

## 当前最关键的下一步

1. 优先补 `Cluster-D` 的真实检索、去重归并和真实时间线构建。
2. 完成 `Cluster-C` 的 URL 正文抽取，也就是 `C10`。
3. 补齐 `Cluster-F` 的 eval 回归和演示前 smoke checklist。
4. 收口 `Cluster-G` 的最终 README、演示口径和 replay / demo 资产。
5. 由主控窗口同步刷新 `tasks/` 的状态板，避免继续按过时进度推进。

## 建议优先阅读

如果需要快速理解当前真实代码状态，建议优先阅读：

1. `frontend/IMPLEMENTATION_SUMMARY.md`
2. `frontend/FILE_RECORD.md`
3. `backend/docs/api-foundation-implementation-record.md`
4. `backend/README.md`
5. `tasks/README.md`
6. `evals/minimal_v1/README.md`