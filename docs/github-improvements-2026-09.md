# GitHub 参考与本次优化

本次实际克隆并阅读了四个项目的固定版本，并在当前运行时中实现改进。没有引入新 Agent 框架或复制上游源码。

| 项目 | 参考内容 | 本项目落地 |
| --- | --- | --- |
| [DEFAME](https://github.com/multimodal-ai-lab/DEFAME/tree/0d5c2eb5e07cfa8a673351e765c9c576070cdd6c)，Apache-2.0 | `defame/common/label.py` 区分无证据、反证与可靠来源冲突；问答提示词强调完整主体和核查事项 | 数量按事项、单位及上下文配对，无法对齐时保留不足；LLM 判定支持已有四态 |
| [w3lib](https://github.com/scrapy/w3lib/tree/537c5d46455ae8b2c67b53fc03b36ef1da8c4837)，BSD-3-Clause | `w3lib/url.py` 分别规范主机、路径、参数 | 保守 URL 身份去重，原始 URL 保持用于抓取和引用 |
| [OpenInference](https://github.com/Arize-ai/openinference/tree/732eec1b0d7e5c753f22ea9ac328132003372dd1)，Apache-2.0 | `spec/semantic_conventions.md`、Haystack instrumentation 的检索类型和父子关系 | 检索各阶段 span、Phoenix `RETRIEVER/CHAIN`、前端分阶段数量和缓存详情 |
| [Haystack](https://github.com/deepset-ai/haystack/tree/f4e004c34cbc724b3ffb026debdf7a0541e4a21f)，Apache-2.0 | `document_joiner.py` / `utils/misc.py` 中基于稳定文档身份的排名融合 | 先修复身份和合并链路；目前结果顺序已经按日期重排，不能冒充原搜索排名启用 RRF |

## 准确性

原规则将正文中任意不同数字当作冲突。已执行的反例：

| 声明与证据 | 修改前 | 修改后 |
| --- | --- | --- |
| 招聘 2000 人；公告确认招聘 2000 人，工资最高 8000 元 | 错误反驳 | 支持 |
| 裁员 50 人；公告说员工共 500 人、本轮裁员 50 人 | 错误冲突 | 支持 |
| 招聘 2000 人；公告同时说安排 10 个部门参加 | 错误冲突 | 支持 |

新比较保留局部主体/地点上下文、时间、数量属性、统计范围、薪资周期、边界值和更正关系。缺少可匹配维度时不再把相关词重叠当作数量证实。人员单位及十进制规模可归一，但没有宣称覆盖所有中文数词、单位、实体共指或时间关系。多主体声明逐项匹配；真正同口径更正和未解决来源冲突仍保留。

LLM 主裁判的 prompt 和解析白名单补上 `conflicting`，提示缺少支持不等于反驳，并拒绝畸形返回。四态是原公开契约已有值，不需要新增公开 Report 字段。

## 检索链路

已执行以下结果组数对照：

| 场景 | 修改前 | 修改后 | 应有组数 |
| --- | ---: | ---: | ---: |
| 路径 `/News` 与 `/news` 的不同文章 | 1 | 2 | 2 |
| 同页面带不同 `utm_source` | 2 | 1 | 1 |
| 两篇空 URL 的不同文章 | 1 | 2 | 2 |
| 同页面、同 provider ID | 2 | 1 | 1 |
| 三篇独立文章，其中存在歧义 `duplicate_of` | 1 | 3 | 3 |

URL 比较保留业务参数顺序、路径大小写、hash 路由；拒绝损坏 URL。相似标题本身不再触发合并，保留金额、正负数或否定不同的报道；明确页面身份、无歧义转载关系及同标题同实质摘要仍可合并。重复合并保留已有 merged IDs/notes。更保守的内容去重可能保留更多相似报道，独立来源数仍按原独立性规则计算，不能直接等于不同 URL 数。

## 可观测性

沿用 `AGENT_TRACE_ENABLED` 和现有调用记录面板，增加：

- `retrieval.round`：整轮最终结果、独立/高信任来源、证据覆盖等级、失败数。
- `retrieval.query`：真实搜索请求及其 LLM 子节点、结果数和错误类别。
- `retrieval.cache`：命中、未命中、写入、使用过期缓存。
- `retrieval.selection`：噪声、导航页、主题/相关性过滤、软回退以及去重。
- `retrieval.supplement` / `retrieval.official_boost`：补充源与官方源查询失败及耗时。
- 轻量 `complete_once` 模型通道也记录每次实际 HTTP 尝试，覆盖 LLM 判定、纠错等原先漏记的调用。

Phoenix 使用标准 `RETRIEVER` / `CHAIN` kind。新增 metadata 不记录原始查询、URL、正文或异常文本；provider/stage 用固定值白名单。前端只展示白名单统计，未记录值不伪装成零。不同 selection 可能处理同一批材料，不能跨父子节点求和。`partial` 表示子操作失败，即使过期缓存已成功提供降级结果。

## 验证与边界

验证覆盖独立复查发现的误判反例、去重误合并、畸形 URL 完整过滤路径、缓存与并发父子关系、观测写入失败不影响业务、隐私 sentinel、真实内存 OTel 导出，以及桌面和 390/320px 真实页面检索详情。页面使用实际 RetrievalService 产生的合成 trace，经真实 FastAPI/Next.js 展示；没有浏览器端伪造接口响应。

已有外部开发集的纯规则前后对照没有观察到整体提升：CFEVER 开发分区标签/完整 URL 组为 4/12，健康集为 1/8，context 开发分区为 4/4。这些已给定声明和证据的回放不测真实搜索召回；不能将它们宣传成端到端核查准确率。未使用留出集调规则。代码冻结后的一次留出验收：CFEVER 4/12，context 3/4；hard 既有回归为 5/8，001、003、007 的错误标签保留。这说明本轮修复了已证明的误判类别，尚未提高这些外部数据上的整体规则准确率。

原通用网关配置的四个合成判定场景未返回有效结果，诊断为 HTTP 400 鉴权失败；两个真实失败尝试均记录为 `stage_key=llm_verdict`、`status=error`、`usage_reported=false`，不会把未知消耗记成已报告零。

随后使用本机 JoyCode 的 DeepSeek-V4-Pro 完成真实模型验收：招聘人数与工资旁支数字、同口径来源冲突、无数量证据、明确更正四个合成给定证据用例全部返回有效 JSON，分别判为 supported、conflicting、insufficient、refuted。四次请求均为 HTTP 200，原 `llm_verdict → complete_once` 路径记录完整父子 LLM span、成功状态和 usage；共 1,685 Tokens，其中缓存读取 512 Tokens（输入子集）。本地临时适配 JoyCode 路由/鉴权并关闭 thinking，未修改项目默认模型或保存凭据。这是给定合成证据的模型验收，不代表完整检索端到端或总体准确率。

机器可读的本地对照摘要保存在 `artifacts/github-improvements-evaluation.json`（不包含凭据、网关地址或提示词）。既有无日期/过期证据与困难样本诊断保留，不改 gold 来获取通过。

架构决策：[ADR 0012](adr/0012-evidence-alignment-and-retrieval-tracing.md)。相关使用说明：[模型调用可观测性](model-call-observability.md)。

## 最终本地门禁（2026-09-30）

- 契约：16 个公开模型一致；没有新增公开报告字段。
- 后端：1,467 项测试通过，62 条既有 httpx/Starlette 弃用警告；Ruff 通过。
- 前端：182 项测试、TypeScript 检查、生产构建通过。
- 浏览器：真实检索 trace 的缓存命中/部分失败详情在桌面、390px、320px 验收通过，无横向溢出或页面脚本错误。
- 数据审计通过。默认回放标签/完整证据组 8/8，seed_015 的无日期/过期诊断仍存在；其它语料结果见上文，不将命令退出成功等同于全部样例判定正确。
- `git diff --check` 通过。后端沿用 `/tmp/rumor-observability-venv/bin/python`，环境限制见模型观测文档。

## 本次提交的隔离门禁

本次只提交可观测性、数量判定与检索身份改动；上述外部评测集和其它既有开发功能没有一并提交。在当前 main 基础上隔离应用这些改动后：后端 976 项、前端 109 项测试通过，7 个契约模型一致，Ruff、类型检查和生产构建通过。仓库原有默认 18 个回放的标签为 16/18、完整证据组为 18/18；保留失败诊断。可观测性首个提交的精确暂存版本另通过 99 项定向测试。
