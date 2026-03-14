# Minimal V1 Test Set

这是一套**开发期最小测试集**，目标不是模拟最终复试总评分，而是帮助你在开始编码时，先把当前 V1 的核心链路跑稳。

它遵循当前项目已经冻结的目标：

- 输入：新闻 URL / 新闻文本 / `XXX 是真的吗`
- 输出：
  - 当前模式
  - 一句话结论
  - 3 到 5 条 claim 核查表
  - 5 到 10 个关键时间线节点
  - 证据列表
- 硬边界：
  - 不乱判
  - 允许 `supported / refuted / insufficient / conflicting`
  - 允许部分模式和安全模式

## 1. 为什么这套测试集是“最小”的

它只覆盖 5 件当前最关键的事：

1. 输入标准化
2. claim 类型分类
3. verdict 生成
4. 检索结果筛选与时间线候选识别
5. 报告模式选择

它不追求：

- 大规模 benchmark
- 真实全网检索结果稳定复现
- 生产级覆盖率

## 2. 文件说明

- `input_cases.json`
  - 给 `input_normalizer` 使用
- `claim_classification_cases.json`
  - 给 `claim_extractor` / `claim_classification` 使用
- `verdict_cases.json`
  - 给 `evidence_selection` / `verdict_engine` 使用
- `retrieval_cases.json`
  - 给 `retriever` / `timeline_builder` 使用
- `report_mode_cases.json`
  - 给 `report_builder` 或页面模式切换使用
- `provider_text_news_cases.json`
  - 给 `C9` 的 Kimi provider 文本新闻小样本验收使用，重点看标题、摘要和 claim 帮助性是否优于 `ANALYSIS_PROVIDER=off`

## 3. 使用建议顺序

建议按下面顺序开始接：

1. 先跑 `input_cases.json`
2. 再跑 `claim_classification_cases.json`
3. 再跑 `verdict_cases.json`
4. 再跑 `retrieval_cases.json`
5. 最后跑 `report_mode_cases.json`

## 4. 通过线建议

### 4.1 输入标准化

- 6 条 case 中至少 5 条能输出非空事件对象
- `url_unknown` 不允许直接崩溃，必须进入 fallback
- `question_only` 不允许伪造来源和发布时间

### 4.2 Claim 分类

- 6 条 case 至少 5 条分类正确
- `opinion` 与 `prediction` 不能被系统性错判成 `fact`

### 4.3 Verdict

- 8 条 case 至少 7 条 verdict 方向正确
- 不允许出现“无足够证据却输出 supported/refuted”

### 4.4 检索与时间线

- 4 条 retrieval case 中至少 3 条能识别高可信来源
- 至少 3 条能给出 origin 候选
- 至少 2 条能给出 turning point 候选

### 4.5 报告模式

- 4 条 case 都应进入预期模式
- `safe_mode` 不能出现确定性强结论
- `partial_mode` 不能伪装成完整传播链

## 5. 这套测试集的定位

这套数据最适合：

- 本地单元测试
- 开发早期回归测试
- Prompt / schema 变更后快速复测
- `C9` provider 调优后的文本新闻帮助性对照验收

它不替代后续的：

- 随机新闻 live case 评测
- 公开 benchmark 评测
- 最终人工答辩评分

