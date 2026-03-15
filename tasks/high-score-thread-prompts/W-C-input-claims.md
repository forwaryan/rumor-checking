# W-C / Input Claims

你现在负责线程 `W-C`。

你的职责是：

- 把输入新闻变成可核查的 claim-first 结构

你不是检索线程，不是 verdict 线程，也不是前端线程。

## 1. 先读这些文件

- `tasks/high-score-final-execution-plan.md`
- `backend/app/services/input_normalizer.py`
- `backend/app/services/claim_extractor.py`
- `backend/app/services/question_resolver.py`
- `backend/app/services/content_check_builder.py`
- `backend/app/models/schemas.py`
- `rules/origin_problem_statement.md`
- `rules/evidence_and_verdict_rules.md`

## 2. 你允许修改的文件

- `backend/app/services/input_normalizer.py`
- `backend/app/services/claim_extractor.py`
- `backend/app/services/question_resolver.py`
- 输入理解与 claim 拆解相关测试

## 3. 你默认不要修改的文件

- `contracts/*`
- `backend/app/services/retrieval_*.py`
- `backend/app/services/timeline_builder.py`
- `backend/app/services/verdict_engine.py`
- `backend/app/services/report_builder.py`
- `frontend/*`

## 4. 本线程核心目标

1. 把复杂新闻拆成多个原子 claim
2. 区分事实、观点、预测、不可核验
3. 做更稳的实体锚定
4. 给检索线程提供 claim 级输入

## 5. 当前优先任务

优先完成：

- `T03` 输入理解与 Claim 拆解

## 6. 本轮必须完成的事

1. 让复杂新闻不再只输出粗粒度 claim
2. 识别引语、转述、观点、猜测和情绪化表达
3. 做人名、机构名、地点、时间标准化
4. 给每条 claim 打标签：`核心 / 附加细节 / 观点延伸`
5. 为每条 claim 生成更适合 retrieval 的 query 输入结构
6. 处理截图流言、聊天记录、爆料体这类高噪声输入

## 7. 不要做的事

1. 不要自己写 retrieval 逻辑
2. 不要自己定义 overall score 字段
3. 不要碰前端显示逻辑

## 8. 开始前先写

在对应任务文档下先回写：

- 本轮执行任务
- 执行步骤
- 计划修改文件

## 9. 完成标准

你这轮完成的标准是：

1. “哪些是真实、哪些是观点、哪些可能有误”在结构上可做出来
2. 检索线程不再拿整段新闻当一个 query 去查
3. 高风险 case 的主体锚定明显更稳

## 10. 交付物

你结束时必须明确给出：

1. claim 输出示例
2. claim 类型规则说明
3. 实体锚定策略说明
4. retrieval 线程如何消费这些 claim 的说明
