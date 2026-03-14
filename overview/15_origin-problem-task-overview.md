# 15 原题需求对照任务总览表

更新时间：2026-03-15 02:15（Asia/Shanghai）

这份表不是按代码量打分，而是按“是否已经能稳定支撑演示、验收和对外口径”来评估完成度。

核对依据：

- `rules/origin_problem_statement.md`
- `docs/status/current-verified-state.md`
- `overview/13_f8-random-acceptance.md`
- `backend/app/api/v1/router.py`
- `backend/app/services/analyze_pipeline.py`
- `backend/app/services/retrieval_service.py`
- `frontend/components/analyze-page.tsx`
- `frontend/components/status-banner.tsx`
- `backend/tests/test_api.py`
- `backend/tests/test_retrieval.py`

## 1. 结论先行

- 综合完成度估计：`72%`
- 当前已经具备：`可运行的前后端闭环`、`mock/demo 可演示路径`、`传播链/内容核查的结构化页面`、`明确的 provenance 和保守降级`
- 当前不能宣称：`真实 live retrieval 已稳定通过`、`任意新闻都能稳定较真`
- 如果今天要上台：
  - `Go`：讲 `mock demo + 边界 + explainability`
  - `No-Go`：讲“真实开放场景已经稳定较真”

## 2. 完整任务总览表

| ID | 任务包 | 对应题意 / 评分点 | 状态 | 完成度 | 当前结论 |
| --- | --- | --- | --- | ---: | --- |
| T1 | 输入接入与标准化 | 支持新闻文本、URL、问题输入 | `◐ 部分完成` | `80%` | 文本 / URL / 问题三类输入都已接入，URL 也有 fallback，但 URL 仍只覆盖公开 HTML。 |
| T2 | 传播链还原主链 | 还原从发酵到高峰的传播过程 | `◐ 部分完成` | `65%` | 已能输出 `origin / amplification / turn / clarification` 时间线，但真实 live 样本仍未通过最终验收。 |
| T3 | 内容核查主链 | 区分事实、观点、可能有误内容 | `◐ 部分完成` | `78%` | claim 抽取、verdict、content check、问题拆解都已落地，但 verdict 仍偏启发式，且 question case 出现模式漂移。 |
| T4 | 前端工作台与体验 | Web GUI、交互、结果表达 | `☑ 基本完成` | `88%` | 单页工作台、三档模式、风险/证据/时间线/链路追踪都已经在页面中联通。 |
| T5 | Provenance 与可解释性 | AI 原生思维、边界清晰、不伪装结果 | `☑ 基本完成` | `90%` | `live / mock / replay / demo / fallback` 标签、fallback 提示、process trace 都已经落地，这是当前比较强的加分项。 |
| T6 | AI 与真实检索增强 | Provider、联网检索、开放输入帮助性 | `◐ 部分完成` | `60%` | Kimi enrichment、GDELT/Kimi web search、cache 都已接入，但 live 路径稳定性不足。 |
| T7 | 工程质量与验收 | 测试、类型、回归、可维护性 | `◐ 部分完成` | `58%` | 后端大部分回归可跑，但已有 2 个关键回归漂移；前端 `typecheck` 当前为红，测试运行链也不稳定。 |
| T8 | Demo 交付与答辩准备 | README、smoke、demo 资产、口播一致性 | `◐ 部分完成` | `72%` | 运行说明、Smoke、Demo Script 已有，但稳定 demo 实际只剩 1 条真正安全。 |

## 3. 最新验证快照

- `pytest backend/tests/test_api.py backend/tests/test_retrieval.py backend/tests/test_kimi_provider.py backend/tests/test_kimi_provider_quality.py -q`
  - 结果：`41 passed, 2 failed`
  - 当前失败：
    - `backend/tests/test_api.py` 的 `test_analyze_question_only_can_surface_partial_mode_with_retrieval_evidence`
    - `backend/tests/test_retrieval.py` 的 `test_kimi_question_retrieval_keeps_raw_rumor_phrasing`
  - 含义：问题型输入至少有一条链路从预期 `partial_mode` 漂到了 `complete_mode`
- `cmd /c "pushd ...\\frontend && npm run typecheck && popd"`
  - 结果：失败
  - 当前错误集中在：
    - `frontend/lib/api-client.ts`
    - `frontend/lib/report-utils.ts`
  - 含义：前端类型层和 provenance badge 拼装逻辑还没有收口
