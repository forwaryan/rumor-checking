# Docs Hub

本仓库保留“代码邻近文档不乱搬、项目级文档统一导航、冲突旧稿单独归档”这三个原则。

## 先看这里

- [../README.md](../README.md)
  - 仓库总入口，给第一次进入项目的人用。
- [status/current-verified-state.md](status/current-verified-state.md)
  - 2026-03-14 按代码核验后的当前状态。
- [archive/conflicts/README.md](archive/conflicts/README.md)
  - 已归档的冲突旧稿与归档原因。

## 1. 演示与运行

- [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md)
  - 演示顺序、讲法和不要过度宣称的点。
- [../SMOKE_CHECKLIST.md](../SMOKE_CHECKLIST.md)
  - 演示前检查清单。
- [../backend/README.md](../backend/README.md)
  - 后端运行方式、接口和能力边界。
- [../frontend/README.md](../frontend/README.md)
  - 前端运行方式、fallback 和 provenance 展示。
- [../data/demos/README.md](../data/demos/README.md)
  - replay 目录草案与 demo 资产说明。

## 2. 现状与实现

- [../overview/README.md](../overview/README.md)
  - 项目地图与阶段说明。
- [../overview/06_current_code_implementation.md](../overview/06_current_code_implementation.md)
  - 当前代码实现总览。
- [../backend/docs/api-foundation-implementation-record.md](../backend/docs/api-foundation-implementation-record.md)
  - 后端主链实现记录。
- [../backend/docs/real-retrieval-pipeline.md](../backend/docs/real-retrieval-pipeline.md)
  - retrieval 架构与缓存说明。
- [../frontend/IMPLEMENTATION_SUMMARY.md](../frontend/IMPLEMENTATION_SUMMARY.md)
  - 前端实现总结。
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
- [../workflows/README.md](../workflows/README.md)
  - 协作流程文档入口。
- [../prompt-history.md](../prompt-history.md)
  - 历史 prompt 记录。

## 5. 数据与评测

- [../data/README.md](../data/README.md)
  - cache、demo、数据目录说明。
- [../evals/README.md](../evals/README.md)
  - eval 资产入口。
- [../evals/minimal_v1/README.md](../evals/minimal_v1/README.md)
  - 最小回归集与 fixture 说明。

## 6. 结构约定

- `backend/`、`frontend/`、`contracts/`、`data/`、`evals/` 下的文档继续贴着代码和资产放。
- `docs/` 负责统一导航、现状核验和冲突归档，不替代代码邻近文档。
- 如果旧文档和代码事实冲突，先在 [status/current-verified-state.md](status/current-verified-state.md) 中给出核验结论，再把旧版本归档到 [archive/conflicts/](archive/conflicts/)。
