# 证据上下文与核查经验

## 按需读取证据

深度 synthesis 将证据组织成三个层次：

- L0：候选来源索引，保留 `result_id`、URL、来源、日期和标题。
- L1：搜索摘要的原文摘录。
- L2：本次已抓取网页的相关原文片段，记录在原始正文中的起止偏移。

按相关性和反证线索选择片段，包括正文后段；未知 `result_id` 的正文不会进入上下文。来源索引用于导航，摘要不是已核实的网页全文，片段缺失也不能证明事实不存在。引用继续使用当前检索结果的编号，现有证据约束与 Critic 降级规则保持有效。

预算覆盖系统提示、原始问题、事件信息、策略提示、证据三个层次、消息封装和预留输出。无法容纳原始问题及固定提示时走原有保守降级，不截短用户问题来制造可处理的输入。模型切换也会重新检查预算。

`AGENT_LAYERED_CONTEXT_ENABLED=true` 默认启用相关片段选择；关闭后采用短摘要与正文前段，仍保留完整提示预算检查。`AGENT_CONTEXT_MAX_TOKENS=0` 使用原有普通模型 32k / 推理模型 64k 假定；部署时可按实际模型设置正整数上限。该值不是自动探测的模型容量。

## 上下文诊断

`AGENT_CONTEXT_DIAGNOSTICS_ENABLED=true` 时，执行轨迹展示系统提示、用户固定内容、来源索引、摘要、正文片段、策略、预留输出与合计的估算量，以及选入/省略数量。启用现有 `MODEL_LEDGER_ENABLED` 后，synthesis 调用还会将允许的非负计数写入账本 `context_estimate`，并标记 `estimate_kind=heuristic`。

计数不包含原始提示、正文或凭证；不同请求的统计互不共享。模型响应中的真实 usage 与这些估算是两个维度。启发式估算不等于模型 tokenizer，也不承诺实际费用或准确率改善。本次未实现相邻轮次的上下文差异可视化。

## 经审核的核查策略

`AGENT_PLAYBOOKS_ENABLED=true` 默认启用策略库；目录由 `AGENT_PLAYBOOK_DIR` 指定，默认为 `backend/app/agent/playbooks/`。内置政策时效、旧闻与实体对齐、转载去重与正反证核对三类步骤，按当前问题匹配，最多读取三个策略。

策略只给 investigation 和 synthesis 提供查证方法，不能作为事实来源或引用。新增 JSON 文件需满足 `CheckingPlaybook` 模型：

```json
{
  "id": "example_procedure",
  "kind": "procedure",
  "status": "draft",
  "title": "核对官方发布日期",
  "match_terms": ["政策", "policy"],
  "instructions": ["分别确认发布日、生效日与适用范围。"],
  "source_url": "repo://backend/tests/test_claim_timeliness.py",
  "reviewed_at": "2026-09-13"
}
```

先审核方法和出处，再将 `status` 设为 `approved`。可选 `expires_at` 限定有效期。草稿、未来审核日期、过期记录、未知字段、超大文件、符号链接和格式错误均不加载；不会执行文件中的代码。`repo://` 表示仓库内的策略依据，不是事实证据 URL。

使用新 run 接口完成分析时，会在 `ANALYSIS_RUN_DIR/experience/` 留下草稿观察记录：使用的策略 ID、结果分类计数和来源数量，最多保留 200 条。记录不保存问题、结论或网页原文，也不会自动变成可加载策略。维护者可以据此寻找反复出现的核查缺口，编写候选步骤，并通过回放与审核后更新策略库。

这是流程经验复用，不训练模型权重，不把历史裁决当作当前证据。JSON 策略文件是受信任的本地维护配置；业务输入不能指定其路径或修改审核状态。

## 验证入口

```bash
python -m pytest backend/tests/test_evidence_context.py backend/tests/test_context_window.py backend/tests/test_model_ledger.py backend/tests/test_checking_playbooks.py -q
```

长文本、反证位于正文后段、未知来源编号、预算边界和模型切换由确定性测试覆盖；真实模型准确率与费用需要另用同一批回放用例比较。
