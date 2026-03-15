# 演示前 Smoke Checklist

适用对象：主控、演示者、临时接手机器的同学
建议预留时间：复试前 15 到 20 分钟

通过规则：
- `Go / 讲 mock demo + 边界`：页面能打开，`expired-yogurt` 可跑，演示者能说清 `live / mock / replay / fallback`。
- `Go / 讲保底 fallback`：后端不稳时，demo payload 和前端 `safe_mode` 降级路径仍可演示，但必须主动说明不是 live 结果。
- `No-Go / 讲真实检索较真`：在出现 `backend_live + retrieval_live` 的正式通过样本前，不要对外这么讲。

配套总表：
- 高分路线样例与回归入口：`overview/14_high-score-golden-cases.md`

## 0. 先决定今天走哪条路径

[ ] 选择今天是“mock demo 路径”、“保底 fallback 路径”还是“内部 live probe”
怎么检查：
先确认今天的目标是不是对外演示。如果是对外演示，默认走 `mock demo`；如果后端不稳，就改走保底 fallback；只有内部排障才尝试 `live probe`。
预期看到什么：
主控能在开场前一句话说清楚今天演示的是 mock/demo 结果、前端保底结果，还是只做内部 live 诊断。
失败后怎么处理：
如果路径都说不清，不要直接开始。先统一口径，避免把 mock 或 fallback 误讲成真实检索通过。

## 0.5 先跑高分路线快速回归

[ ] 跑一遍高分路线快速回归
怎么检查：
在仓库根目录执行：

```bash
pytest backend/tests/test_high_score_golden_cases.py -q
```

如果要在开场前多看一眼关键能力，再执行：

```bash
pytest \
  backend/tests/test_high_score_golden_cases.py \
  backend/tests/test_claim_extractor.py::test_claim_extractor_refines_provider_claims_into_atomic_claims_and_query_hints \
  backend/tests/test_api.py::test_provider_mixed_claims_surface_true_false_split_and_answer_suggestions \
  backend/tests/test_retrieval.py::test_timeline_builder_uses_retrieval_candidates[R01] \
  -q
```

预期看到什么：
三类主 case、claim 拆分、真假混杂、传播链完整度和 score guardrail 至少都能过一遍。
失败后怎么处理：
如果快速回归不过，不要临场赌口播。先退回只讲 `expired-yogurt + provenance + fallback`，并把失败点标记为受控回归问题。

## 1. 启动前准备

[ ] 先检查版本是否满足最低要求
怎么检查：
在后端终端执行 `python3 --version`，在前端终端执行 `node --version`。
预期看到什么：
- Python `>= 3.8`
- Node.js `>= 18.18.0`，建议 `>= 20.9.0`
失败后怎么处理：
如果 Node 低于 `18.18.0`，不要继续在当前环境跑前端；先升级 Node，或改用 Windows 本地镜像脚本对应的已升级 Node 环境。

[ ] 准备两个终端窗口
怎么检查：
一个终端给后端，一个终端给前端。默认端口保留为后端 `8000`、前端 `3020`。
预期看到什么：
两个终端都能输入命令，没有旧进程持续占用同一端口。
失败后怎么处理：
如果端口被占用，先结束旧进程，再重开。优先保留后端 `8000`。

[ ] 选择前端启动方式
怎么检查：
如果当前仓库是通过 `\\wsl.localhost\...` 挂到 Windows 下，优先用仓库现成脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\start-local-windows.ps1 -BackendUrl http://127.0.0.1:8000 -Port 3020
```

如果就是在 Linux / WSL 本地目录里跑，再用：

```bash
cd frontend
npm install
npm run dev
```

预期看到什么：
前端终端最后显示页面地址 `http://127.0.0.1:3020`，且不会立刻退出。
失败后怎么处理：
如果 Windows 直接跑 `npm run dev` 卡住或文件监听异常，改用 `frontend/start-local-windows.ps1`。