- `cmd /c "pushd ...\\frontend && npm test && popd"`
  - 结果：失败
  - 当前报错：`ERR_RESOLVE_PACKAGE_ENTRY_FAIL`
  - 含义：前端测试资产在仓库中存在，但现环境下测试执行链不稳定

## 4. 分任务详表与增强子任务

### T1 输入接入与标准化

当前状态：`◐ 部分完成（80%）`

已完成：

- 文本、URL、问题三类输入都已进入同一条 `analyze` 主链
- URL 支持公开 HTML 抽取，并能回填标题、摘要、来源、发布时间
- 非 HTML、超时、正文缺失、抓取失败时会给出明确 fallback

主要缺口：

- URL 仍不支持登录页、强反爬、浏览器渲染页面、PDF 和图片正文
- 问题输入对人物、事件锚点的收束仍容易漂移

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T1.1 扩展 URL 抽取覆盖面 | 在 `InputNormalizer / UrlContentExtractor` 后补一层内容类型识别，按 HTML / PDF / 图片 / 动态页分流；对不支持类型直接给出“建议粘贴正文”的明确提示。 | 现在 URL 能力只覆盖一部分新闻页面，扩展后才更接近真实使用场景。 | `高`。原题允许 URL 类新闻输入，不补这层会持续限制真实覆盖率。 |
| T1.2 做更强的实体与时间锚点归一 | 在 normalize 阶段抽出实体、地点、时间表达，并把它们写入 retrieval query 和 investigation 视图。 | 问题型输入能不能对准真实事件，首先取决于锚点是否稳定。 | `高`。这直接影响 question case 的命中率和误判率。 |
| T1.3 增加输入诊断反馈 | 前端在提交前后展示“当前输入缺什么信息”，例如缺人名、缺来源、缺时间点。 | 用户更容易知道该补什么，而不是看到 safe_mode 却不知道原因。 | `中`。对演示体验和真实使用体验都很有帮助。 |

### T2 传播链还原主链

当前状态：`◐ 部分完成（65%）`

已完成：

- retrieval bundle、去重归并、timeline builder 都已经接入主链
- 页面能展示 `origin / amplification / turn / clarification`
- 当拿不到证据时，系统会退回保守时间线或空时间线，不会硬造链路

主要缺口：

- `overview/13_f8-random-acceptance.md` 明确记录：`real_live = 0`
- 当前时间线仍偏启发式，不是可靠的“传播高峰求解器”
- 峰值节点和转折解释还不够 grounded

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T2.1 先把 live retrieval 稳定下来 | 处理 `ConnectError / 429 / JSONDecodeError`，加 provider 重试、退避、缓存复用和失败分类。 | 没有稳定 live 证据，就不可能稳定还原真实传播链。 | `最高`。这是传播链能力能不能对外讲的前置条件。 |
| T2.2 为时间线节点加 grounded 评分 | 在 `timeline_builder` 中加入来源等级、实体一致性、时间跨度、转述密度的综合评分，再决定 `origin / turn / clarification`。 | 能减少“抓到几条结果就抬成完整传播链”的误报。 | `高`。当前最缺的是可信度，而不是节点数量。 |
| T2.3 补“高峰”和“扩散原因”层 | 基于转载密度、发布时间集中区间、来源类型，额外标出 peak 和 amplification 的解释性文案。 | 原题强调“从发酵到高峰”，现在更像“关键节点列表”，不是完整传播过程。 | `中高`。这是从“可看”升级到“像新闻观察员”的关键。 |

### T3 内容核查主链

当前状态：`◐ 部分完成（78%）`

已完成：

- claim 抽取、claim 类型区分、verdict、confidence 都已输出
- `content_check`、`investigation`、`final_summary` 已经组成更易讲解的结果层
- 页面可以把内容拆成“更像真的 / 更像加料的 / 观点 / 仍待核查”

主要缺口：

