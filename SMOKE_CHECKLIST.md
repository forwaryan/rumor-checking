# 演示前 Smoke Checklist

适用对象：主控、演示者、临时接手机器的同学
建议预留时间：复试前 15 到 20 分钟

通过规则：
- 能打开前端页面，并完整走完 `complete_mode / partial_mode / safe_mode` 三条稳定 demo。
- 如果后端可用，再补 `health` 和 `analyze` 接口检查。
- 如果后端不可用，必须切换到“保底演示模式”，并在开场明确说明当前展示包含本地 demo fallback，不把它说成真实在线检索结果。

## 0. 先决定今天走哪条演示路径

[ ] 选择“完整联调模式”还是“保底演示模式”
怎么检查：
先判断后端今天能不能正常启动。如果 `http://127.0.0.1:8000/api/v1/health` 能返回 `status = ok`，走完整联调模式；如果后端启动失败或接口无响应，直接走保底演示模式。
预期看到什么：
主控能在开场前一句话说清楚今天是“真实接口联调演示”还是“前端本地 demo 保底演示”。
失败后怎么处理：
如果后端不稳，不要现场边修边试。直接切到保底演示模式，只演示三条稳定 demo 和安全回退场景，并主动说明 `C10`、`D5 ~ D7` 仍在收口。

## 1. 启动前准备

[ ] 准备两个终端窗口
怎么检查：
一个终端给后端，一个终端给前端。默认端口保留为后端 `8000`、前端 `3020`。
预期看到什么：
两个终端都能输入命令，没有旧进程持续占用同一端口。
失败后怎么处理：
如果端口被占用，先结束旧进程，再重开。优先保留后端 `8000`，前端次选改端口，但要同步告诉演示者新地址。

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
如果 Windows 直接跑 `npm run dev` 卡住或文件监听异常，不要继续硬试，直接改用 `frontend/start-local-windows.ps1`。

[ ] 准备后端启动命令
怎么检查：
在仓库根目录执行：

```bash
python -m pip install -r backend/requirements-dev.txt
uvicorn backend.app.main:app --reload
```

如果要接真实 provider，再补 `backend/.env`，但演示前 smoke 不是必须项。
预期看到什么：
后端终端持续运行，没有启动后立即报错退出。
失败后怎么处理：
如果后端启动就报错，直接记录错误信息，不要现场扩改功能；切换到保底演示模式，并把问题转给 `Cluster-D / Retrieval` 或 `Cluster-C / API`。

## 2. 后端接口检查

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
如果 health 失败，今天不要承诺真实接口联调；直接切到保底演示模式。

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
如果接口 500、结构缺字段、或模式明显不对，停止真实联调演示，只保留前端离线 demo，并把错误交给 `Cluster-C` 与 `Cluster-D` 联合处理。

## 3. 前端页面检查

[ ] 打开页面并确认在线状态提示
怎么检查：
浏览器打开 `http://127.0.0.1:3020`。
预期看到什么：
页面顶部能看到“单页 rumor-checking 工作台”，输入区右上角有状态胶囊。后端正常时应显示“后端在线”；后端不通时显示“后端离线”或“后端降级”。
失败后怎么处理：
如果页面打不开，先回前端终端检查地址和端口；如果是 `\\wsl.localhost` watcher 问题，改用 `frontend/start-local-windows.ps1`。

[ ] 确认输入区可以手动输入，也能选 demo
怎么检查：
页面上应能看到：
- 输入类型切换：`自动判断 / 正文 / URL / 问题`
- 文本输入框
- 三个 demo 卡片
- `开始分析` 或 `运行 demo` 按钮
预期看到什么：
点击任一 demo 卡片后，输入框会自动填入示例文本，主按钮会变成“运行 demo”。
失败后怎么处理：
如果 demo 卡片不能填充输入框，不要继续演示真实链路；先记录为前端交互回归，交给 `Cluster-E / Experience Shell`。

## 4. 三条稳定 demo 检查

[ ] Demo 1：完整模式 `expired-yogurt`
怎么检查：
点击“完整模式 / 海州酸奶抽检”，再点“运行 demo”。
预期看到什么：
- 状态条标题是“完整模式 / 主要链路已连通”
- 事件标题包含“海州市市场监管局通报海州新鲜屋酸奶抽检结果”
- 时间线至少有 2 个节点
- claim 至少 4 条，其中至少 2 条是 `supported`
失败后怎么处理：
如果页面落成 `safe_mode`，先看后端是否在线；若后端离线但页面仍能展示本地 payload，可继续演示，但必须说明这是 demo fallback，不是真实联调结果。

[ ] Demo 2：部分模式 `chemical-odor`
怎么检查：
点击“部分模式 / 化工厂异味核查”，再点“运行 demo”。
预期看到什么：
- 状态条标题是“部分模式 / 局部结果可用”
- 事件标题包含“北城区化工厂异味投诉仍处在核查阶段”
- claim 至少 4 条
- 至少 1 条 verdict 是 `conflicting`
- 风险区能看到“存在相互冲突的证据”这一类提示
失败后怎么处理：
如果没有冲突 verdict，而是一边倒结论，不要继续把它当作 partial 模式讲，先记录为 `D5 ~ D7` 侧的判定或时间线回归。

