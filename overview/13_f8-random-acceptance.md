# F8 随机 case 与稳定 demo 最终验收记录

更新时间：2026-03-14 21:46（Asia/Shanghai）
对应窗口：`T-random-acceptance` / `Cluster-F / Quality Gate / F8`
原始结果：`overview/13_f8-random-acceptance.raw.json`

> 注：本文件记录的是 `2026-03-14` 历史验收快照。当时默认样本运行在 `analysis_provider=kimi`、`retrieval_provider=mock`、`retrieval_fallback_to_mock=true` 的环境上。自 `2026-03-15` 起，仓库冻结的默认开发/演示基线已调整为 `ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`；如需复现本页结果，请以这里记录的历史环境为准。

## 1. 验收口径

本轮沿用 `tasks/cluster-c-api-foundation.md` 中 `C11` 冻结的 provenance 口径：

- `source_type=backend_live` 且 `evidence_source=retrieval_live`：记为真实后端 + 真实检索路径。
- `source_type=backend_mock / backend_replay`，或 `evidence_source=retrieval_mock / request_mock`：记为 mock / replay / 联调路径。
- `evidence_source=none` 或 `fallback_used=true`：记为保守降级路径，不能记作“已较真成功”。

当前默认环境快照：

- `analysis_provider=kimi`
- `kimi_enabled=true`
- `retrieval_provider=mock`
- `retrieval_fallback_to_mock=true`

## 2. 基线测试结果

- `pytest backend/tests/test_api.py -q`：`16 passed`
- `pytest backend/tests/test_retrieval.py -q`：`15 passed`
- `pytest backend/tests/test_kimi_provider.py backend/tests/test_kimi_provider_quality.py -q`：`6 passed`

结论：接口、retrieval 单测和 provider 质量测试都能过，但这只能证明“当前实现可回归”，不能替代 `F8` 的随机样本最终验收。

## 3. 样本范围

- 稳定 demo：3 条，按当前 `.env` 默认环境运行。
- 随机样本：9 条，覆盖文本 / question / URL，按当前 `.env` 默认环境运行。
- live probe：4 条，强制 `RETRIEVAL_PROVIDER=gdelt` 且 `RETRIEVAL_FALLBACK_TO_MOCK=false`，专门检查是否能拿到 `backend_live + retrieval_live`。

总样本数：`16`

## 4. 结果总览

| 批次 | 环境 | 样本数 | mode 分布 | provenance 归类 | 结论 |
| --- | --- | ---: | --- | --- | --- |
| `default_env_demo` | 当前 `.env` | 3 | `complete 2 / safe 1` | `mock_or_replay 3` | 稳定 demo 只复现了 mock 路径，且 2 条 demo 发生模式漂移。 |
| `default_env_random` | 当前 `.env` | 9 | `safe 8 / partial 1` | `mock_or_replay 9` | 随机样本全部落在 `backend_mock`，没有真实检索样本。 |
| `gdelt_live_probe` | `gdelt` + 禁止 mock fallback | 4 | `safe 4` | `fallback_or_none 4` | 4 条样本全部未拿到 `retrieval_live`，都因 `real_retrieval_failed` 停在保守路径。 |

汇总分布：

- `mode`：`complete_mode 2 / partial_mode 1 / safe_mode 13`
- provenance 归类：`real_live 0 / mock_or_replay 12 / fallback_or_none 4`
- `source_type`：`backend_mock 12 / backend_live 4`
- `evidence_source`：`retrieval_mock 3 / none 13`
- `fallback_reason`：`real_retrieval_failed 4 / url_content_incomplete 1 / url_fetch_failed 1`

## 5. 稳定 demo case 明细

| demo | 预期口径 | 实测结果 | 判定 |
| --- | --- | --- | --- |
| `expired-yogurt` | `complete_mode`，适合作为完整链路演示 | `complete_mode`，但 provenance=`backend_mock + retrieval_mock` | 仅可讲“稳定 mock demo 通过”，不能讲真实检索通过。 |
| `chemical-odor` | `partial_mode`，应展示冲突证据 | 实测落到 `safe_mode`，`evidence_source=none`，只剩输入种子时间线 | 失败样本。当前不能把它继续当作稳定 partial demo。 |
| `morningstar-layoff` | `safe_mode`，应展示证据不足 | 实测变成 `complete_mode`，provenance=`backend_mock`，`provider_used=true`，主结论变成“晨星生物已宣布裁员40%” | 高风险失败样本。当前不能把它当作安全模式 demo 讲。 |

说明：当前最危险的不是“没有结果”，而是 `morningstar-layoff` 这类本该保守收口的样本被抬到了 `complete_mode`。

## 6. 随机样本分布与代表性样本

### 6.1 当前默认环境（`retrieval_provider=mock`）

- 文本 4 条：`safe 3 / partial 1`，全部 `backend_mock`。
- Question 2 条：`safe 2`，全部 `backend_mock`。
- URL 3 条：`safe 3`，全部 `backend_mock`；其中 2 条触发 URL fallback。
- 没有任何一条样本拿到 `backend_live + retrieval_live`。