- verdict 仍主要依赖关键词、来源等级、启发式规则
- question case 有“该 partial 却升到 complete”的漂移
- 对“冲突证据”与“证据不足”的边界还不够稳
- 新观察到的具体失败模式：`晨星生物是不是裁员了？` 这类输入会先把主体猜向 `Morningstar`，再拼接“生物医药行业裁员潮”等背景，最后给出低信心但方向跑偏的回答；说明主体锚定、检索约束和判定门槛还没收紧

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T3.1 给 `complete_mode` 增加硬门槛 | 在 `report_builder / verdict_engine` 里增加门槛，例如：没有至少 2 条高可信证据且无冲突时，不允许从 `partial_mode` 升到 `complete_mode`。 | 能直接压住当前 `question` 类输入的模式漂移。 | `最高`。这关系到是否会把谣言误讲成已核实事实。 |
| T3.2 强化反证与冲突聚合 | 对同一 claim 的支持证据、反证、澄清证据分桶，再统一做冲突判定。 | 现在系统能判 supported/refuted，但对“公开来源打架”的场景还不够强。 | `高`。原题不是只要能判真，还要能把不确定性讲清楚。 |
| T3.3 校准 `content_check` 话术层 | 让 `content_check` 不只是 claim 映射，而是显式说明“哪部分是事实、哪部分是观点、哪部分可能有误”。 | 这能更直接贴题，也更适合答辩时展示“内容核查”这一半题目。 | `高`。当前功能有了，但题意映射还可以更直接。 |

### T4 前端工作台与体验

当前状态：`☑ 基本完成（88%）`

已完成：

- 单页工作台已经联通输入、状态、事件、时间线、claim、证据、风险、内容核查、问题拆解、链路追踪
- demo case、后端健康检查、失败回退都接上了
- 三档模式在页面上有明确区分

主要缺口：

- 页面虽然功能齐，但“claim 和 evidence 的对应关系”还可以更直观
- 当前没有面向答辩的导出或分享视图

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T4.1 增加 claim 到 evidence 的联动高亮 | 点击 claim 时，只高亮对应证据和时间线节点。 | 能让“为什么判成这样”变得一眼可见。 | `中高`。这会明显提升答辩演示效果。 |
| T4.2 做一个演示导出视图 | 输出一页精简版 markdown 或只读页面，保留结论、时间线、claim 和来源。 | 演示和复盘时更容易固定证据，不用手动截屏拼接。 | `中`。不是主链必需，但对答辩很有价值。 |
| T4.3 补“继续核查建议”交互 | 在 safe / partial 模式下提示用户补什么输入最有帮助。 | 系统不再只是告诉用户“证据不足”，而是告诉用户“下一步怎么查”。 | `中`。能把产品体验从展示型提升到助手型。 |

### T5 Provenance 与可解释性

当前状态：`☑ 基本完成（90%）`

已完成：

- 后端 `report.provenance` 已进入最终响应
- 前端能明确区分 `backend_live / backend_mock / backend_replay / demo_payload / frontend_fallback`
- `pipeline_trace`、`investigation`、fallback 标签都已经是页面的一部分

主要缺口：

- provenance 术语还没有完全冻结
- trace 和具体证据、claim 的跳转关系还比较松

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T5.1 冻结 provenance 词表 | 把 `source_type / evidence_source / timeline_source / fallback_reason` 的对外术语固定下来，并同步 README、页面、Smoke。 | 避免答辩时不同文档说法不一致。 | `高`。这已经是项目的一个亮点，应该把口径彻底统一。 |
| T5.2 让 trace 可回跳到具体卡片 | trace 的每一步都能定位到对应的 claim、证据或时间线节点。 | 调试链路就不再只是“看步骤”，而是能帮助现场解释“这步产出了什么”。 | `中高`。能显著提升 explainability 的展示效果。 |
| T5.3 暴露更细的 fallback 原因 | 把 URL 抽取失败、检索失败、provider 失败分别展示到页面。 | 用户更容易理解是“没查到”还是“链路坏了”。 | `中`。对真实使用和演示都更友好。 |

### T6 AI 与真实检索增强

当前状态：`◐ 部分完成（60%）`

已完成：

- Kimi enrichment、Kimi web search、GDELT provider、retrieval cache 都已接入
- question 输入已有 query rewrite 和 follow-up retrieval
- provider 失败时会自动回退，不会打断主流程

主要缺口：

