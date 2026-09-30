# 模型调用可观测性

参考 [claude-tap](https://github.com/liaohch3/claude-tap) 的逐请求记录、上下文对比和 usage 展示方式，在现有 Agent Trace、模型台账和 Phoenix 中补充 LLM 调用信息。参考版本为 `4cc867d2e9689a7e5ca8623c67cabcb3fb7a456f`；没有引入代理进程、复制其源码或添加新的 Agent 框架。

## 开启与查看

在后端运行环境或本机 `backend/.env` 中设置，重启后端：

```dotenv
AGENT_TRACE_ENABLED=true
MODEL_LEDGER_ENABLED=true
LLM_STREAM_INCLUDE_USAGE=true
```

运行一次核查，在结果下方打开 **Agent 调用记录**，展开 `LLM` 节点的 **调用详情**。节点显示输入/输出/缓存 Token、首内容时间、耗时、重试次数、响应和推理字符数、工具调用数，以及上下文组成和变化字段。页面总览显示 usage 覆盖率；未提供的数值显示“未提供”，不能按零消耗理解。

失败和中断的任务也保留调用记录入口。面板支持重新加载，关闭后再次展开会获取最新记录；刷新失败时保留上次成功读取的数据。详情按 Token、响应耗时、请求上下文、调用标识分组，支持窄屏换行和键盘展开。

- `AGENT_TRACE_DIR/<run_id>.json` 保存完整任务 span 树，默认目录为 `data/traces`。
- `MODEL_LEDGER_DIR/model-calls-YYYY-MM-DD.jsonl` 保存逐调用台账，目录沿用原配置。
- `call_id` 对应一次真实发送；`trace_id` 对应任务的 `run_id`；`parent_span_id` 对应发起请求的 Agent/工具节点。每次重试单独计数。
- `GET /api/v1/agent-trace/{run_id}` 沿用现有内部诊断接口。
- 仅开启台账也能记录调用，JSON span 树仍需 `AGENT_TRACE_ENABLED`。
- 对不支持 `stream_options.include_usage` 的旧网关，设置 `LLM_STREAM_INCLUDE_USAGE=false`；不会自动追加兼容性重试、额外消耗模型调用预算。

Phoenix 沿用原配置：

```bash
pip install -r backend/requirements-observability.txt
```

```dotenv
PHOENIX_ENABLED=true
PHOENIX_OTLP_ENDPOINT=http://localhost:6006/v1/traces
```

新节点导出为 OpenInference `LLM`，包含模型名、HTTP 状态和 Token 数；原 Agent/工具节点继续保留。导出失败不会改变核查结果。

## 覆盖范围和语义

| 内容 | 实现与限制 |
| --- | --- |
| 实际调用 | reasoner 流式调用、结构化抽取、web_search 每轮 Chat Completions，以及 `complete_once` 的判定/纠错等轻量调用都记录；未真正发出的请求不计数 |
| 业务链路 | 固定流水线、单 Agent、多 Agent 和失败回退共享一个任务 Trace；线程池通过 `copy_context` 传播运行和父节点 |
| 请求上下文 | 记录角色字符数、消息/工具数和紧凑 JSON 序列化字节数；后者不是原始 HTTP 线上字节数，也不是 Token 估算 |
| 请求对比 | 对同一任务、父节点、提供方、阶段、工作线程的相邻请求比较白名单字段；第一次无比较结果。运行级随机密钥的 HMAC 只在内存中保存，结束时释放，不输出摘要或正文 |
| 流式响应 | 汇总内容/推理字符、首次内容/推理/工具增量时间；按 choice/tool 索引去重分片工具调用 |
| Token | 支持 OpenAI 及常见兼容字段，包括 choice 内 usage、usage-only 末块和缓存读取字段；缓存数是输入子集，不另加到总量 |
| 缺失用量 | `usage_reported=false`，span 的 `token_usage` 为空；台账保留旧计数字段兼容性，通过 `usage_reported` 与可空 `total_tokens` 区分未知和已报告零 |
| 状态 | `ok`、`empty`、`error`、`truncated`；HTTP/网络/JSON 错误、超时、输出截断，以及无终止标记直接结束的 SSE 都入账。`ok` 表示调用获得内容或工具调用，不代表后续业务校验/证据核验成功 |
| 原文调试 | 常规 Trace/台账不保存请求或响应正文。已有进度流的调用详情保持原行为；需要逐字节代理抓取可另行使用 claude-tap |

上下文变化白名单：`messages`、`tools`、`model`、`temperature`、`max_tokens`、`response_format`、`stream`、`stream_options`。不持久化任意字段名、提示词、回答、请求头或网关地址。合成阶段原有的启发式上下文预算统计继续保存在台账，和上游实际 usage 分开解释。

Agent hook 的 Token 统计改为动作前后增量，扣除已记录的 LLM 子节点用量，避免累计值在多个动作上重复相加。失败回退结束后只导出一次，避免先前尝试的 Trace 被覆盖。检查点续跑目前仍按本次执行记录，不合并历史执行文件。

## 实现位置

- `backend/app/services/model_call_observer.py`：调用上下文、usage 归一化、安全上下文对比、span 和台账关联。
- `backend/app/agent/trace.py`：按执行上下文隔离的父子 span 和 Token 增量。
- `backend/app/services/agent_reasoner.py`、`llm_provider.py`、`retrieval_provider.py`：发送与响应采集。
- `backend/app/services/analyze_pipeline.py`：整个核查请求的上下文与最终导出。
- `frontend/components/agent-span-tree.tsx`：沿用现有内部 Trace 结构展示 LLM 详情。

没有增加公共 Report 字段；新增数据使用原内部 Trace 的 `metadata` 和 `token_usage` 扩展字段，前端保留对旧 Trace 的兼容。

## 验证边界

离线测试覆盖真实 httpx 模拟传输、JSON/SSE、网络/HTTP/解析异常、截断、未知/零/缓存 usage、上下文对比、并发隔离、回退只导出一次、台账与 Trace 的调用 ID 对齐及正文不落盘。Phoenix 用内存 exporter 验证标准 LLM 属性；真实 JoyCode DeepSeek 模型的补充验收见下方改进记录；Phoenix 仍未连接实际实例验收。离线核查回放不测模型计费，也不证明核查准确率提升。


完整开发工作区的历史验证（2026-09-30，包含其他尚未提交的功能，数量不等同于本次独立提交的验证）：

- 契约检查：16 个公共模型一致；Ruff 和 `git diff --check` 通过。
- 后端全量：前端优化收尾时重跑，1,369 项通过。
- 前端：类型检查、178 项测试、生产构建通过；新增乱序、重复、循环和深层节点的调用树测试。
- 默认回放：8 个已提供证据的样例，标签和证据组评分均为 8/8；`seed_015_dateless_evidence` 仍报告 `undated_evidence` / `stale_evidence`，不把该诊断视为模型或观测链路验收通过。
- 后端使用 `/tmp/rumor-observability-venv/bin/python` 隔离安装仓库要求的 httpx 版本。原全局环境与 Starlette 不兼容；全量测试中的 62 条警告来自其旧 `app` 快捷接口。该虚拟环境继承全局包，`pip check` 仍报告 py9n、sse-starlette 两项非项目工具的版本冲突；干净环境安装受包源缺少 pydantic-core 阻塞。

前端交互补充验收：使用隔离临时目录中的合成失败任务与真实 FastAPI/Next.js 页面，Chromium 验证桌面、390px 和 320px 视口无横向溢出，详情分组、未知 usage、真实接口 404/500 重试、刷新失败保留旧记录、关闭重开获取新记录、键盘展开均通过，无页面脚本错误。该验收不调用真实模型。

检索阶段与轻量模型调用的补充覆盖、参考项目和验证边界见 [GitHub 改进记录](github-improvements-2026-09.md)。检索详情沿用同一调用记录面板与开关。

提交隔离验收：仅应用本次可观测性、数量判定与检索身份改动的候选版本，后端 976 项、前端 109 项测试通过；7 个契约模型一致，Ruff、类型检查和生产构建通过。默认保留的 18 个回放中标签/完整证据组为 16/18 与 18/18，既有诊断未删除。可观测性首个提交的精确暂存版本另有 99 项定向测试通过。上述完整开发工作区记录包含未随本次提交的历史功能与评测集。