[ ] 在 Windows 本地镜像目录复跑前端检查
怎么检查：
如果当前 WSL Node 不满足版本要求，或怀疑 `node_modules/.bin/*` 可执行位异常，在 Windows PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\frontend\run-local-windows-checks.ps1 -BackendUrl http://127.0.0.1:8000
```

预期看到什么：
依次通过 `npm ci`、`npm run typecheck`、`npm test`、`npm run build`。
失败后怎么处理：
如果这里失败，不要继续把前端链路讲成“稳定可复现”；先修 Node 版本、依赖安装或本地镜像脚本。

[ ] 准备后端启动命令
怎么检查：
在仓库根目录执行：

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

预期看到什么：
后端终端持续运行，没有启动后立即报错退出。
失败后怎么处理：
如果后端启动就报错，今天不要临场扩改功能；切换到保底 fallback 路径，并把问题转给实现窗口。

## 2. 环境变量与路径选择

[ ] 确认当前不是把默认环境误讲成 live retrieval
怎么检查：
确认当前如果走对外交付，后端默认仍是：
- `ANALYSIS_PROVIDER=off`
- `RETRIEVAL_PROVIDER=mock`
- `RETRIEVAL_FALLBACK_TO_MOCK=true`

预期看到什么：
演示者知道这组变量代表的是默认 `mock/demo` 路径，不是 `real_live` 验收路径。
失败后怎么处理：
如果准备把这组环境讲成真实检索，请立即停止并改口径。

[ ] 如需 Kimi 增强，确认它是“可选增强”而不是默认依赖
怎么检查：
只有在已经显式配置 `ANALYSIS_PROVIDER=kimi` 和 `KIMI_API_KEY` 时，才把 Kimi 作为标题/摘要/claim 抽取增强打开。
预期看到什么：
团队知道默认 demo 不依赖 Kimi key，Kimi 只是在 `mock retrieval` 不变的前提下增强抽取质量。
失败后怎么处理：
如果现场没有可用 key，直接回到 `ANALYSIS_PROVIDER=off` 的默认基线，不要临时改默认口径。

[ ] 只有内部诊断才切 live probe
怎么检查：
如果今天只是内部排障，才把后端改为：
- `RETRIEVAL_PROVIDER=gdelt`
- `RETRIEVAL_FALLBACK_TO_MOCK=false`

预期看到什么：
团队明确这只是观察 `backend_live + retrieval_live` 是否出现的 probe，不是对外通过条件。
失败后怎么处理：
如果需要对外演示，不要临场切 live probe。`F8` 对这条路径的正式结果是 `0/4 real_live`。

## 3. 后端接口检查

[ ] 检查健康接口
怎么检查：
浏览器打开 `http://127.0.0.1:8000/docs`，或在 PowerShell 里执行：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/health | ConvertTo-Json -Depth 4
```

预期看到什么：
返回 JSON 里至少包含：
- `status: ok`
- `service: rumor-checking-backend`

失败后怎么处理：
如果 health 失败，今天不要承诺真实接口联调；直接切到保底 fallback 路径。

[ ] 检查一次最小 analyze 接口
怎么检查：
在 PowerShell 里执行：

```powershell
$body = @{
  raw_input = '3月1日海州市市场监管局通报海州新鲜屋部分酸奶超过保质期，涉事门店已停业整改，目前未发现大规模食物中毒病例。'
  input_type = 'text'
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/analyze -ContentType 'application/json; charset=utf-8' -Body $body | ConvertTo-Json -Depth 8
```

预期看到什么：
返回 JSON 至少满足下面 4 条：
- 有 `mode / event / timeline / claim_results / final_summary / risks / sources`
- `mode` 是 `complete_mode`
- `event.title` 里包含“海州市市场监管局”
- `timeline` 不为空，且 `claim_results` 里至少有一条 `supported`

失败后怎么处理：
如果接口 500、结构缺字段或模式明显不对，停止真实联调演示，只保留前端保底路径。

## 4. 前端页面检查

[ ] 打开页面并确认在线状态提示
怎么检查：
浏览器打开 `http://127.0.0.1:3020`。
预期看到什么：
页面顶部能看到状态胶囊。后端正常时显示后端在线；后端不通时显示后端离线或后端降级。
失败后怎么处理：
如果页面打不开，先回前端终端检查地址和端口；如果是 `\\wsl.localhost` watcher 问题，改用 `frontend/start-local-windows.ps1`。

[ ] 确认来源标签可见
怎么检查：
运行任一 demo 或 analyze 后，确认页面能看见 `backend_live / backend_mock / backend_replay / demo_payload / frontend_fallback` 之一。
预期看到什么：
结果页不会把缺 provenance 的旧 payload 或本地 fallback 误标成 live。
失败后怎么处理：
如果来源标签缺失或混乱，先不要上台讲边界，优先修前端展示。

## 5. 当前推荐的 demo 检查

[ ] Demo 1：`expired-yogurt`
怎么检查：
点击“完整模式 / 海州酸奶抽检”，再点“运行 demo”。
预期看到什么：
- 页面能稳定出结果
- 结果可用于讲完整结构化输出
- provenance 不会被误讲成 `real_live`

失败后怎么处理：
如果页面打不开或结果结构严重异常，今天不要继续做 mock demo 演示。

[ ] 受控 partial case：`morningstar-question`
怎么检查：
只在受控回归里确认，不把它排进默认对外主线。执行：

```bash
pytest backend/tests/test_high_score_golden_cases.py::test_partial_demo_candidate_stays_question_first -q
```

预期看到什么：
- `question-first` 路径能落到 `partial_mode`
- claim 里存在反驳型结论
- 它被当作“受控 mock 回归”，而不是“稳定 live demo”

失败后怎么处理：
如果这条不过，不影响今天的对外主线；直接把它降级为内部回归问题，不要带上台。

[ ] 边界 safe case：`viral-death-ambiguous`
怎么检查：
执行：

```bash
pytest backend/tests/test_high_score_golden_cases.py::test_safe_demo_candidate_refuses_to_overclaim -q
```

预期看到什么：
- 系统停在 `safe_mode`
- 会列出多种可能性
- 不会直接给出真假强结论

失败后怎么处理：
如果这条不过，今天不要讲“系统会主动保守收口”；只讲已通过的 mock demo 和 fallback。

[ ] 不把漂移样本排进默认主线
怎么检查：
确认今天的正式演示主线里不包含 `chemical-odor` 和 `morningstar-layoff`。
预期看到什么：
演示者知道这两条在 `F8` 中已经漂移，不再按稳定 partial / safe demo 使用。
失败后怎么处理：
如果仍要用这两条，必须先做单独复测并明确标注为“待复核样本”，不要当作通过样本。

## 6. fallback / 失败场景检查

[ ] 失败场景 A：后端离线时的 demo payload fallback
怎么检查：
先停掉后端，刷新前端页面，然后重新运行 `expired-yogurt`。
预期看到什么：
页面仍能出结果，并明确提示当前回退到了本地 demo payload。
失败后怎么处理：
如果后端离线后 demo 也完全打不开，今天就不能承诺稳定演示。

[ ] 失败场景 B：后端离线时的普通输入 `frontend_fallback`
怎么检查：
在后端离线状态下，不选 demo，直接输入任意一段自定义文本，再点“开始分析”。
预期看到什么：
- 状态条是保守 `safe_mode`
- 页面明确写着当前结果不是后端真实分析输出
- 时间线为空或显式提示没有可展示节点

失败后怎么处理：
如果页面伪造出完整模式或部分模式结果，不能继续演示；这会误导评审。

## 7. 已知限制确认

[ ] 演示者能主动说清楚当前限制
怎么检查：
开场前让演示者用自己的话复述下面 7 句：
- 当前最稳的是 `mock demo + provenance 边界`，不是“任意新闻都能真实较真”。
- 默认环境下 retrieval 仍主要是 `mock`，不能把它讲成真实检索通过。
- `chemical-odor` 和 `morningstar-layoff` 当前不是稳定 demo。
- `morningstar-question` 是受控 `partial` 回归，不是默认开场主线。
- `viral-death-ambiguous` 是边界演示，用来讲“不强判”，不是为了给真假结论。
- 后端没有公开 replay 接口，前端看到 `backend_replay` 也只是消费后端标签。
- 后端离线时的 `demo_payload / frontend_fallback` 只算保底演示，不是真实 analyze。

预期看到什么：
演示者能在 30 秒内把“已完成什么、没通过什么、为什么仍可演示”说清楚。
失败后怎么处理：
如果演示者自己都说不清边界，先不要开始正式演示。

## 8. 上台前最后 1 分钟确认

[ ] 最终 go / no-go 判断
怎么检查：
按下面规则三选一：
- `Go / mock demo + 边界`：页面正常、`expired-yogurt` 正常、来源标签正常，演示者会主动说明当前是 mock/demo 路径。
- `Go / 保底 fallback`：后端不稳，但 demo payload 和普通输入 safe fallback 都正常，且演示者会明确说明不是 live 结果。
- `No-Go / 真实检索较真`：如果需要讲真实检索通过，但今天拿不出 `backend_live + retrieval_live` 的正式样本，就不要这么讲。

预期看到什么：
主控能明确告诉演示者今天讲哪条路径，以及哪些话绝对不能说。
失败后怎么处理：
如果连 `mock demo` 或 `fallback` 都不稳，应该暂停演示，先修环境或回滚到最后一个稳定版本。

## 本轮实测状态（2026-03-14）

- `F8` 正式验收记录已落库在 `overview/13_f8-random-acceptance.md`。
- 自 `2026-03-15` 起，默认开发/演示基线已冻结为 `ANALYSIS_PROVIDER=off`、`RETRIEVAL_PROVIDER=mock`、`RETRIEVAL_FALLBACK_TO_MOCK=true`。
- 当前默认环境的样本主要落在 `backend_mock / retrieval_mock`，并没有形成 `real_live` 通过样本。
- `expired-yogurt` 仍可作为稳定 mock demo；`chemical-odor` 和 `morningstar-layoff` 已从稳定演示主线移除。
- live probe 在 `gdelt + 禁止 mock fallback` 条件下为 `0/4 real_live`，当前只能作为内部诊断。

## 建议交接

- `Cluster-C / Cluster-D`：优先修 `chemical-odor`、`morningstar-layoff` 的模式漂移和 live retrieval 不可用问题。
- `Cluster-G`：继续保证 README、Smoke、口播和 overview 共用同一套 `F8` 口径。
- 演示主控：如果今天要上台，只讲 `mock demo + 边界` 或 `fallback`，不要承诺真实检索已经收口。
