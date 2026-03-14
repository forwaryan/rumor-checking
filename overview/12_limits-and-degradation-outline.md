# 12 当前限制与降级边界

更新时间：2026-03-14 21:46（Asia/Shanghai）
对应验收：`overview/13_f8-random-acceptance.md`

## 1. 这份文档的定位

这份文档是当前限制与降级边界的终稿，不再保留骨架式占位。

它只处理一件事：把当前能讲什么、不能讲什么，以及 live / mock / replay / fallback 的边界一次写清，避免 README、Smoke、口播脚本各讲一套。

## 2. 当前可以讲什么

- 可以讲：后端测试基线稳定，`health`、API、retrieval 基础测试和 provider 基础测试都有通过记录。
- 可以讲：页面已经能区分 `backend_live / backend_mock / backend_replay / demo_payload / frontend_fallback`，不会把本地 fallback 伪装成 live 结果。
- 可以讲：`expired-yogurt` 仍可作为稳定 mock demo 演示完整结构化输出。
- 可以讲：系统已经能把保守路径标记出来，`fallback_used=true` 或 `evidence_source=none` 不会再被当成“已较真成功”。

## 3. 当前不能讲什么

- 不能讲：当前随机输入已经验证了“任意新闻都能较真”。`F8` 的 `real_live` 样本数是 `0`。
- 不能讲：三条稳定 demo 都已在真实检索路径上通过。当前默认环境主要还是 `mock` 路径。
- 不能讲：`chemical-odor` 仍是稳定 `partial_mode` demo。它在 `F8` 中已漂移到 `safe_mode`。
- 不能讲：`morningstar-layoff` 仍是稳定 `safe_mode` demo。它在 `F8` 中已漂移到 `complete_mode`。
- 不能讲：frontend fallback、demo payload 或 mock retrieval 等同于实时联网分析结果。

## 4. `live / mock / replay / fallback` 判定方式

| 分类 | 判定方式 | 当前怎么讲 |
| --- | --- | --- |
| `live` | `source_type=backend_live` 且 `evidence_source=retrieval_live` 且没有 fallback | 只有满足这组条件，才可以说拿到了真实后端 + 真实检索路径 |
| `mock` | `source_type=backend_mock`，或 `evidence_source=retrieval_mock / request_mock` | 这是当前默认联调和稳定 demo 的主要路径，只能讲 mock/demo 能力 |
| `replay` | 后端显式返回 `source_type=backend_replay` | 当前没有公开 replay 接口，因此不是默认交付路径 |
| `fallback` | `fallback_used=true`、`evidence_source=none`，或前端进入 `demo_payload / frontend_fallback` | 只能讲保守降级或保底演示，不能讲“已经核查成功” |

## 5. `complete / partial / safe_mode` 的当前讲法

### `complete_mode`

- 只表示当前链路给出了相对完整的结构化结果。
- 如果 provenance 仍是 `backend_mock` 或 `retrieval_mock`，它也不能被讲成真实检索通过。
- `morningstar-layoff` 当前默认环境下会漂移到 `complete_mode`，这说明 mode 本身不能脱离 provenance 单独宣称能力。

### `partial_mode`

- 适合讲“部分结果可用、但冲突仍需保留”。
- 当前没有通过 `F8` 重新验证的稳定 partial demo，因此不要把 `chemical-odor` 继续当作默认演示素材。
- 如果后续要恢复 partial 演示，必须先由实现窗口复核并重新验收。

### `safe_mode`

- 只表示当前证据不足、输入不完整或链路发生保守回退。
- 它不代表传闻为假，也不代表系统已经完成了全网搜索。
- URL 抽取失败、live retrieval 失败、provider 超时等场景都可能把结果推回 `safe_mode`。

## 6. 输入与主链边界

- 文本输入：当前能走完整 analyze 主链，但默认环境下仍多落在 `mock` 路径。
- 问题输入：可以触发后端主链，但在默认环境和 live probe 中都还没有形成稳定的真实检索通过样本。
- URL 输入：只支持公开 HTML 页面；登录页、强反爬、浏览器渲染页面、PDF 和图片正文都仍会触发保守路径。
- verdict、evidence、timeline 仍是基于当前检索结果和规则链路的 V1 组合，不应讲成完整 RAG 或 agent 搜证系统。

## 7. 当前降级层级

1. `backend_live + retrieval_live`
   当前尚未形成正式通过样本，不能作为默认对外交付口径。
2. `backend_mock / retrieval_mock`
   当前最稳定的联调与 demo 路径，可交付但必须明确说明是 mock/demo。
3. `backend_replay`
   只保留为后端显式产物，不作为公开启动方式。
4. `demo_payload`
   前端演示用的本地稳定 payload，只用于保住 demo 结构。
5. `frontend_fallback`
   后端不可达或请求失败时的保守 `safe_mode` 报告壳，只说明页面降级成功。

## 8. `F8` 暴露的主要风险与临时规避

| 风险 | 证据 | 当前影响 | 临时规避 |
| --- | --- | --- | --- |
| 默认环境 retrieval 仍是 `mock` | `F8` 默认快照 `RETRIEVAL_PROVIDER=mock` | 默认演示和随机输入都不能代表真实检索 | README、Smoke、口播统一写成 mock/demo 边界 |
| `chemical-odor` 漂移到 `safe_mode` | 稳定 demo 明细里 `DEMO02` 失败 | 不能继续当 partial demo 使用 | 从默认演示主线移除，待实现窗口复核 |
| `morningstar-layoff` 漂移到 `complete_mode` | 稳定 demo 明细里 `DEMO03` 高风险失败 | 会把本该保守的 case 误讲成确定性结论 | 从默认演示主线移除，禁止作为 safe demo 口播 |
| live retrieval 未通过验收 | `gdelt_live_probe` 为 `0/4 real_live` | 当前不能讲真实检索较真 | 只保留为内部 probe，不纳入对外通过口径 |
| provider 在线批次存在超时 | 随机批次多次 `ReadTimeout` | 开放输入帮助性不稳定，且会悄悄回到规则链路 | 对外交付时不要把 provider 打开讲成稳定增益 |

## 9. 当前 go / no-go 结论

- `Go / 讲 mock demo + 边界`：可以。
- `Go / 讲 frontend fallback 是保底演示`：可以，但必须明确说明不是 live 结果。
- `No-Go / 讲真实检索较真已经稳定通过`：当前不可以。

## 10. 一句话结论

截至 2026-03-14，当前系统已经具备“路径清楚、边界明确、mock/demo 可交付”的 V1 形态，但真实检索链路仍未通过 `F8` 最终验收，因此任何对外说明都必须把 live 能力与降级/演示路径明确拆开。
