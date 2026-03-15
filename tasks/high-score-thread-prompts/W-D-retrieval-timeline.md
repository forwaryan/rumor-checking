# W-D / Retrieval Timeline

你现在负责线程 `W-D`。

你的职责是：

- 建统一 evidence bundle
- 把传播链时间线做得更像“传播过程还原”

你不是 contract owner，不是 verdict owner，也不是 README owner。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `backend/app/services/retrieval_service.py`
- `backend/app/services/retrieval_provider.py`
- `backend/app/services/retrieval_models.py`
- `backend/app/services/retrieval_cache.py`
- `backend/app/services/retrieval_deduper.py`
- `backend/app/services/timeline_builder.py`
- `rules/propagation_chain_rules.md`

## 2. 你允许修改的文件

- `backend/app/services/retrieval_*.py`
- `backend/app/services/timeline_builder.py`
- 检索与传播链相关测试

## 3. 你默认不要修改的文件

- `contracts/*`
- `backend/app/models/schemas.py`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- `frontend/*`
- `README.md`

## 4. 本线程核心目标

1. 建立统一 evidence bundle
2. 统一不同来源的检索结果结构
3. 做来源独立性、冲突标记和失败原因记录
4. 让时间线不只是排序，而是能讲清传播阶段

## 5. 当前优先任务

优先完成：

- `T04` 多源检索与 Evidence Bundle
- `T06` 传播链还原收口

## 6. 本轮必须完成的事

1. 为每条 claim 生成 2 到 5 组 query
2. 统一接入和归一官方源、主流媒体源、聚合新闻源
3. 区分原始源和转载源
4. 在 evidence bundle 中增加来源独立性判断
5. 增加失败原因、冲突标记、去重信息
6. 强化 `origin / amplification / peak / turn / clarification`
7. 给 `peak` 增加传播强度代理信号
8. 至少冻结 2 条能稳定讲清的传播链 case

## 7. 不要做的事

1. 不要自己下 supported / refuted 结论
2. 不要新增 report 最终字段
3. 不要改前端组件

## 8. 开始前先写

在对应任务文档下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 9. 完成标准

你这轮完成的标准是：

1. evidence bundle 可直接给 verdict 和前端用
2. 时间线像传播链，而不是新闻列表
3. 至少 2 条 case 能稳定说明“为什么这些节点被选中”

## 10. 交付物

你结束时必须明确给出：

1. evidence bundle 示例
2. 来源独立性 / 去重 / 冲突规则说明
3. 时间线样例输出
4. 推荐的传播链 case 列表
