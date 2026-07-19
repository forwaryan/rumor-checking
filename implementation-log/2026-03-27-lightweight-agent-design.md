# 轻量 Agent 化设计（已实现，归档）

原始记录日期：2026-03-27　　归档更新：2026-07-19（Asia/Shanghai）

> 本文是"把固定 pipeline 改造成受控调查 Agent"的技术方案，**现已全部实现并端到端联调通过**。
> 保留它作为设计说明与决策记录；当前代码与运行事实以
> [docs/current-code-architecture-guide.md](../docs/current-code-architecture-guide.md) §6.5 和
> [docs/status/current-verified-state.md](../docs/status/current-verified-state.md) 为准。
> 原先的多 Agent 协作任务看板（认领规则/波次表等纯过程脚手架）已删除——任务已完成，看板无保留价值。

## 目标与边界

一个**受控的谣言核查调查 Agent**，不是开放式通用 Agent：

- 输入范围：文本问题 / URL / 新闻文本。
- 允许动作：白名单工具 + 有上限的额外检索轮次。
- 停止条件：证据已足够 / 证据不足但达轮数上限 / 问题无法锚定到稳定事件。
- 输出约束：最终仍收敛到现有 `Report` 契约，不破坏前后端协议。

## 核心设计（对应已落地代码）

### 1. Agent 运行状态

`backend/app/agent/state.py::AgentState` 作为贯穿工具的黑板，字段对应固定 pipeline 的中间产物（normalized/resolved/final event、retrieval bundle、claim/verdict/timeline 等）。

> 实现取舍：**没有**新增独立的 `AgentTrace`/`AgentRun` 模型；调查过程复用现有 `stage`/`log` 流式事件 + `pipeline_trace`，前端从这些事件派生调查视图。这样最小化了协议改动。

### 2. 把现有能力封装成工具

`backend/app/agent_tools/tools.py` 把现成服务薄封装为工具，**不重写业务**：
`normalize / search_news / resolve_question / follow_up_retrieval / investigate / fetch_url / synthesize / enrich / extract_claims / judge_claims / build_timeline / finalize_report`。
工具共用同一套 `emit_stage`，所以过程可观测。其中 `fetch_url` 抓取最权威证据的全文，按同一 `result_id` 挂靠喂给 synthesis（grounding 安全），由 `AGENT_MAX_URL_FETCHES` 限制。

### 3. 受控 Agent 循环

`backend/app/agent/runner.py`：`plan -> tool -> observe -> decide -> finalize`，带步数上限；任何异常回退固定 pipeline。

`backend/app/agent/planner.py`：
- `legal_actions(state)` 是排序的**唯一真相源**（编码数据依赖：如不能先判定后抽取）。
- `RulePlanner`（默认）永远取第一个合法动作，复刻固定 pipeline 顺序 → `off+mock` 上与旧链路**逐字节一致**（parity 测试保证）。
- `LlmPlanner`（配置 Kimi 时）只在真实岔路口调 LLM 决策（候选：investigate / fetch_url / synthesize），非法/失败退回 `RulePlanner`。`fetch_url` 排在规则默认动作之后，故 `RulePlanner` 永不选它 → parity 不破。

### 4. Grounded verdict

开 Kimi 时 `agent_reasoner.synthesize` 接管判定：`supported/refuted/conflicting` 必须带 `evidence_result_id`，否则降级 `insufficient`；落到规则引擎时 provenance 标 `llm_synthesis_unavailable_rule_fallback`。

### 5. 前端

`frontend/components/agent-run-panel.tsx` + `frontend/lib/agent-run.ts` 从事件流派生 plan/tool/observation/decision 视图，非 agent 路径自动隐藏。

## 与固定模式的取舍（仍成立的结论）

| 维度 | 固定 pipeline | Agent 编排 |
| --- | --- | --- |
| 执行 | 固定顺序 | 受控小循环，可决定是否继续调查 |
| 稳定性/可回归 | 更高 | 靠 RulePlanner 保 parity + 出错回退 |
| 成本/时延 | 更低 | LLM 调用 + 真实检索,时延明显 |
| 可解释性 | 阶段日志 | 计划 + 工具调用 + 决策理由 |

默认关闭（`AGENT_ORCHESTRATOR_ENABLED=false`），需要"agent 感"或真实调查时再开。
