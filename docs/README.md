# Docs

仓库当前只保留和现行代码、运行路径、演示口径直接相关的文档。

以下几类历史文档已经移除：

- 任务拆分与多窗口执行文档
- 提案、规划和旧阶段蓝图
- Prompt 历史、协作复盘和冲突登记表
- 已经被当前 README 覆盖的实现记录

## 先看这里

- [../README.md](../README.md)
  - 仓库总入口和当前运行基线。
- [current-code-architecture-guide.md](current-code-architecture-guide.md)
  - 当前代码结构、项目架构与示例链路总览。
- [status/current-verified-state.md](status/current-verified-state.md)
  - 已按当前代码核验过的事实边界。
- [status/web-search-options.md](status/web-search-options.md)
  - 联网检索方案调查、各入口能力对比与推荐方向。
- [question-analysis-end-to-end-flow.md](question-analysis-end-to-end-flow.md)
  - 从用户输入到最终 `Report` 的主链路讲解。

## 运行与演示

- [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md)
  - 演示顺序、样例和口播边界。
- [../SMOKE_CHECKLIST.md](../SMOKE_CHECKLIST.md)
  - 演示前检查清单。
- [../backend/README.md](../backend/README.md)
  - 后端接口、环境变量和已知边界。
- [../frontend/README.md](../frontend/README.md)
  - 前端运行方式、来源标签和错误态说明。

## 协议与数据

- [../contracts/README.md](../contracts/README.md)
  - 前后端共享 schema 的入口。
- [../data/README.md](../data/README.md)
  - 运行时缓存与数据目录说明。
- [../evals/README.md](../evals/README.md)
  - 评测资产总入口。
- [../evals/minimal_v1/README.md](../evals/minimal_v1/README.md)
  - 当前最小回归集说明。

## 约定

- 代码邻近文档继续放在对应目录下。
- `docs/` 只承担项目级导航和当前状态说明，不再保留过程性归档。
