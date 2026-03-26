# Contract Forge Implementation Record

更新时间：2026-03-26（Asia/Shanghai）

## 这份文档记录什么

这份文档记录 `contracts/` 当前仍在生效的共享协议边界，以及它和前后端实现的对应关系。

## 当前结论

`contracts/` 仍是仓库里的共享协议源头，但范围已经收敛为运行时真正会消费的 schema：

1. `contracts/*.schema.json` 固定字段结构
2. 后端用 `backend/app/models/schemas.py` 镜像运行时模型
3. 前端用 `frontend/types/report.ts` 镜像消费类型

此前用于本地回放的 `contracts/demo_payloads/*.json` 已移除，因为当前前端不再消费本地报告 JSON，也没有公开 replay 路径。

## 当前目录结构

```text
contracts/
  event.schema.json
  timeline_node.schema.json
  evidence.schema.json
  claim_result.schema.json
  report.schema.json
```

## 当前保留的核心协议

### `Event`

- `title`
- `summary`
- `source_url`
- `source_name`
- `published_at`
- `keywords`
- `mode`

### `TimelineNode`

- `node_type`
- `title`
- `url`
- `source_name`
- `published_at`
- `summary`
- `why_selected`

### `ClaimResult` + `Evidence`

- `claim_type` 固定为 `fact / opinion / prediction / unverifiable`
- `verdict` 固定为 `supported / refuted / insufficient / conflicting`
- `confidence` 同时允许枚举等级和 `0 ~ 1` 数值
- `Evidence` 继续复用到 `ClaimResult.evidence[]` 和 `Report.sources[]`

### `Report`

当前 `Report` 仍固定为运行时真正需要的结构，包括：

- `mode`
- `event`
- `timeline`
- `claim_results`
- `final_summary`
- `risks`
- `sources`
- `retrieval_hits`
- `provenance`

其中 `report.provenance.source_type` 当前只保留：

- `backend_live`
- `backend_mock`

## 当前前后端如何消费

### 后端

- 运行时不直接解析 JSON Schema
- 通过 `backend/app/models/schemas.py` 镜像 contract
- 通过测试保护关键字段不漂移

### 前端

- 运行时不直接解析 JSON Schema
- 通过 `frontend/types/report.ts` 镜像 `Report` 及其子结构
- 通过 `frontend/lib/api-client.ts` 做保守解析

## 修改顺序建议

如果后续要改 contract，建议按下面顺序：

1. 先改 `contracts/*.schema.json`
2. 再同步 `backend/app/models/schemas.py`
3. 再同步 `frontend/types/report.ts`
4. 最后补前后端测试
