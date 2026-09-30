# 数据质量与评测协议

本目录说明 2026-09-13 的数据修订与评测边界。回放集有 56 个 case，组件集 `minimal_v1` 有 40 个测试条目；它们不是 96 个独立的真实新闻事件。

## 数据分工

| 目录 | 数量 | 来源与用途 | 项目分区 |
| --- | ---: | --- | --- |
| `seed` | 8 | 合成行为回归，保留故意缺日期、旧但有效的证据 | 既有回归，不作为留出集 |
| `hard` | 8 | 合成时态、实体、冲突与证据门槛对抗 | 既有回归，不作为留出集 |
| `cfever_curated` | 24 | 固定版本 CFEVER 的 8 个主题，每主题真/假/NEI 各一条 | 开发 12，留出 12，主题互斥 |
| `covid19_health_rumor_curated` | 8 | 固定 CSV 与逐条人工核验的历史健康主张 | 同疫情主题，全为开发分区 |
| `context_challenge` | 8 | 合成支持、直接反驳、非空 NEI 和同口径冲突，各两条 | 开发 4，留出 4，主题互斥 |

`metadata.split=dev` 是 CFEVER 上游分区；`metadata.evaluation_split` 是本项目分区，两者不能混称。CI 对开发分区与既有回归评分，留出集通过显式命令验收；不要根据留出集结果反复调规则，再把同一批数据称作独立验收。

健康集七条反驳、一条证据不足，全部猜反驳的基线就是 87.5%。CFEVER 中的八条上游 NEI 均没有 gold 证据，不能单靠这组衡量带干扰材料的判断能力。新增的两个非空 NEI 分别提供开放时间而不提供票价、提供机场设施而不提供航线信息；来源相关不代表足以支持命题。

## 本次修订

- `minimal_v1/V07`：把“5 人受伤”与“3 人留观”的不同统计口径，修成同一事故、截止时间及受伤总人数口径的 5 人/3 人。
- `minimal_v1/V08`：支持侧明确为全部产线；两侧采用同一截止时间。
- `minimal_v1/C06`：改为纯价值评价，避免把意见措辞包裹的事实指控整体当意见；R01 增补传播起点的实体对齐口径。
- `seed_014`：两侧明确在同一剂量和适用人群上对绝对安全命题相反。
- `seed_016`：官方声明和记者向同一机构核实属于一个信息源，使用同一 `origin_id`；两份引用是替代证明，不再要求它们凑成两个独立来源。
- `hard_005`：冲突 gold 包含双方通报，不能只引用 500 例一侧。
- 健康 `80840` 与 `81017`：校正原始 `rumor_type`，分别为 `dread` 和 `wish`。该字段表示希望/恐惧，不是真假；本项目的 verdict 另记人工标注依据。
- 健康 `80401`：从相同发布页取得完整细菌消毒比较，并为 claim 增加“对细菌消毒时”范围。保存原题、原截断片段、抽取位置、页面摘要、更新时间与当前抓取时间，不冒充不可变历史网页。
- 健康 `80840`：保留历史 `insufficient`，同时要求引用“仍需进一步证实”的材料。80406 保留上游截断标记，首句的直接否定只按当时语境评估。

旧 `cases.json` 聚合文件曾与独立 seed 文件漂移，当前以独立快照为唯一维护形式。原 seed 001–010 的删除保留；有效的体育、同向支持和机构澄清预测能力等维度通过新合成样本补充，不把旧的模糊或未采集来源的内容直接当真实 gold。

## 严格评分和隔离

协议是 `gold_claims_supplied_evidence` / `url-evidence-groups-v2`。回放直接使用标准 claim 和给定检索材料调用判定器，不测真实检索、claim 拆解或完整 Agent 执行。

`expected_claims[].evidence` 默认是一组需要全部覆盖的 URL。若有等价证明，可用 `evidence_sets`：组内 AND，组间 OR。非 `insufficient` 的已审核样本不允许空 gold；NEI 可以没有 gold，也可以要求引用说明“不足以确认”的材料。标准证据必须存在于检索快照中。

旧输出字段 `fever_score` 为兼容保留，其含义是“标签正确且完整 URL 组命中”。它不是官方逐句 FEVER：同一页面内部是否引用全部必要句子仍需原始句号定位或人工审查。CFEVER 保存原始 page/sentence 指针及完整替代组，不丢弃这些信息。

评分按规范化 claim 文本和类型匹配，不依赖输出数组顺序；缺失或额外 claim 有单独诊断。派生置信度用 `evaluation.score_confidence=false` 排除，无观测指标显示 N/A。独立性优先按 `origin_id`，没有时回退来源名，回退值只是粗略代理指标。

坏 JSON、非法类型/日期、重复 ID、丢失 gold URL 或损坏指针都必须报错。`metadata.review_status=quarantined` 的记录保留但不计分，报告显示 ID、原因、总数和计分数；全隔离集返回非零。自动运行录制的模型答案默认隔离，不能自动晋升为标准答案。审核状态 `approved` 代表记录了来源/标注审查，不代表模型答对。

CFEVER 转换器验证固定 dev 摘要，使用固定 seed 和主题轮转抽样；未核验本地 Wikipedia 内容时，生成物仍标为待审核。不能仅凭文件名声称来自固定上游。经核验的精选数据明确记录了“验证所需页句”的范围，不虚称已重算整个约 1 GB 语料库的摘要。

## 命令

```bash
python backend/scripts/audit_datasets.py
python backend/scripts/audit_datasets.py --json > artifacts/dataset-audit.json
python backend/scripts/replay_eval.py --dir evals/live_replay/cfever_curated --evaluation-split development
python backend/scripts/replay_eval.py --dir evals/live_replay/cfever_curated --evaluation-split holdout
python backend/scripts/replay_eval.py --dir evals/live_replay/context_challenge --evaluation-split holdout
```

审计检查全局 ID、文件名、公共来源信息、分区主题及引用 URL 泄漏，并报告标签分布和多数类基线。故意缺日期的样本和合法空证据 NEI 不算坏数据。`--compare-to` 拒绝不同评分协议、分区或语料摘要之间的直接对比，避免把换题或改计分方式误报成模型进步。

数据质量修复与判定能力改进分别记录：新的有效难例即使模型答错也保留；不通过提升来源等级、虚构日期、删去反证或反改正确标签来获得高分。
