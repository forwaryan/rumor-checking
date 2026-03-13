# Prompt Inventory

## 1. 这份文档的作用

本文件用于统一整理**当前仓库可见范围内已经使用过的 Prompt**，并把原先散落在 `02_prompt_asset_templates.md` 中的 Prompt 资产模板一并合并进来。

补充说明：

- 这里是可复用 Prompt 资产与规范化说明的正式入口
- 项目历史轨迹与上下文还原请参考 `overview/04_prompt_inventory.md`

目标有三个：

1. 盘点目前到底用过哪些 Prompt
2. 把这些 Prompt 按用途分层，方便后续复用
3. 给后续 Prompt 调优、Prompt 资产沉淀和面试讲解提供统一入口

## 2. 统计范围说明

本次 inventory 的来源包括：

- `prompt-history.md` 中已经记录的历史 Prompt
- 当前可见会话中已经实际使用过、但未必已写入 `prompt-history.md` 的用户指令
- 当前仓库中已经长期使用的触发型 Prompt，例如 `[Log]`、`[Commit]`
- 原 `requirements/guides/02_prompt_asset_templates.md` 中的 Prompt 资产模板

注意：

- “所有对话”这里按**当前仓库与当前会话可见范围**统计
- 如果过去还有未记录到仓库、也不在当前上下文里的历史聊天，本文件无法凭空恢复

## 3. 当前 Prompt 分层

当前已用 Prompt 基本可以分成 4 类：

1. **项目分析型 Prompt**
   - 用于梳理需求、竞品、难点、边界、执行计划
2. **结构整理型 Prompt**
   - 用于整理文件夹、规则、触发指令、项目地图
3. **验证与评测型 Prompt**
   - 用于 benchmark、测试集、随机新闻评测、Prompt 资产评测
4. **协作触发型 Prompt**
   - 用于 `[Log]`、`[Commit]` 这类流程触发

## 4. 已实际使用的触发型 Prompt

### 4.1 `[Log]`

- 作用：记录任务日志、线程职责、上下文来源和交接建议
- 当前已使用场景：
  - 线程与角色分析
  - benchmark / 数据集评测问题
- 典型用法：

```md
[Log] 我现在有一个问题，就是是否有一种可能的数据集能测试我做出的工程评分，比如 benchmark？
```

### 4.2 `[Commit]`

- 作用：触发真实 Git 提交流程
- 当前已使用场景：
  - 文档提交
  - Prompt 规则与双层留痕规则提交
- 典型用法：

```md
[Commit]
```

## 5. 已使用的历史任务 Prompt

下面这些 Prompt 已在 `prompt-history.md` 中留痕，属于当前项目最早一批核心任务指令。

### P01 原型与需求梳理

- 原始 Prompt：
  - `根据当前系统已有的原型文档，结合需求，整理它们的实现逻辑、实现思路和实现技术，并把总结文档放到 requirements/ 目录下。`
- 主要目的：
  - 梳理项目原型、明确当前仓库已有的产品目标与协作规则
- 主要产出：
  - 原型对齐类分析文档
- Prompt 家族：
  - `requirements_synthesis`

### P02 竞品与开源调研

- 原始 Prompt：
  - `调研 GitHub 和各大公司是否有与题目类似的实现，重点包括腾讯新闻“较真AI”等产品，列举并分析对比这些产品，进而反推出我们自己的设计目标。`
- 主要目的：
  - 找外部参考、明确差异化设计目标
- 主要产出：
  - 开源参考与竞品对比文档
- Prompt 家族：
  - `research_benchmarking`

### P03 边界确认问题清单

- 原始 Prompt：
  - `总结一份需要向改题目/出题方确认的问题清单，重点关注数据集、题目边界和实施约束。`
- 主要目的：
  - 提前识别高风险边界问题，减少返工
- 主要产出：
  - 需求澄清与边界确认问题清单
- Prompt 家族：
  - `boundary_confirmation`

