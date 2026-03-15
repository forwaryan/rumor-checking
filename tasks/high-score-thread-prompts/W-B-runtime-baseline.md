# W-B / Runtime Baseline

你现在负责线程 `W-B`。

你的职责只有一个：

- 把默认运行链和基线修到“可复现、可解释、可回归”

你不是 verdict 线程，不是前端线程，也不是 contract owner。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`
- `overview/11_runtime-and-env-outline.md`
- `overview/12_limits-and-degradation-outline.md`
- `overview/13_f8-random-acceptance.md`
- `backend/app/core/config.py`
- `backend/README.md`
- `frontend/README.md`

## 2. 你允许修改的文件

- `backend/app/core/*`
- 运行与配置相关说明文档
- 必要的启动脚本
- 与基线直接相关的测试和说明

## 3. 你默认不要修改的文件

- `contracts/*`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/timeline_builder.py`
- `backend/app/services/report_builder.py`
- `frontend/components/*`

## 4. 本线程核心目标

1. 冻结默认开发路径
2. 冻结默认演示路径
3. 冻结关键环境变量默认值
4. 让 README / SMOKE / overview 的运行口径一致

## 5. 当前优先任务

优先完成：

- `T02` 默认运行链与基线统一

## 6. 本轮必须完成的事

1. 明确默认 `analysis_provider / retrieval_provider / fallback` 组合
2. 明确默认开发路径和默认演示路径
3. 核对 Node / Python 最低版本并补到文档
4. 补齐标准命令：安装、启动、测试、演示
5. 确认默认环境的关键 smoke 可以复现
6. 把 README / SMOKE / overview 的基线口径同步一致

## 7. 不要做的事

1. 不要顺手改 verdict / timeline 逻辑
2. 不要擅自新增 report 字段
3. 不要为了追求 live 路径，把默认可运行路径搞复杂

## 8. 开始前先写

在对应任务文档下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 9. 完成标准

你这轮完成的标准是：

1. 新人照着 README 和 SMOKE 就能知道怎么跑
2. 默认路径不再同时出现两套互相矛盾的说法
3. 后续线程不需要再猜默认配置是什么

## 10. 交付物

你结束时必须明确给出：

1. 默认运行路径说明
2. 默认演示路径说明
3. 标准启动命令
4. 关键环境变量说明
5. 已验证的命令及结果
