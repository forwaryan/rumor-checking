# Codex App 多线程执行方案

更新时间：2026-03-15（Asia/Shanghai）

适用前提：

1. 你使用的是 Codex app。
2. 多个线程之间是真并行，但不会自动共享上下文。
3. 每个线程都应该像“独立承包一块文件域”的执行窗口，而不是 agent team 里的协作成员。

这份文档的目标不是设计理想化的多 agent 系统，而是给出在 Codex app 里真正可执行、冲突成本低的并行方案。

## 1. 先说结论

上一版“10 角色”方案，思路上没问题，但不适合直接在 Codex app 里原样执行。

原因很简单：

1. Codex app 线程不会自动同步中间结论。
2. 多个线程同时改 `schema`、`report_builder`、前端结果页，冲突概率非常高。
3. 线程太碎，会把大量时间浪费在手工合并和反复对齐上。

所以在 Codex app 里，正确的并行单位是：

- 文件域
- 阶段屏障
- 可复制的线程 prompt

不是“很多角色同时开工”。

## 2. Codex app 下的核心原则

### 原则 A：一个线程只拥有一组文件

不要让两个线程同时改下面这些高冲突文件：

- `backend/app/models/schemas.py`
- `contracts/report.schema.json`
- `backend/app/services/report_builder.py`
- `frontend/components/analyze-page.tsx`

这些文件必须有明确 owner。

### 原则 B：必须分阶段启动

在 Codex app 里，真正重要的不是“开多少线程”，而是“什么时候开哪个线程”。

推荐顺序：

1. 先冻结 contract
2. 再并行做输入、检索、前端壳
3. 再做 verdict + score 收口
4. QA 和文档线程全程跟随，但尽量不抢主实现文件

### 原则 C：线程之间靠文档交接，不靠记忆

每个线程都应该把本轮结论写进固定文档或固定文件，而不是假设其他线程“知道你改了什么”。

推荐交接落点：

- `proposal/`：本轮设计和线程方案
- `tasks/`：任务状态和 handoff
- `prompt-history.md`：重要规划记录
- `README / SMOKE_CHECKLIST / DEMO_SCRIPT`：对外表达收口

## 3. 两种可执行版本

### 方案 A：4 线程版

适合：

1. 你手里线程不多
2. 想尽快推进
3. 接受每个线程稍微重一点

#### 线程划分

| 线程名 | 职责 | 允许修改的核心文件 |
| --- | --- | --- |
| `T1-main-contract` | 总控、contract、评分字段冻结 | `contracts/*`、`backend/app/models/schemas.py`、`tasks/*`、`proposal/*` |
| `T2-input-retrieval` | 输入理解、claim 拆解、检索、时间线 | `backend/app/services/input_normalizer.py`、`backend/app/services/claim_extractor.py`、`backend/app/services/question_resolver.py`、`backend/app/services/retrieval_*.py`、`backend/app/services/timeline_builder.py` |
| `T3-verdict-score` | evidence judge、report builder、总可信度分 | `backend/app/services/verdict_engine.py`、`backend/app/services/report_builder.py`、评分相关测试 |
| `T4-frontend-qa-doc` | 前端展示、回归、smoke、README、demo 文档 | `frontend/*`、`backend/tests/*`、`README.md`、`SMOKE_CHECKLIST.md`、`DEMO_SCRIPT.md` |

#### 优点

1. 线程少，管理成本低。
2. 文件所有权比较清楚。
3. 适合快速起量。

#### 风险

1. `T2` 会比较重。
2. `T4` 会同时处理前端和文档，容易偏忙。

### 方案 B：6 线程版

适合：

1. 你准备更稳定地并行推进
2. 想减少线程之间的代码冲突
3. 愿意多开几个窗口

#### 线程划分