### P04 Benchmark 可行性判断

- 原始 Prompt：
  - `[Log] 我现在有一个问题，就是是否有一种可能的数据集能测试我做出的工程的评分，比如说 benchmark？`
- 主要目的：
  - 判断有没有公开 benchmark 能部分代理工程评分
- 主要产出：
  - benchmark 适配建议、三层评测思路
- Prompt 家族：
  - `eval_strategy`

### P05 V1 零额外 Key 蓝图

- 原始 Prompt：
  - `基于现有 overview 和最小可行方案，制定一版 V1 文档，要求除大模型 API key 调用外尽量做到零额外 key，并将文档与现有分析文档全部关联起来。`
- 主要目的：
  - 把总览文档和分析文档压缩成可执行的 V1 实施蓝图
- 主要产出：
  - `overview/03_v1_zero_key_blueprint.md`
- Prompt 家族：
  - `v1_bridge_blueprint`

## 6. 当前会话中新增使用的任务 Prompt

下面这些 Prompt 已在当前会话中实际使用，但不一定都已经单独沉淀到 `prompt-history.md` 中；这里统一纳入 inventory。

### P06 线程与角色分析

- 原始 Prompt：
  - `[Log] 你分析现有的工作应该起多少个线程来同时进行，同时对角色的必要性进行分析`
- 主要目的：
  - 评估当前阶段适合开几个并行窗口，以及哪些角色必须独立
- 主要产出：
  - 线程数建议、角色必要性分析
- Prompt 家族：
  - `threading_and_roles`

### P07 方括号触发指令整理

- 原始 Prompt：
  - `把我现有的 用[]触发的指令整理到一个文件中，对每个指令进行解释，并且列一个逻辑图`
- 主要目的：
  - 统一整理 `[Log]`、`[scores]`、`[Commit]` 等协作触发词
- 主要产出：
  - 方括号触发指令总览文档
- Prompt 家族：
  - `command_inventory`

### P08 难点汇总与边界确认文档

- 原始 Prompt：
  - `根据现有的分析内容给出难点汇总和需要跟提需求的人确定边界的文档，需要你结合流程图之类的文图并茂的方式，减少我的理解难度`
- 主要目的：
  - 把现有分析压缩成适合沟通需求边界的材料
- 主要产出：
  - 难点汇总与边界确认文档
- Prompt 家族：
  - `difficulty_and_scope_summary`

### P09 项目目标与文件夹分层解释

- 原始 Prompt：
  - `总结一下我们现在的目标是什么，需要你有新的文件夹对我们目前其他所有内容进行解释分层，为什么要有某个文件夹`
- 主要目的：
  - 给当前仓库补一层“地图层”解释
- 主要产出：
  - `overview/` 目录及分层说明文档
- Prompt 家族：
  - `repo_overview`

### P10 AI 新技巧扫描

- 原始 Prompt：
  - `看看有没有什么ai新出的更方便的技巧我这里没用使用上的？`
- 主要目的：
  - 对照当前方案，找高收益但尚未使用的 AI 能力
- 主要产出：
  - 新技巧建议清单
- Prompt 家族：
  - `ai_capability_gap_scan`

### P11 最小测试集生成

- 原始 Prompt：
  - `按照这个目标，给我做一个最小的测试集，后边我开始写的时候会用这些`
- 主要目的：
  - 为 V1 开发阶段准备最小可重复测试集
- 主要产出：
  - `evals/minimal_v1/`
- Prompt 家族：
  - `minimal_eval_set`

### P12 Prompt Inventory 收口

- 原始 Prompt：
  - `整理目前我所有对话中使用过的prompt，然后整理到04_prompt_inventory.md中，和之前的文件进行合并`
- 主要目的：
  - 把已使用 Prompt 和 Prompt 资产模板统一收口到一个文件
- 主要产出：
  - 本文档 `04_prompt_inventory.md`
- Prompt 家族：
  - `prompt_inventory`

