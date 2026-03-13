# Contract Forge Implementation Record

## 1. 这份文档是干什么的

这份文档记录 `Cluster-B / Contract Forge` 当前已经落地的共享协议设计。

它主要覆盖已经完成的 `B1 ~ B5`：

- `Event` schema
- `TimelineNode` schema
- `ClaimResult` schema
- `Report` schema
- 三份稳定 demo payload

它不试图替代 schema 文件本身，而是解释：

- 为什么这些字段这样设计
- 前后端现在怎么消费它们
- 哪些字段是后续修改时不能随便漂移的

## 2. 当前结论

`contracts/` 已经是当前仓库里事实上的共享协议源头。

当前前后端的协作方式不是“后端先写模型，前端再猜着接”，而是：

1. `contracts/*.schema.json` 固定结构边界
2. 后端用 `backend/app/models/schemas.py` 镜像运行时模型
3. 前端用 `frontend/types/report.ts` 镜像消费类型
4. `contracts/demo_payloads/*.json` 提供离线演示和三档模式基线

## 3. 当前用了什么框架

| 层级 | 当前做法 | 落点 | 作用 |
| --- | --- | --- | --- |
| 协议定义 | JSON Schema Draft 2020-12 | `contracts/*.schema.json` | 固定字段名、枚举、数组结构和基本格式 |
| 后端镜像模型 | Pydantic v2 | `backend/app/models/schemas.py` | 运行时验证请求、内部模型和返回结构 |
| 前端镜像类型 | TypeScript interface/type | `frontend/types/report.ts` | 约束页面消费的 `Report` 结构 |
| 演示资产 | 本地 JSON payload | `contracts/demo_payloads/*.json` | 提供 complete / partial / safe 三档稳定结果 |

## 4. 当前目录结构

```text
contracts/
  event.schema.json
  timeline_node.schema.json
  evidence.schema.json
  claim_result.schema.json
  report.schema.json
  demo_payloads/
    complete_mode_report.json
    partial_mode_report.json
    safe_mode_report.json
```

## 5. 当前实际完成了什么

## 5.1 `B1` `Event` schema

当前 `Event` 已固定为：

- `title`
- `summary`
- `source_url`
- `source_name`
- `published_at`
- `keywords`
- `mode`

这里有两个关键设计：

1. `published_at` 要求是 `date-time`
   这样前后端可以统一当成时间字段处理，而不是把日期字符串再二次猜格式。

2. `mode` 不只放在 `Report` 顶层，也保留在 `Event`
   这样前端在只拿事件对象时，也能知道当前事件是 `complete / partial / safe` 哪种上下文。

## 5.2 `B2` `TimelineNode` schema

当前 `TimelineNode` 重点固定了两类信息：

- 结构字段：`node_type / title / url / source_name / published_at`
- 解释字段：`summary / why_selected`

这里的核心不是“把一个时间点画出来”，而是让时间线节点本身带解释能力。

也就是说，当前时间线对象不是纯 UI 点位，而是要能回答：

- 这是什么节点
- 来自哪里
- 为什么它会出现在时间线里

## 5.3 `B3` `ClaimResult` + `Evidence` schema

当前 `ClaimResult` 里最重要的约束有 3 个：

1. `claim_type` 固定为：
   `fact / opinion / prediction / unverifiable`

2. `verdict` 固定为：
   `supported / refuted / insufficient / conflicting`

3. `confidence` 同时允许：
   - 枚举等级：`high / medium / low`
   - 数值：`0 ~ 1`

第三点是当前 contract 里最重要的“为后续演进留口”设计之一。

原因是：

- 当前规则链路更适合直接给 `high / medium / low`
- 后续如果接更细的 provider 或评分器，可能直接输出 `0 ~ 1`

因此 contract 先把两者都留出来，避免后续又改字段名。

`Evidence` 被单独拆成 schema，而不是只作为匿名内联对象，目的是：

- 让 `ClaimResult.evidence[]` 和 `Report.sources[]` 复用同一结构
- 避免“每个地方都拷一份长得像但不完全一样的证据对象”

## 5.4 `B4` `Report` schema

当前 `Report` 已固定为 7 个根字段：