代表性样本：

- `KP03 / 清河水库`：唯一落到 `partial_mode` 的随机文本，但 provenance 仍是 `backend_mock + retrieval_mock`，只能算 mock 路径可回归，不能算真实检索已打通。
- `KP01 / 滨海地铁`：停在 `safe_mode`，标题退化成“热搜截图”，说明开放文本在默认 mock 检索下仍容易停在保守结果。
- `example-url`：URL 抽取成功到 `Example Domain`，但仅触发 `url_content_incomplete`，仍停在 `safe_mode`。
- `broken-pdf-url`：URL 直接触发 `url_fetch_failed`，只能保守输出。

### 6.2 live probe（`gdelt`，禁止 mock fallback）

- 4 条 probe 全部是 `backend_live`，但全部 `evidence_source=none`、`fallback_used=true`、`fallback_reason=real_retrieval_failed`。
- 实测没有观察到任何 `retrieval_live`，所以本轮真实路径通过数是 `0/4`。

代表性失败：

- `kp03-live-probe`：文本输入进入 `backend_live`，但 live retrieval 因 `real_retrieval_failed` 直接退回 `safe_mode`。
- `viral-death-live-probe`：question 样本虽然 provider 产出了事件标题，但检索仍失败，没有证据、没有时间线。
- `gov-home-live-probe`：URL 抽取能成功拿到标题，但下游 `gdelt` 返回异常内容，最终仍是 `safe_mode`。

运行期观察到的外部失败信号：

- `gdelt` 侧出现 `ConnectError`、`HTTP 429 Too Many Requests` 和 `JSONDecodeError`。
- `kimi_provider` 在随机批次中多次出现 `ReadTimeout`，随后回落到规则路径。

## 7. 给 G3 / G4 复用的口径与风险表

### 能讲什么

- 可以讲：当前后端测试基线是稳定的，API / retrieval / provider 回归都能跑通。
- 可以讲：`expired-yogurt` 仍可作为“稳定 mock demo”演示完整结构化输出。
- 可以讲：系统已经能用 provenance 明确区分 `backend_mock`、`backend_live` 和 fallback，不再把保守结果伪装成真实较真成功。

### 不能讲什么

- 不能讲：当前三条稳定 demo 都已在真实检索路径上通过。实际只有 mock 路径在工作，且 2 条 demo 已漂移。
- 不能讲：当前随机输入已经验证了“任意新闻可较真”。本轮 `real_live` 样本数是 `0`。
- 不能讲：`morningstar-layoff` 仍然是安全模式 demo。当前默认环境下它会被抬成 `complete_mode`。

### 风险表

| 风险 | 证据 | 影响 | 建议回提 |
| --- | --- | --- | --- |
| 默认环境检索仍是 `mock` | 当前 `.env` 快照 `retrieval_provider=mock` | 默认演示和随机输入都不能代表真实检索 | `Cluster-G / G3/G4` 文档必须明确写成 mock/demo 边界 |
| `chemical-odor` demo 漂移到 `safe_mode` | `DEMO02` 实测 `safe_mode` | 不能继续按 partial demo 口播 | `Cluster-C / Cluster-D` 复核该样本的检索与 verdict 收口 |
| `morningstar-layoff` 由 safe 漂移到 complete | `DEMO03` 实测 `complete_mode` | 会把本该保守的演示讲成确定性结论 | `Cluster-C` 优先回看 question + provider + mock retrieval 组合边界 |
| live retrieval 未验收通过 | `gdelt_live_probe` 为 `0/4 real_live`，全部 `real_retrieval_failed` | 不能对外宣称真实检索链路已收口 | `Cluster-D` 优先处理 live retrieval 可用性、限流与异常响应 |
| provider 在线批次存在超时 | 随机批次运行期多次 `kimi_provider_failed ... ReadTimeout` | 开放输入帮助性不稳定，且会悄悄回到规则链路 | `Cluster-C / C9` 继续做 provider 超时与帮助性验收 |

## 8. 本轮结论

- `F8` 的正式验收记录已落库，但结论不是“真实路径通过”，而是“mock/demo 路径可记录，真实检索路径未通过最终验收”。
- 当前可以进入 `G3 / G4` 的，是一份带 provenance 边界的真实说明，而不是“主链已经能对随机新闻稳定较真”的宣传口径。
- 如果今天要演示，最保守的 go/no-go 结论是：
  - `Go / 讲 mock demo + 边界`：可以。
  - `No-Go / 讲真实检索较真`：当前不可以。

## 9. 建议交接

- `Cluster-G / G3 / G4`：直接复用本文件的“能讲什么 / 不能讲什么”和风险表，更新 README、口播和交付文档。
- `Cluster-D`：优先修 live retrieval 的 `ConnectError / 429 / JSONDecodeError`，否则 `backend_live + retrieval_live` 无法形成正式通过样本。
- `Cluster-C`：优先复核 `chemical-odor` 与 `morningstar-layoff` 的模式漂移，避免 demo 边界继续失真。