## 7. 可复用 Prompt 家族模板

下面这些模板，是从上面的真实 Prompt 中抽象出来的复用版。

### 7.1 需求 / 原型梳理模板

```md
根据当前系统已有的原型文档，结合需求，整理它们的实现逻辑、实现思路和实现技术，明确每类文档解决什么问题、未来应落到哪里，并把总结文档放到 requirements/ 目录下。
```

### 7.2 竞品 / 开源调研模板

```md
调研与当前题目最接近的产品、开源实现和公开能力，对比它们分别解决了哪一部分问题、有哪些可借鉴点和不适合直接复制的地方，再反推出我们自己的设计目标。
```

### 7.3 边界确认问题清单模板

```md
基于当前题目、规则和实现难点，整理一份需要向需求方确认的问题清单，重点覆盖数据边界、题目口径、联网/API 约束、Demo 验收方式和交付边界。
```

### 7.4 线程与角色分析模板

```md
基于当前仓库已有工作，分析现在适合拆成多少个线程并行推进，区分哪些角色必须独立、哪些角色可以合并，并给出推荐分工方案。
```

### 7.5 仓库结构解释模板

```md
总结当前项目的目标、阶段和最关键的推进顺序，并新增一层总览文档，解释每个文件夹为什么存在、分别负责什么、应该按什么顺序阅读。
```

### 7.6 Benchmark / 评测策略模板

```md
判断当前项目是否存在可直接复用的数据集或 benchmark 来测试工程效果，并区分：哪些能测 verdict/evidence，哪些只能做代理评测，哪些仍必须人工验收。
```

### 7.7 最小测试集生成模板

```md
基于当前 V1 目标、规则边界和评测模板，生成一套最小可重复测试集，要求能直接服务后续开发，并覆盖输入标准化、claim 分类、verdict、检索和模式选择。
```

### 7.8 Prompt 收口与资产盘点模板

```md
整理当前仓库和当前会话中已经使用过的 Prompt，按用途分层归类，并把已有 Prompt 模板、评测模板和资产模板合并到一个统一入口文档中。
```

## 8. 合并自旧文件的 Prompt 资产模板附录

下面这部分内容由原 `02_prompt_asset_templates.md` 合并而来，后续建议优先维护本文件，而不是重复维护两份内容。

### 8.1 关键 Prompt 版本模板

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

### 8.2 失败问题与修复记录模板

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

### 8.3 输出 Schema 模板

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

### 8.4 幻觉防控策略模板

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

### 8.5 上下文超限处理模板

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

### 8.6 Eval Case 表模板

```md
| Case ID | Case Type | Input Summary | Expected Result | Check Focus | Result |
| --- | --- | --- | --- | --- | --- |
| C01 | normal | 正常新闻 case | 能抽出 3-5 条 claim | claim 抽取完整度 | pass |
| C02 | insufficient | 证据不足 case | verdict 含 insufficient | 不乱判 | pass |
| C03 | conflicting | 证据冲突 case | verdict 含 conflicting | 冲突处理 | pass |
| C04 | long_text | 长文本 case | 分块后仍保留关键事实 | 上下文处理 | partial |
```

## 9. 维护建议

后续如果继续新增 Prompt，建议统一按下面方式维护：

1. 先把新任务写入 `prompt-history.md`
2. 再判断它属于哪个 Prompt 家族
3. 如果已经形成可复用模式，就补进本文件第 7 节
4. 如果已经进入 Prompt 调优或 schema 演化，再补本文件第 8 节对应资产

## 10. 最终建议

如果你后续只保留一个 Prompt 总入口，我建议优先看本文件，再按需要跳转到：

- `rules/prompt_and_eval_rules.md`
- `requirements/guides/03_random_news_eval_template.md`
- `prompt-history.md`

这样你就能同时看到：

- 真实用过哪些 Prompt
- 它们属于什么家族
- 后续该怎么把 Prompt 做成真正可复用资产


