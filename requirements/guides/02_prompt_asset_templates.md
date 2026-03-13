# Prompt 资产模板与记录示例

本文档不是规则本身，而是用于配合 `rules/prompt_and_eval_rules.md` 的落地模板。

目标只有一个：让 Prompt 设计不再停留在“原则”，而是能被直接记录、展示和复用。

## 1. 关键 Prompt 版本模板

```md
## Prompt: <prompt_name>

- Version: v1
- Stage: <claim_extraction / evidence_selection / verdict_generation / ...>
- Goal: <这个 Prompt 要解决什么问题>
- Inputs:
  - <输入 1>
  - <输入 2>
- Output Schema:
  - <字段 1>
  - <字段 2>
- Prompt Summary:
  - <这一版 Prompt 的核心约束或核心思路>
- Why This Version:
  - <为什么需要这版改动>
- Known Risks:
  - <这版仍然存在什么风险>
- Status:
  - draft / in_use / deprecated
```

## 2. 失败问题与修复记录模板

```md
## Failure Case: <case_id_or_name>

- Related Prompt: <prompt_name + version>
- Symptom:
  - <失败现象>
- Root Cause:
  - <判断出的原因>
- Fix:
  - <Prompt 或流程改了什么>
- Expected Improvement:
  - <希望改善什么>
- Verification Result:
  - pass / partial / fail
```

## 3. 输出 Schema 模板

```json
{
  "claim": "string",
  "claim_type": "fact | opinion | prediction | unverifiable",
  "verdict": "supported | refuted | insufficient | conflicting",
  "confidence": "number",
  "evidence": [
    {
      "title": "string",
      "url": "string",
      "source_name": "string",
      "published_at": "string",
      "snippet": "string",
      "relevance_reason": "string"
    }
  ],
  "notes": "string"
}
```

## 4. 幻觉防控策略模板

```md
## Hallucination Guard

- No-evidence rule:
  - <没有证据时禁止输出什么>
- Evidence binding rule:
  - <哪些结论必须绑定证据字段>
- Conflict handling rule:
  - <冲突证据时如何处理>
- Opinion boundary:
  - <哪些内容只允许归类为观点，不允许硬判真假>
- Final fallback:
  - <最坏情况下输出什么安全结果>
```

## 5. 上下文超限处理模板

```md
## Context Overflow Strategy

- Long input trigger:
  - <什么情况下视为超长>
- Chunk strategy:
  - <按什么维度分块>
- Chunk summary rule:
  - <每块保留什么信息>
- Merge strategy:
  - <如何合并各块摘要>
- Loss check:
  - <如何检查关键信息是否丢失>
```

## 6. Eval Case 表模板

```md
| Case ID | Case Type | Input Summary | Expected Result | Check Focus | Result |
| --- | --- | --- | --- | --- | --- |
| C01 | normal | 正常新闻 case | 能抽出 3-5 条 claim | claim 抽取完整度 | pass |
| C02 | insufficient | 证据不足 case | verdict 含 insufficient | 不乱判 | pass |
| C03 | conflicting | 证据冲突 case | verdict 含 conflicting | 冲突处理 | pass |
| C04 | long_text | 长文本 case | 分块后仍保留关键事实 | 上下文处理 | partial |
```

## 7. 当前项目最推荐优先记录的 Prompt

对于“较真”的新闻观察员，建议优先从下面几个 Prompt 开始建资产：

1. `claim_extraction`
2. `claim_classification`
3. `evidence_selection`
4. `verdict_generation`
5. `timeline_summary`

## 8. 最小使用建议

如果你不想一开始写得太重，至少先做这 4 件事：

1. 给 `claim_extraction` 和 `verdict_generation` 各留一份版本记录
2. 写 2 到 3 条失败修复记录
3. 固定一份核查输出 schema
4. 拉一张 4 个 case 的 eval 表

做到这一步，你的 Prompt 设计就已经从“口头原则”升级成“可展示资产”了。
