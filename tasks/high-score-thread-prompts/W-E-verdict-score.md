# W-E / Verdict Score

你现在负责线程 `W-E`。

你的职责是：

- 做内容核查的最终判断层
- 做整条新闻可信度分

你必须建立在 `W-C` 的 claim 和 `W-D` 的 evidence bundle 之上，不要跳过它们自己发明输入。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- `backend/app/models/schemas.py`
- `contracts/report.schema.json`
- `rules/evidence_and_verdict_rules.md`

## 2. 你允许修改的文件

- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- verdict / score 相关测试

## 3. 你默认不要修改的文件

- `contracts/*`
- `backend/app/services/retrieval_*.py`
- `backend/app/services/timeline_builder.py`
- `frontend/*`
- `README.md`

## 4. 本线程核心目标

1. 把 claim 级 verdict 做稳
2. 让 provider / retrieval 失败时走保守边界
3. 让高风险样例不再危险抬升
4. 让整条新闻可信度分可计算、可解释、可展示

## 5. 当前优先任务

优先完成：

- `T05` Verdict、Fallback 与风险收口
- `T07` 整条新闻可信度分

## 6. 本轮必须完成的事

1. provider 失败时不再直接 `502`
2. provider claim 缺失时能回退到 rule claim
3. retrieval / evidence 缺失时不抬高 mode 和 verdict
4. 强化“主体不一致”“旧闻拼接”“半真半假”场景
5. 给每条 claim 输出更可复核的 `why this verdict`
6. 冻结第一版 overall score 公式
7. 生成 `overall_credibility_score`
8. 生成 `overall_credibility_label`
9. 生成 `score_breakdown`
10. 生成 `claim_contributions`

## 7. 不要做的事

1. 不要改 contract 本身
2. 不要改 retrieval / timeline 核心实现
3. 不要顺手改前端组件

## 8. 开始前先写

在对应任务文档下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 9. 完成标准

你这轮完成的标准是：

1. 内容核查主流程在失败场景下仍然保守可解释
2. 真假混杂新闻不会被粗暴打成单一真假
3. 整条新闻可信度分不是黑盒概率，而是可拆解说明

## 10. 交付物

你结束时必须明确给出：

1. verdict 规则变化摘要
2. 高风险 case 修复说明
3. score 公式与解释
4. final summary / score breakdown 示例