| 线程名 | 职责 | 允许修改的核心文件 |
| --- | --- | --- |
| `T1-main-contract` | 总控 + contract 冻结 | `contracts/*`、`backend/app/models/schemas.py`、`tasks/*`、`proposal/*` |
| `T2-input-claims` | 输入理解、claim 拆解 | `backend/app/services/input_normalizer.py`、`backend/app/services/claim_extractor.py`、`backend/app/services/question_resolver.py`、对应测试 |
| `T3-retrieval-timeline` | 多源检索、缓存、时间线 | `backend/app/services/retrieval_*.py`、`backend/app/services/retrieval_provider.py`、`backend/app/services/retrieval_models.py`、`backend/app/services/timeline_builder.py`、对应测试 |
| `T4-verdict-score` | verdict、score、report 收口 | `backend/app/services/verdict_engine.py`、`backend/app/services/report_builder.py`、评分相关测试 |
| `T5-frontend` | 前端输入页、结果页、可视化展示 | `frontend/*` |
| `T6-qa-doc` | 回归、smoke、README、演示话术 | `backend/tests/*`、`README.md`、`SMOKE_CHECKLIST.md`、`DEMO_SCRIPT.md`、说明文档 |

#### 优点

1. 线程边界更稳。
2. 检索和裁决分开，最接近题目两条主流程。
3. 前端不必等待全部后端做完才开始。

#### 风险

1. 需要更严格执行“禁止越界改文件”。
2. `T1` 如果没有及时冻结字段，其他线程会卡住。

## 4. 推荐你用哪一个

如果你现在主要目标是“真实做出来”，我建议你用 6 线程版。

理由：

1. 这个题最容易冲突的地方正好是 `claim / retrieval / verdict / score / frontend`。
2. 6 线程已经足够把高冲突区域拆开。
3. 再往上拆，Codex app 的上下文同步成本就不划算了。

一句话：

- 想快：4 线程版
- 想稳：6 线程版

## 5. 阶段屏障

不管你选 4 线程还是 6 线程，都应该遵守这 4 个阶段。

### 阶段 0：冻结 contract

只启动：

- `T1-main-contract`

完成标准：

1. 决定是否新增 `overall_credibility_score`
2. 决定是否新增 `score_breakdown`
3. 决定是否新增 `overall_credibility_label`
4. 决定前端最终消费哪些字段

没完成前，不建议其他线程改 `report` 最终结构。

### 阶段 1：并行打底

启动：

- `T2-input-claims`
- `T3-retrieval-timeline`
- `T5-frontend`
- `T6-qa-doc`

完成标准：

1. 输入拆 claim 能用
2. retrieval/timeline 有第一版稳定输出
3. 前端可以消费固定 contract 展示结果
4. smoke 和回归样例已经建起基本骨架

### 阶段 2：收口 verdict + score

启动：

- `T4-verdict-score`

依赖：

1. claim 输出结构稳定
2. retrieval bundle 稳定
3. timeline 第一版已经能产出

完成标准：

1. claim verdict 可解释
2. 整条新闻可信度分可计算
3. `report_builder` 输出稳定

### 阶段 3：验收和演示

继续推进：

- `T5-frontend`
- `T6-qa-doc`
- `T1-main-contract`

完成标准：

1. 页面表达清楚
2. smoke checklist 可执行
3. README 和 demo 话术收口
4. 能明确说明哪些是真实能力，哪些还只是保守路径

## 6. 文件所有权清单

这是 Codex app 最重要的一节。

### `T1-main-contract`

可改：

- `contracts/report.schema.json`
- `contracts/claim_result.schema.json`
- `contracts/timeline_node.schema.json`
- `backend/app/models/schemas.py`
- `proposal/*.md`
- `tasks/*.md`

默认不要改：

- `verdict_engine.py`
- `timeline_builder.py`
- `frontend/*`

### `T2-input-claims`

可改：

- `backend/app/services/input_normalizer.py`
- `backend/app/services/claim_extractor.py`
- `backend/app/services/question_resolver.py`
- 与输入理解直接相关的测试

默认不要改：

- `contracts/*`
- `report_builder.py`
- `frontend/*`

### `T3-retrieval-timeline`

可改：

- `backend/app/services/retrieval_service.py`
- `backend/app/services/retrieval_provider.py`
- `backend/app/services/retrieval_models.py`
- `backend/app/services/retrieval_cache.py`
- `backend/app/services/retrieval_deduper.py`
- `backend/app/services/timeline_builder.py`
- 检索与时间线测试

默认不要改：

- `schemas.py`
- `report_builder.py`
- `frontend/*`

### `T4-verdict-score`

可改：

- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- 与 score / verdict 相关测试

默认不要改：

- `contracts/*`
- `retrieval_*.py`
- `frontend/*`

### `T5-frontend`

可改：

- `frontend/components/*`
- `frontend/lib/*`
- `frontend/app/*`
- `frontend/README.md`

