# Contracts

本目录是前后端共享协议的唯一落点。

更新时间：2026-08-29（Asia/Shanghai）

## 当前内容

- `event.schema.json`
- `analyze_request.schema.json` / `mock_fetch_result.schema.json` — 分析输入及测试抓取材料；原始输入最多 100,000 字符
- `timeline_node.schema.json`
- `evidence.schema.json`
- `evidence_snapshot.schema.json` — 报告内留存文本、内容身份、取得方式与精确引文绑定
- `claim_result.schema.json`
- `report.schema.json`
- `analysis_run.schema.json` — 持久化分析任务的执行状态与最终报告
- `analysis_run_event.schema.json` — 带递增游标的流式事件封套
- `evidence_gap.schema.json` — 待补证属性和查询建议
- `analysis_recheck_request.schema.json` — 指定范围、链接和幂等键的复核请求
- `analysis_run_summary.schema.json` / `analysis_run_history.schema.json` — 同事项版本列表
- `claim_change.schema.json` / `analysis_run_comparison.schema.json` — 复核范围内的判定和证据变化

## 当前约束

- 任何会影响前端渲染、后端响应、测试断言的字段结构，都应该先在这里冻结
- `report.provenance.source_type` 当前 contract 只保留 `backend_live` 和 `backend_mock`
- 本地 demo payload 已移除，因为当前前端运行时不再消费这类 JSON 资产

## 协作说明

- schema 变更后，需要同步检查 [schemas.py](../backend/app/models/schemas.py) 和 [report.ts](../frontend/types/report.ts)
- 不要绕过这里在实现文件里直接新增“事实上的新字段”
- 运行 `python backend/scripts/check_contracts.py` 校验十六个公共模型的字段集合；CI 会执行同一检查
- JSON Schema 描述当前后端输出契约；TypeScript 可将部分字段保留为 optional，以兼容历史报告