- 真实 provider 稳定性不足
- live 检索没有形成正式通过样本
- AI 帮助性有，但还没被系统化验收和版本管理

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T6.1 做 prompt 与 provider 的版本化验收 | 给 provider prompt 编版本，绑定固定小样本和通过标准。 | 现在 provider 像“可用能力”，还不是“可控能力”。 | `高`。不做这层，后面会继续出现漂移但难以定位。 |
| T6.2 做多 provider 检索编排 | 把 `gdelt / kimi web search / mock` 明确成主、备、保底三层，而不是单点切换。 | 能显著提高 live 命中率和鲁棒性。 | `高`。真实检索不稳定时，这是最现实的增强路线。 |
| T6.3 利用 stale cache 做保守保真 | 区分“实时失败但有旧可信结果”和“完全无结果”两类场景。 | 可以减少一失败就全变 safe_mode 的抖动。 | `中高`。对开放输入帮助性很重要。 |

### T7 工程质量与验收

当前状态：`◐ 部分完成（58%）`

已完成：

- 后端已有较完整的 API、retrieval、provider 测试
- 文档里已有 Smoke 和验收记录

主要缺口：

- 当前后端关键回归不是全绿
- 前端 `typecheck` 当前失败
- 前端测试命令当前环境下不稳定

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T7.1 修复 question case 模式漂移回归 | 先定位 `partial_mode -> complete_mode` 的抬升条件，再补测试和门槛。 | 这是当前最直接的功能风险。 | `最高`。不修它，内容核查结论不可信。 |
| T7.2 修复前端类型错误 | 先收口 `api-client.ts` 的 `claim_type` 类型，再收口 `report-utils.ts` 的 badge 联合类型。 | 类型不稳说明前端协议层还没完全冻结。 | `高`。这会直接影响构建和后续改动安全性。 |
| T7.3 稳定前端测试运行链 | 统一在 Windows 本地镜像目录或标准 Linux Node 环境跑 `vitest`，避免 UNC / 可执行位 / package entry 混乱。 | 现在不是“没有测试”，而是“测试资产无法稳定执行”。 | `高`。没有稳定执行链，前端回归就形同虚设。 |
| T7.4 新增模式漂移验收集 | 单独维护 demo case 和 question case 的模式验收，不让 `safe`、`partial`、`complete` 悄悄漂。 | 这能直接守住演示可信度。 | `高`。当前问题已经说明它是必要的。 |

### T8 Demo 交付与答辩准备

当前状态：`◐ 部分完成（72%）`

已完成：

- README、SMOKE_CHECKLIST、DEMO_SCRIPT、运行说明都已经存在
- 当前口径已经明确区分 `mock demo / live probe / replay / frontend fallback`

主要缺口：

- 稳定 demo 实际只剩 `expired-yogurt` 一条可放心讲
- replay 还是内部能力，没有公开交付路径
- 文档、代码、验收虽然大体一致，但还没完全冻结

| 子task | 准备怎么做 | 为什么能增强功能 | 必要性 |
| --- | --- | --- | --- |
| T8.1 冻结 3 条稳定 demo case | 每条 demo 都补验收快照、预期 mode、预期 provenance、禁止口播点。 | 这样答辩时才不会临场漂移。 | `最高`。没有稳定 demo，就没有稳定演示。 |
| T8.2 决定 replay 是否公开 | 要么补 replay HTTP 接口与说明，要么明确继续保持内部能力，不再模糊。 | 现在 replay 介于“有”与“没有”之间，容易讲乱。 | `中高`。这关系到演示边界是否清晰。 |
| T8.3 把 README / Smoke / Demo Script 再收一次口径 | 所有文档都统一成“mock 可讲、live 不可夸”的版本。 | 项目本身已经有解释边界的能力，文档应该与之完全一致。 | `高`。这能避免答辩时被文档反向打脸。 |

## 5. 建议的下一步优先级

1. `P0`：先做 `T2.1 + T3.1 + T7.1`
2. `P0`：再做 `T7.2 + T7.3`
3. `P1`：冻结 `T8.1 + T8.3`
4. `P1`：补 `T1.2 + T2.2 + T6.1`
5. `P2`：最后再决定 `T8.2` 和更大的 URL 覆盖面增强

## 6. 一句话判断

当前项目已经不是“还没做完”的状态，而是“主闭环已经成型，但真实 live 能力、模式稳定性和工程收口还没达到可放心夸口的程度”。
