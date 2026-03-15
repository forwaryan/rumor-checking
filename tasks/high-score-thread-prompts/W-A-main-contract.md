# W-A / Main Contract

你现在负责线程 `W-A`。

你的身份是：

- 总控 owner
- contract owner
- 阶段屏障 owner

你不是普通实现线程。你的工作不是到处补业务，而是保证所有线程围绕同一套高分路线推进。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `proposal/codex-app-multithread-execution-plan-20260315.md`
- `contracts/report.schema.json`
- `contracts/claim_result.schema.json`
- `contracts/timeline_node.schema.json`
- `backend/app/models/schemas.py`
- `backend/app/services/report_builder.py`
- `rules/origin_problem_statement.md`
- `rules/score_alignment_rules.md`

## 2. 你允许修改的文件

- `contracts/*`
- `backend/app/models/schemas.py`
- `tasks/*`
- `proposal/*`
- 与总控口径直接相关的说明文档

## 3. 你默认不要修改的文件

- `backend/app/services/verdict_engine.py`
- `backend/app/services/timeline_builder.py`
- `backend/app/services/retrieval_*.py`
- `frontend/*`
- `README.md`

## 4. 本线程核心目标

1. 冻结高分路线的目标口径
2. 冻结 `Report` 和评分相关字段
3. 明确每一批次何时可以进入下一批
4. 决定哪些能力可以讲，哪些能力不能讲过头

## 5. 当前优先任务

优先完成：

- `T00` 高分口径与范围冻结
- `T01` Contract / Schema / 字段冻结
- `T11` 最终集成与 Go/No-Go（仅在 Wave-4）

## 6. 本轮必须完成的事

### Wave-0 必做

1. 冻结 `overall_credibility_score`
2. 冻结 `overall_credibility_label`
3. 冻结 `score_breakdown`
4. 冻结 `claim_contributions`
5. 冻结 `timeline_confidence`
6. 冻结 `independent_source_count`
7. 写出其他线程可依赖字段清单
8. 写出其他线程暂时禁止扩展的字段清单

### Wave-3 必做

1. 复核前端和文档口径是否与 contract 一致
2. 冻结 `live / mock / replay / fallback` 的对外说法
3. 冻结 `complete / partial / safe` 的推荐演示 case

### Wave-4 必做

1. 输出最终 Go / No-Go 判断
2. 输出剩余风险清单
3. 冻结最终演示路径

## 7. 开始前先写

在对应任务文档下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 8. 完成标准

你这轮完成的标准不是“改了几个 schema”，而是：

1. `W-C / W-D / W-E / W-F / W-G` 不会再自行发明 report 字段
2. 评分字段可以被前端、测试、文档统一消费
3. 下一批线程知道自己何时可以开工，何时必须暂停

## 9. 交付物

你结束时必须明确给出：

1. 最终字段表
2. 每个新字段的含义、类型、边界
3. 哪些字段已冻结
4. 哪些字段暂不允许扩展
5. 下一批可启动线程名单
