# Contracts

本目录是前后端共享协议的唯一落点。

任何会影响前端渲染、后端响应、测试断言的字段结构，都应该先在这里冻结，再扩散到实现层。

详细实现说明见：`contracts/contract-forge-implementation-record.md`

## 建议内容

- `event.schema.json`
- `timeline_node.schema.json`
- `claim_result.schema.json`
- `report.schema.json`
- `demo_payloads/`

## 并行协作约束

- `Cluster-B / Contract Forge` 是本目录默认 owner
- 其他线程可以消费这里的定义，但不要绕过这里直接在实现文件里新增“事实上的新字段”
