# 演示脚本与口播提纲

更新时间：2026-03-14（Asia/Shanghai）

## 1. 这份文档给谁用

这份文档给两类人用：

- 第一次接手这个仓库、需要快速准备 demo 的人
- 面试现场负责口播和操作的人

目标不是把实现讲全，而是把当前已经通过 `F8` 验收的讲法说准确。

## 2. 先记住一句话介绍

> 这是一个新闻核查工作台。当前我们稳定交付的是 mock/demo 路径下的结构化核查演示，以及 live / mock / fallback 边界的清晰展示，而不是“真实检索已对随机新闻稳定较真”。

## 3. 演示前先说明的边界

正式操作前，建议先主动说明这 5 点：

- 当前最稳的是 `expired-yogurt` 这条 mock demo，不是三条 demo 全部稳定通过。
- 前端会优先调用真实 `POST /api/v1/analyze`；如果后端离线或请求失败，会回退到本地 `demo_payload` 或 `frontend_fallback`。
- `complete / partial / safe_mode` 必须结合 provenance 一起讲，不能只看 mode 名称。
- 默认环境下 retrieval 仍主要是 `mock`，不能把今天的演示讲成真实检索已经通过最终验收。
- live probe 在 `F8` 中是 `0/4 real_live`，所以今天不能承诺“任意新闻都能真实较真”。

## 4. 推荐的 5 到 8 分钟演示顺序

| 时间 | 操作 | 口播重点 |
| --- | --- | --- |
| 0:00 - 0:40 | 打开页面，说明输入方式和来源标签 | “今天重点演示 mock/demo 路径，以及系统如何把 live、mock、fallback 分开标识。” |
| 0:40 - 3:30 | 演示 `expired-yogurt` | 先建立信任：结构化结果完整、claim 和时间线可读，但 provenance 仍要按 mock 路径讲。 |
| 3:30 - 5:30 | 展示来源标签和边界 | 解释 `backend_mock / backend_live / demo_payload / frontend_fallback` 的区别，强调 mode 不能脱离 provenance 讲。 |
| 5:30 - 6:30 | 可选展示一次 fallback | 后端离线时说明 demo payload 或 `safe_mode` 保底，不把它说成真实联网结果。 |
| 6:30 - 8:00 | 主动讲当前 no-go 边界 | 说明 `chemical-odor`、`morningstar-layoff` 已漂移，live retrieval 还没过 `F8`。 |

## 5. 当前推荐 demo：`expired-yogurt`

### 输入

```text
3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。
```

### 建议操作顺序

1. 先看状态条和来源标签，说明当前是可交付的 mock/demo 路径。
2. 再看事件卡片，讲“一句话总结 + 关键词”。
3. 然后看时间线，点出关键节点。
4. 最后看 claim 表和证据列表，说明哪些说法有支持、哪些仍是边界提示。

### 推荐讲法

> 这条 case 用来演示系统在当前稳定路径下怎么把一段新闻拆成结构化结果。它能给出事件摘要、claim、时间线和风险提示，同时页面会明确告诉你这次结果来自哪条路径，避免把 mock 或 fallback 误看成 live 检索通过。

### 不要说过头的地方

- 不要说“这已经证明真实互联网检索稳定通过”。当前默认环境主要还是 mock 路径。
- 不要把时间线节点讲成“完整传播链还原”。当前更接近可展示的关键节点摘要。
- 不要把 provenance 省略掉，只讲 `complete_mode`。

## 6. 当前不应放进默认主线的两个 case

### `chemical-odor`

- `F8` 中已从预期 `partial_mode` 漂移到 `safe_mode`。
- 当前不能继续把它当作稳定 partial demo 使用。
- 如果必须展示，只能先说明这是待复核样本，不是通过样本。

### `morningstar-layoff`

- `F8` 中已从预期 `safe_mode` 漂移到 `complete_mode`。
- 当前存在把本该保守的 case 讲成确定性结论的风险。
- 演示主线里不要使用它。

## 7. 如果被追问，建议怎么答

**Q：你们现在已经能查任意新闻了吗？**

建议回答：

> 还不能这么说。当前正式验收通过的是 mock/demo 路径和边界展示能力；真实检索链路在 `F8` 的 live probe 里还没有通过最终验收。

**Q：现在的 verdict 是真实证据驱动的吗？**

建议回答：

> 不能一概这么说。当前要同时看 mode 和 provenance：默认演示仍主要是 mock 路径，只有出现 `backend_live + retrieval_live` 时，才可以讲成真实后端加真实检索。

**Q：如果后端挂了，为什么页面还可以演示？**

建议回答：

> 当前前端是“真实 analyze 优先、demo payload 和 frontend fallback 保底”。这能保证页面结构和边界讲法稳定，但不等于真实链路已经全部完成。

## 8. 一句话结论

截至 2026-03-14，最稳的演示主线是：`expired-yogurt` + provenance 边界 + fallback 说明；不再沿用“三条稳定 demo 全部通过”或“真实检索已收口”的旧口径。