默认不要改：

- `contracts/*`
- `backend/app/models/schemas.py`
- `backend/app/services/*`

### `T6-qa-doc`

可改：

- `backend/tests/*`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `DEMO_SCRIPT.md`
- 文档说明文件

默认不要改：

- 后端主逻辑文件
- 前端主组件逻辑

## 7. 冲突最大的文件

如果你要开线程，这些文件必须特别谨慎：

| 文件 | 为什么高冲突 | owner |
| --- | --- | --- |
| `backend/app/models/schemas.py` | 所有线程都依赖 | `T1-main-contract` |
| `contracts/report.schema.json` | 前后端和测试共用 | `T1-main-contract` |
| `backend/app/services/report_builder.py` | verdict、score、前端全依赖 | `T4-verdict-score` |
| `frontend/components/analyze-page.tsx` | 前端主入口，容易被多线程同时改 | `T5-frontend` |
| `README.md` | 容易被实现线程和文档线程同时改 | `T6-qa-doc` |

## 8. 线程 Prompt 模板

下面是适合 Codex app 的版本。重点是“文件域边界”和“完成标准”，不是角色扮演。

### Prompt A：`T1-main-contract`

```text
你现在负责 Codex 线程 T1-main-contract。

你的职责只有三件事：
1. 冻结本轮 report / score contract。
2. 明确哪些字段是前端最终可依赖的。
3. 把本轮线程边界和依赖写清楚。

开始前先读：
- proposal/codex-app-multithread-execution-plan-20260315.md
- proposal/news-credibility-multi-agent-task-plan-20260315.md
- contracts/report.schema.json
- backend/app/models/schemas.py
- backend/app/services/report_builder.py

你可以修改：
- contracts/*
- backend/app/models/schemas.py
- proposal/*
- tasks/*

你不要修改：
- backend/app/services/verdict_engine.py
- backend/app/services/timeline_builder.py
- frontend/*

本轮必须完成：
1. 决定是否新增 overall_credibility_score、overall_credibility_label、score_breakdown。
2. 给出字段类型、边界、默认值和说明。
3. 写清楚其他线程应该依赖什么字段，不应该自己扩什么字段。

验收标准：
1. contract 第一版冻结。
2. 其他线程可以按这个结构继续实现。
3. 不产生新的字段漂移。
```

### Prompt B：`T2-input-claims`

```text
你现在负责 Codex 线程 T2-input-claims。

目标：把输入新闻拆成更稳的原子 claim，并提升事实 / 观点 / 预测的分类质量。

开始前先读：
- proposal/codex-app-multithread-execution-plan-20260315.md
- backend/app/services/input_normalizer.py
- backend/app/services/claim_extractor.py
- backend/app/services/question_resolver.py
- backend/app/models/schemas.py

你可以修改：
- backend/app/services/input_normalizer.py
- backend/app/services/claim_extractor.py
- backend/app/services/question_resolver.py
- 与输入相关测试

你不要修改：
- contracts/*
- backend/app/services/retrieval_*.py
- backend/app/services/report_builder.py
- frontend/*

本轮必须完成：
1. 复杂新闻拆成多个 claim。
2. 区分事实、观点、预测、不可核验。
3. 为后续 retrieval 提供更适合 claim 级检索的结构。

验收标准：
1. 输入拆 claim 明显比当前更细。
2. 不破坏现有 analyze 主链。
3. 输出结构能被 retrieval 线程直接消费。
```

### Prompt C：`T3-retrieval-timeline`

```text
你现在负责 Codex 线程 T3-retrieval-timeline。

目标：增强多源检索、缓存和传播链时间线，但不要碰最终裁决和总评分。

开始前先读：
- proposal/codex-app-multithread-execution-plan-20260315.md
- backend/app/services/retrieval_service.py
- backend/app/services/retrieval_provider.py
- backend/app/services/retrieval_models.py
- backend/app/services/retrieval_cache.py
- backend/app/services/timeline_builder.py

你可以修改：
- backend/app/services/retrieval_*.py
- backend/app/services/timeline_builder.py
- 检索与时间线测试

你不要修改：
- contracts/*
- backend/app/models/schemas.py
- backend/app/services/verdict_engine.py
- backend/app/services/report_builder.py
- frontend/*

本轮必须完成：
1. claim/event 级 retrieval 更稳定。
2. cache、fallback、failure detail 更清楚。
3. timeline 能更好地体现 origin -> amplification -> peak -> turn -> clarification。

验收标准：
1. retrieval bundle 稳定。
2. timeline 在真实结果上可解释。
3. 不引入 schema 漂移。
```

