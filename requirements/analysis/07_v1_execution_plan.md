# V1 开工执行清单

## 1. 结论先行

下一步不再继续扩写泛分析，而是正式进入“实现前冻结 + 三项验证 + 最小骨架”阶段。

当前最优开工顺序只有三步：

1. 先冻结内容核查、传播链、失败处理三份硬规则
2. 再做输入、检索、verdict 三个技术验证
3. 验证通过后，再搭最小可跑骨架

## 2. 这周必须完成的 4 项交付物

### 2.1 规则冻结

必须冻结以下规则文件：

- `rules/evidence_and_verdict_rules.md`
- `rules/propagation_chain_rules.md`
- `rules/failure_handling_rules.md`

完成标准：

- claim 类型、evidence 字段、verdict 标签固定
- 传播链节点与边界固定
- 失败 fallback 和模式切换固定

### 2.2 输入验证

目标：确认随机新闻输入是否能被稳定接住。

最小任务：

- 选 10 条标准新闻 URL
- 选 5 条抽取不稳定 URL
- 选 5 条直接粘贴文本

要验证：

- 标题/正文/时间/来源抽取成功率
- 抽取失败时能否安全降级

### 2.3 检索验证

目标：确认系统是否能拿到“足够像核查证据”的公开来源。

最小任务：

- 选 10 个事件 query
- 每个 query 检查：
  - 能否召回多篇相关文章
  - 能否召回较高可信来源
  - 能否为传播链提供最早来源与转折节点

### 2.4 Verdict 验证

目标：确认 verdict 能否稳定落在可控边界内。

最小任务：

- 选 10 条 claim
- 覆盖：
  - supported
  - refuted
  - insufficient
  - conflicting

要验证：

- 有没有乱判
- schema 是否稳定
- evidence 与结论能否绑定

## 3. 第一版功能冻结范围

V1 只承诺：

- 输入：新闻 URL / 新闻文本 / “XXX 是真的吗”
- 输出：
  - 一句话结论
  - 当前模式
  - 3 到 5 条 claim 核查表
  - 5 到 10 个关键时间线节点
  - 证据列表

V1 明确不做：

- 全网社交传播图
- 多模态核查
- 大规模爬虫
- 复杂知识图谱
- 模型训练

## 4. 第一批要建的模块

建议直接按下面 6 个模块拆：

1. `input_normalizer`
2. `retriever`
3. `claim_extractor`
4. `verdict_engine`
5. `timeline_builder`
6. `report_builder`

职责定义：

- `input_normalizer`
  - 输入标准化、抽取失败 fallback
- `retriever`
  - 新闻检索、证据拉取、缓存
- `claim_extractor`
  - 生成 3 到 5 条可核查 claim
- `verdict_engine`
  - claim 分类、证据筛选、verdict 输出
- `timeline_builder`
  - 关键来源时间线
- `report_builder`
  - 组装前端展示数据

## 5. 第一批最小数据协议

在开始写后端前，至少固定以下对象：

### 5.1 Event

- `title`
- `summary`
- `source_url`
- `source_name`
- `published_at`
- `keywords`

### 5.2 ClaimResult

- `claim`
- `claim_type`
- `verdict`
- `confidence`
- `evidence[]`
- `notes`

### 5.3 TimelineNode

- `node_type`
- `title`
- `url`
- `source_name`
- `published_at`
- `summary`

### 5.4 Report

- `mode`
- `event`
- `timeline[]`
- `claim_results[]`
- `final_summary`
- `risks[]`

## 6. 第一批 UI 只做一页

页面必须有：

- 输入框
- 当前模式标识
- 一句话结论
- 时间线
- claim 表
- 证据列表
- 风险提示

不需要先做多页、多导航、多主题。

## 7. 什么叫“第一里程碑完成”

只有同时满足下面条件，才算进入可演示状态：

1. 一条输入可以跑完整链路
2. 页面能展示模式、时间线、claim 表和证据
3. 证据不足时能进入部分模式或安全模式
4. 不出现“无证据却强判”
5. 至少有 3 个预设 demo case 跑通
6. 至少有 15 条随机 case 做过评测记录

## 8. 推荐线程分工

如果你开多个窗口，建议这样分：

- `T-main`
  - 盯边界、整合方案、控制 scope
- `T-impl`
  - 搭模块骨架与数据协议
- `T-research`
  - 帮检索与证据来源验证
- `T-doc`
  - README、演示口径、Prompt 资产
- `T-test`
  - 跑随机新闻评测与回归

## 9. 我建议你现在立刻做的第一件事

不是开写前端，而是先完成这两个动作：

1. 认可并冻结三份硬规则
2. 开始做输入 / 检索 / verdict 三个验证

只有这两步稳了，后面的代码骨架才不会返工。
