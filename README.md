# rumor-checking

面向“较真”的新闻观察员题目的文档与协作仓库。

当前仓库仍以需求分析、验证规划和协作规则为主，现已进入实现准备阶段：代码目录骨架已经预留，但业务实现尚未正式展开。

## 目录总览

- `evals/`
  - 开发期最小测试集、回归样本和评测数据
- `frontend/`
  - 前端单页 Demo 代码骨架与界面实现入口
- `backend/`
  - 后端 API、核查流水线和测试代码骨架
- `contracts/`
  - 前后端共享 schema、字段约定和 mock payload
- `data/`
  - 开发期复制数据、缓存和 demo 回放数据
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

## 当前建议

如果准备进入实现阶段，建议先从以下顺序推进：

1. 先验证输入抽取、证据检索和 claim 核查这三条最小链路
2. 再冻结 V1 的功能边界和演示用例
3. 最后再完善真正的 Web Demo 和业务实现

如果需要先理解整个仓库为什么这样分层，建议优先阅读：

1. `overview/README.md`
2. `overview/01_current_goal_and_layers.md`
3. `overview/02_folder_rationale.md`
4. `overview/04_prompt_inventory.md`
5. `requirements/guides/04_prompt_inventory.md`
6. `evals/minimal_v1/README.md`