- `mode`
- `event`
- `timeline`
- `claim_results`
- `final_summary`
- `risks`
- `sources`

这里最重要的设计决定有两个：

1. 返回的是裸 `Report`
   当前后端接口不再包一层 `{ request_id, report }`。

2. 顶层保留 `sources`
   这样页面可以同时渲染：
   - 每条 claim 自己的局部证据
   - 整份报告的全局来源池

## 5.5 `B5` 三份 demo payload

当前 demo payload 不是任意 mock，而是明确对应三档模式：

- `complete_mode_report.json`
- `partial_mode_report.json`
- `safe_mode_report.json`

它们的主要职责不是测试后端接口，而是：

- 作为前端离线 fallback 的稳定结果
- 作为三档模式的视觉和字段基线
- 让联调失败时仍然能演示页面结构

## 6. 当前前后端是怎么消费这些 contract 的

## 6.1 后端消费方式

后端没有直接在运行时去解析 JSON Schema。

当前做法是：

- 用 `Pydantic` 定义镜像模型
- 输出结构主动对齐 contract
- 通过测试保护关键顶层字段不漂移

关键落点：

- `backend/app/models/schemas.py`
- `backend/tests/test_api.py`

## 6.2 前端消费方式

前端同样不直接把 JSON Schema 喂给运行时组件。

当前做法是：

- 用 `frontend/types/report.ts` 镜像 `Report` 及其子结构
- `frontend/lib/api-client.ts` 在请求返回后做保守解析
- `frontend/lib/demo-cases.ts` 直接消费 `contracts/demo_payloads/*.json`

这里的关键点是：

- JSON Schema 负责“定义边界”
- TS 类型负责“页面消费”
- parser 负责“联调期防御性收口”

## 7. 当前 contract 的设计原则

## 7.1 字段名优先稳定，不追求过度抽象

当前字段名都比较直白，例如：

- `claim_results`
- `final_summary`
- `why_selected`
- `source_tier`

这样做是为了减少前后端和 AI 接手时的解释成本。

## 7.2 允许空数组，不允许缺根字段

当前大量数组字段都允许默认空数组，例如：

- `timeline`
- `claim_results`
- `risks`
- `sources`
- `evidence`

但根字段本身不允许缺失。

这对前端非常重要，因为它能避免：

- 页面到处写 `?.`
- 一部分数据是“字段不存在”，另一部分是“字段存在但为空”的混乱情况

## 7.3 三档模式是 contract 内建概念

`complete_mode / partial_mode / safe_mode` 不是只存在于前端 UI 的状态词，而是共享协议的一部分。

这意味着：

- 后端要显式产出 mode
- 前端要按 mode 渲染
- demo payload 也必须覆盖三档模式

## 8. 当前最容易误解的点

1. `contracts/` 虽然是 schema 源头，但当前没有自动代码生成链。
   现在仍然是“手工同步的镜像约束”。

2. `Report.sources` 和 `ClaimResult.evidence` 不是重复字段。
   前者是全局来源池，后者是 claim 级局部证据。

3. `confidence` 允许数字不代表后端已经在大量输出数字评分。
   这更多是在为后续能力预留空间。

## 9. 当前还没完成的 contract 工作

按任务文件来看，`B6 / B7` 还没真正完成：

- 字段语义说明仍分散在前后端实现文档里
- schema 变更流程还没有正式制度化

所以当前 contract 层已经“能用”，但还没有完全进入“可治理”状态。

## 10. 后续修改建议

如果后续要改 contract，建议按下面顺序做：

1. 先改 `contracts/*.schema.json`
2. 再同步 `backend/app/models/schemas.py`
3. 再同步 `frontend/types/report.ts`
4. 再检查 `contracts/demo_payloads/*.json`
5. 最后补前后端测试

如果跳过第 1 步，最容易出现“实现层偷偷长出事实新字段，但 contract 没更新”的漂移。

## 11. 一句话结论

当前 `Cluster-B` 已经把共享协议、三档模式和 demo payload 的基础盘搭好了；后续的关键不是再造一套 schema，而是继续围绕这套 contract 维持一致性和变更纪律。