[ ] Demo 3：安全模式 `morningstar-layoff`
怎么检查：
点击“安全模式 / 晨星生物裁员传闻”，再点“运行 demo”。
预期看到什么：
- 状态条标题是“安全模式 / 关键证据不足”
- 事件标题是“待核实事件”或明显保守的事件名称
- 时间线为空，或页面明确显示没有可展示的传播节点
- claim verdict 全部是 `insufficient`
失败后怎么处理：
如果页面给出很确定的真伪结论，不要带着这个结果上台；这说明边界收口失效，需要回给 `Cluster-D / Retrieval` 和 `Cluster-C / API`。

## 5. fallback / 失败场景检查

[ ] 失败场景 A：后端离线时的 demo fallback
怎么检查：
先停掉后端，刷新前端页面，确认输入区右上角显示“后端离线”。然后重新运行任意一个 demo。
预期看到什么：
页面仍能出结果，但状态条下方应出现下面两类提示之一：
- “后端当前离线，页面已直接回退到本地 demo payload”
- “真实 analyze 请求失败，页面已回退到同主题本地 demo payload”

失败后怎么处理：
如果后端离线后 demo 也完全打不开，今天就不能承诺稳定演示，必须先修前端 fallback，再安排复测。

[ ] 失败场景 B：后端离线时的普通输入 safe fallback
怎么检查：
在后端离线状态下，不选 demo，直接输入任意一段自定义文本，再点“开始分析”。
预期看到什么：
- 状态条标题是“安全模式 / 关键证据不足”
- 事件标题是“接口暂不可达，当前展示安全模式回退结果”
- 时间线为空
- 风险区明确写着“当前结果不是后端真实分析输出”这一类提示
失败后怎么处理：
如果页面伪造出完整模式或部分模式结果，不能继续演示；这会误导面试官，必须先修 fallback 边界。

## 6. 已知限制确认

[ ] 演示者能主动说清楚当前限制
怎么检查：
开场前让演示者用自己的话复述下面 4 句，确认不会过度承诺：
- URL 输入当前还是保守 fallback，正文抽取尚未接入，这部分依赖 `C10`。
- verdict、evidence、timeline 目前仍偏规则和场景库驱动，真实开放检索和传播链还原仍依赖 `D5 ~ D7` 收口。
- 前端 demo 现在依赖本地 payload，不依赖后端 `demo-cases / replay` 接口。
- 口播脚本与最终 README 还需要 `G5 / G6` 最后收口。

预期看到什么：
演示者能在 30 秒内把“已完成什么、没完成什么、为什么还能演示”说清楚。
失败后怎么处理：
如果演示者自己都说不清边界，先不要开始正式演示，至少先统一口径。

## 7. 上台前最后 1 分钟确认

[ ] 最终 go / no-go 判断
怎么检查：
按下面规则二选一：
- `Go / 完整联调`：后端 `health` 正常、前端页面正常、三条 demo 正常、至少一次真实 `analyze` 正常。
- `Go / 保底演示`：前端页面正常、三条 demo 正常、至少一个失败回退场景正常，且演示者会主动说明当前是 fallback 演示。

预期看到什么：
主控能明确告诉演示者“今天讲真实联调”还是“今天讲稳定 demo + 边界”。
失败后怎么处理：
如果连保底演示都不稳，应该暂停演示，先修环境或回滚到最后一个稳定版本。

## 本轮实测状态（2026-03-13）

- 已完成：`tasks/cluster-f-quality-gate.md` 中 `F7` 的任务拆解与回写。
- 已完成：本文件作为根目录可交付 smoke checklist，覆盖环境、后端、前端、三条 demo、接口、fallback 和已知限制确认。
- 已确认：前端稳定 demo 的输入与预期模式对齐 `frontend/lib/demo-cases.ts`，三条分别是 `expired-yogurt / chemical-odor / morningstar-layoff`。
- 已确认：前端实际 fallback 行为与页面提示已在 `frontend/components/analyze-page.tsx` 和 `frontend/lib/report-utils.ts` 收口。
- 当前阻断：本轮运行 `pytest backend/tests/test_api.py -q` 和 `pytest backend/tests/test_retrieval.py -q` 时，后端在导入阶段失败，暴露出 retrieval 侧文件漂移，当前至少包含 `Settings` 缺少 `retrieval_provider` 字段，以及 `retrieval_service.py` 与 `retrieval_cache.py` / `test_retrieval.py` 的接口版本不一致。
- 结论：今天可以交付 checklist，但“真实后端 smoke 可通过”这一项当前不能判定为通过，需要 `Cluster-D` 先把 retrieval 相关实现收口，再由 `Cluster-F` 或主控复跑接口 smoke。

## 建议交接

- `Cluster-D / D5 ~ D7`：优先统一 `retrieval_service.py`、`retrieval_cache.py`、`retrieval_provider.py`、`analyze_pipeline.py` 与测试的接口版本，恢复后端可启动和 retrieval 回归可跑。
- `Cluster-C / API`：在 retrieval 修复后复跑 `health` 与 `analyze` 主链路，确认 `complete / partial / safe` 三档没有被回归破坏。
- `Cluster-G / G5 / G6`：把本 checklist 融入最终 demo 口播脚本和 README，保证主控、演示者、评审看到的是同一套口径。