### Prompt D：`T4-verdict-score`

```text
你现在负责 Codex 线程 T4-verdict-score。

目标：基于已稳定的 claim 和 retrieval 输出，增强 claim verdict，并实现整条新闻可信度分。

开始前先读：
- proposal/codex-app-multithread-execution-plan-20260315.md
- backend/app/services/verdict_engine.py
- backend/app/services/report_builder.py
- backend/app/models/schemas.py
- contracts/report.schema.json

你可以修改：
- backend/app/services/verdict_engine.py
- backend/app/services/report_builder.py
- 与 verdict / score 相关测试

你不要修改：
- contracts/*
- backend/app/services/retrieval_*.py
- frontend/*

本轮必须完成：
1. evidence judge 更可解释。
2. 实现 overall credibility score。
3. 让 final summary 和 score breakdown 对齐。

验收标准：
1. supported / refuted / insufficient / conflicting 边界清楚。
2. 整条新闻可信度分可解释，不是黑盒概率。
3. 不反向修改 contract。
```

### Prompt E：`T5-frontend`

```text
你现在负责 Codex 线程 T5-frontend。

目标：把可信度、传播链和内容核查做成适合演示的结果页，但不擅自定义后端字段。

开始前先读：
- proposal/codex-app-multithread-execution-plan-20260315.md
- frontend/components/analyze-page.tsx
- frontend/lib/api-client.ts
- frontend/lib/report-utils.ts
- frontend/README.md

你可以修改：
- frontend/*

你不要修改：
- contracts/*
- backend/app/models/schemas.py
- backend/app/services/*

本轮必须完成：
1. 首页首屏价值表达。
2. 整体可信度卡片。
3. 传播链和内容核查的清晰展示。
4. 风险和局限提示。

验收标准：
1. 结果页一眼能看懂。
2. safe / partial / complete 差异清楚。
3. 前端严格消费后端 contract，不自造字段。
```

### Prompt F：`T6-qa-doc`

```text
你现在负责 Codex 线程 T6-qa-doc。

目标：建立回归、smoke、README 和 demo 话术，让这个项目不只是“代码看起来有”，而是真正可讲、可验、可复现。

开始前先读：
- proposal/codex-app-multithread-execution-plan-20260315.md
- README.md
- SMOKE_CHECKLIST.md
- DEMO_SCRIPT.md
- backend/tests/

你可以修改：
- backend/tests/*
- README.md
- SMOKE_CHECKLIST.md
- DEMO_SCRIPT.md
- 文档说明文件

你不要修改：
- backend/app/services/*
- frontend/components/*

本轮必须完成：
1. 形成针对本轮 contract 的回归和 smoke。
2. README 和 demo 话术收口。
3. 明确哪些能力现在能讲，哪些不能讲。

验收标准：
1. smoke checklist 可执行。
2. README 可作为新入口。
3. 演示口径诚实，不夸大 live 能力。
```

## 9. 你现在就能怎么开线程

### 如果你要 4 线程启动

顺序：

1. 开 `T1-main-contract`
2. 开 `T2-input-retrieval`
3. 开 `T4-frontend-qa-doc`
4. retrieval 有第一版结果后，再让 `T3-verdict-score` 收口

### 如果你要 6 线程启动

顺序：

1. 开 `T1-main-contract`
2. contract 稳后，同时开 `T2-input-claims`、`T3-retrieval-timeline`、`T5-frontend`、`T6-qa-doc`
3. claim 和 retrieval 稳后，开 `T4-verdict-score`

## 10. 最后的建议

在 Codex app 里，最忌讳两件事：

1. 线程太多，每个线程都只改一点点，还互相碰同一文件。
2. 没有 owner，靠人工最后再 merge 一切。

所以这次最实用的做法是：

1. 用 6 线程版
2. 让 `T1-main-contract` 先走
3. 明确文件 owner
4. 用阶段屏障控制并行

一句话版本：

Codex app 的并行，不是“让很多智能体讨论”，而是“让多个线程按文件域并行施工，再靠固定文档交接”。
