# 证据快照与精确引文

快照保留本轮实际取得、且最终报告引用来源的文本；它不是再次让模型生成一份“原文”，也不是对来源真实性的独立认证。

## 数据与引用

- `Report.evidence_snapshots` 按内容身份去重，保存来源 URL、可用时的最终 URL、留存文本、SHA-256、留档时间、取得方式和提取器版本。
- `page_text` 是实际抓取或缓存中的提取正文；`search_snippet` 只是检索返回的原始摘要。模型改写后的 `EvidenceItem.snippet` 不作为原文采集入口，mock 输入不冒充网页快照。
- `EvidenceItem.snapshot_id` 绑定具体快照。`quote_status=matched` 只表示 `stance_quote` 是该快照的精确连续子串；`quote_start` / `quote_end` 使用 Unicode codepoint、左闭右开区间，前端再次校验再高亮。
- `unmatched` 表示留存文本中未找到这句引文；`unavailable` 表示没有可绑定快照；`not_provided` 表示没有提供引文。无法定位不等于声明为假，定位成功也不等于引文支持声明。
- 正文中没有、仅搜索摘要中出现的引文，可以定位到摘要，但必须显示“搜索摘要”，不能升级成网页正文。来源卡及逐条核查内均可展开留存文本。

## 时间、缓存与恢复

`captured_at` 是文本进入本次留档的时间，不是网页发布时间、修改时间或缓存最初抓取时间。`acquisition` 区分 `fetched`、`cached`、`retrieved`、`restored`；缓存命中不能伪装成现场重新抓取。

快照身份由 URL、最终 URL、文本类型、提取器、文本哈希和截断标志共同决定，不包含留档时间。同一正文重复留档不因时间不同产生新的内容版本。模型校验同时检查文本哈希和快照身份。

快照随最终 Report JSON 进入现有 SQLite、流式报告事件和完成步骤检查点。已完成检查点恢复保留原快照及留档时间；旧检查点没有快照时，只能从其保留的原始检索摘要/正文恢复，并明确标注。未知旧正文提取器使用 `checkpoint-text-v1`，不假装与新抓取正文完全可比。

## 版本比较

`AnalysisRunComparison.changed_source_urls` 仅比较复核范围内、两版共同引用的同 URL、同提取器的 `page_text` 哈希集合。它与新增/移除来源、模型引文变化分开显示。

这表示“留存的提取正文发生变化”，不证明网站作者进行了修改。动态页面、提取范围和返回内容也可能变化；搜索摘要变化、提取器变更以及缺少快照都不能据此断言网页改了。未报变化也不保证截断范围外没有变化。

## 容量与访问边界

每份留存文本最多 24,000 个字符，每份报告最多 24 个快照、合计 120,000 个字符。超限不伪造定位；被截断的文本明确标记。运行内采集同样有条数与总字符上限，仅最终被引用的来源进入报告，不额外抓网页，不留 HTML、Cookie、请求头或原始模型提示。

快照沿用私有 run 链接的访问边界，不新增可枚举的全局快照接口，也不建设永久知识库。现有运行保留策略仍生效；启用检查点时，其目录也含原文，应按现有检查点存储策略管理。线上来源文本不得作为回归夹具直接提交 Git；测试使用人工编写文本。

## 验证

```bash
python -m pytest backend/tests/test_evidence_snapshots.py backend/tests/test_evidence_goals.py -q
python backend/scripts/check_contracts.py
cd frontend && npm test -- lib/__tests__/evidence-snapshot.test.ts
```

覆盖精确/伪造引文、Unicode 偏移、摘要与正文分层、容量及 URL 边界、并发上下文、完成检查点恢复、版本独立持久化及同链接正文变化。离线测试不证明真实网站可访问或在线判定准确率提高。
