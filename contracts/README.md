# Contracts

本目录是前后端共享协议的唯一落点。

更新时间：2026-03-26（Asia/Shanghai）

## 当前内容

- `event.schema.json`
- `timeline_node.schema.json`
- `evidence.schema.json`
- `claim_result.schema.json`
- `report.schema.json`

## 当前约束

- 任何会影响前端渲染、后端响应、测试断言的字段结构，都应该先在这里冻结
- `report.provenance.source_type` 当前 contract 只保留 `backend_live` 和 `backend_mock`
- 本地 demo payload 已移除，因为当前前端运行时不再消费这类 JSON 资产

## 协作说明

- schema 变更后，需要同步检查 [schemas.py](/home/forwaryan/mianshi/rumor-checking/backend/app/models/schemas.py) 和 [report.ts](/home/forwaryan/mianshi/rumor-checking/frontend/types/report.ts)
- 不要绕过这里在实现文件里直接新增“事实上的新字段”
