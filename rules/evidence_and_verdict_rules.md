# 证据与 Verdict 规则

本文件定义内容核查模块的最小硬边界。目标不是让系统“看起来在核查”，而是确保：

- 有证据才判断
- 证据弱时敢于保留
- 结论与证据之间可追溯

## 1. 适用范围

本规则适用于以下阶段：

- claim 级核查
- evidence 检索后的证据筛选
- verdict 生成
- 最终综合结论生成

## 2. Claim 基本类型

每条 claim 必须先分类，再决定是否进入 verdict 流程：

- `fact`
  - 可被外部证据验证的事实性陈述
- `opinion`
  - 观点、评论、立场表达
- `prediction`
  - 推测、预判、趋势判断
- `unverifiable`
  - 当前公开证据难以直接验证的内容

规则：

- 只有 `fact` 默认进入标准 verdict 流程
- `opinion` 不应强判真假
- `prediction` 只能做风险提示，不应硬判真伪
- `unverifiable` 默认走 `insufficient`

## 3. Evidence 最小字段

每条 evidence 至少应包含：

- `title`
- `url`
- `source_name`
- `published_at`
- `snippet`
- `relevance_reason`
- `source_tier`

如果缺少 `url` 或 `source_name`，原则上不能算高质量证据。

## 4. 来源分级

### 4.1 `source_tier`

建议使用以下分级：

- `S`
  - 官方通报、原始声明、权威机构原始信息
- `A`
  - 主流媒体、专业机构、可信记者或已知高可信平台
- `B`
  - 一般新闻转载、二手整理、弱一手来源
- `C`
  - 自媒体、匿名汇总、来源不明页面

### 4.2 使用原则

- `S/A` 级证据优先
- `B` 级证据只能辅助，不能单独支撑强结论
- `C` 级证据默认不用于确定性 verdict，只能作为线索

## 5. Verdict 标签

允许输出的 verdict 固定为：

- `supported`
- `refuted`
- `insufficient`
- `conflicting`

不允许自行扩展新的核心 verdict 标签，避免前后不一致。

## 6. Verdict 判定硬规则

### 6.1 `supported`

适用条件：

- 至少有 1 条 `S` 或多条 `A` 级证据支持 claim
- 证据之间无明显核心冲突
- claim 与 evidence 能形成直接语义对应

### 6.2 `refuted`

适用条件：

- 至少有 1 条 `S` 或多条 `A` 级证据直接反驳 claim
- 反驳不是旁证，而是正面否定

### 6.3 `insufficient`

适用条件：

- 搜索结果太少
- 证据大多为 `B/C` 级
- 公开资料不足以支持或反驳
- claim 本身过于模糊或不可验证

### 6.4 `conflicting`

适用条件：

- 有多条可信证据，但它们相互冲突
- 当前没有更高优先级证据可以裁决

## 7. 禁止行为

- 没有证据时输出 `supported` 或 `refuted`
- 用单条 `C` 级来源支撑强结论
- 把观点类内容强行写成事实 verdict
- 把模型推断当成 evidence 本身

## 8. Confidence 建议

建议统一使用三档：

- `high`
- `medium`
- `low`

规则：

- `high` 只能在 `S/A` 级证据充分时出现
- `insufficient` 默认不高于 `low`
- `conflicting` 默认不高于 `medium`

## 9. 综合结论规则

最终综合结论必须满足：

- 不能比 claim 级结论更激进
- 如果 claim 大量为 `insufficient`，总评必须保守
- 如果 claim 存在核心冲突，必须显式提醒“当前存在争议或证据冲突”

## 10. 当前项目的最低实现要求

进入编码前，至少要把下面三件事固定：

1. claim 类型集合
2. evidence 字段结构
3. verdict 标签和硬边界

否则后端、前端和 Prompt 输出会很容易失控。
