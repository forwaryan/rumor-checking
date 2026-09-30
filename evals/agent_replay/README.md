# 深度 Agent 确定性回放

此处的三条样本均为虚构城市、机构和事件，不代表真实新闻。它们衡量现有深度执行流程的行为，不构成准确率基准或在线模型质量评估。

```bash
python backend/scripts/replay_agent.py --output artifacts/agent-replay-local.json
python backend/scripts/replay_agent.py --dir evals/agent_replay --json
python -m pytest backend/tests/test_agent_replay.py -q
```

## 实际运行的层

入口为 `AnalyzePipeline.analyze(mode=deep)`，通过现有 `AgentRunner`、`LlmPlanner` 和已注册工具完成归一化、真实查询生成、检索去重、问题解析、调查规划、综合、Critic、Critic refinement、数字纠正、证据缺口守卫、按缺口补查、报告构建。超时样本还经过现有规则 fallback、逐 claim 判定、正文解析、再检索和重新判定。

替换外部 I/O 边界：

- 检索 provider 按准确的 `(stage, query)` 返回录制的 `SearchResult`。真实 `RetrievalService` 的查询生成、并发分发、合并与评级全部执行；未录制或超次数查询导致门禁失败，即使生产代码捕获异常并继续也一样。
- `LlmAgentReasoner._stream_completion` 按顺序返回录制模型文本或抛出录制超时。提示组装、预算适配、JSON/schema 解析、Critic 与缺证保护仍为真实代码。补偿判定和数字纠正的调用也逐条录制。模型调用序列不匹配、调用多了或录制响应没用完，均失败。

超时样本的页面 GET 由录制 HTML 响应喂给真实正文解析；DNS 只对有录制页面的主机返回固定公网地址，HTTP transport 不访问网络。页面响应次数受夹具约束；同次运行的真实页面缓存会避免重复 GET。所有未录制 HTTP、socket 连接、DNS 和子进程启动都被阻断。

## 样本与预期

| 样本 | 路径 | 应保持的行为 |
| --- | --- | --- |
| `01_supported.json` | 公告支持 → Critic 保留 → 报告 | 明确公告支持恢复开放日期，引用真实检索生成的证据 ID |
| `02_missing_price.json` | 补查票价 → Critic 撤回过强判定 → refinement → 缺口定向搜索 | 开放时间、预约流程不能证明免费；补查仍无票价信息，保留 `insufficient` 和 `price` 缺口 |
| `03_model_timeout.json` | 综合超时 → fallback → 页面/逐 claim 判定 → 再检索 | 超时不能产生确定结论；现有证据不足以支持“所有展览永久免费” |

`expected.claims` 检查完整 claim 集和判定，`required_actions` 检查必经工具，`evidence_gaps` 检查结构化缺口。修改流程后若门禁失败，应核实新增调用是否必要、gold 是否符合证据；不能改生产证据要求迎合脚本。

## 输出与隔离

输出含实际工具序列、证据输入/输出 ID、检索 query SHA-256、模型/调用序号/输出预算、完整输入提示指纹、实际系统模板指纹、模型响应指纹、页面指纹、fixture 指纹和失败原因。检索和页面的独立并发调用按稳定键排序；不导出提示正文、原始查询、claim 原文、HTML 正文、密钥或时间耗时，因此相同版本的连续两次运行可直接比较完整 JSON。

运行时不加载项目 `.env`，使用独立默认配置、虚构模型与虚构密钥，缓存和页面缓存写入临时目录并自动删除。设置、模型健康注册表、页面缓存指针及 transport patches 在结束后恢复。该模块使用进程级 patch，只适合专用 CLI 或串行测试，不能嵌入正在处理在线请求的服务进程。

## 明确边界

当前覆盖单 Agent 的深度工作流，不覆盖多 Agent 并发重执行、真实模型网络流/SSE 分块、真实搜索召回、线上超时测量、HTTP 服务与浏览器交互、断点恢复或真实凭据环境。超时在模型传输替身处注入；模型返回内容是测试脚本，不是现场模型生成。它比只把标准 claim 和证据交给 VerdictEngine 的回放多验证规划、工具衔接、综合解析和纠错流程，但不能据此声称在线准确率提高。
