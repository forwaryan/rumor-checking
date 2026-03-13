# Frontend

本目录用于存放 Web Demo 前端实现。

当前仅预留并行开发骨架，方便不同窗口在明确边界后直接落代码。

## 目录边界

- `app/`
  - 页面入口与路由层
- `components/`
  - 可复用界面组件
- `lib/`
  - API client、状态辅助和通用前端工具
- `types/`
  - 前端消费的类型定义；优先从 `contracts/` 派生，不自行发明协议字段

## 并行协作约束

- 页面结构和展示逻辑放在 `frontend/`
- 共享字段结构不在这里定义，统一由 `contracts/` 维护
- 不把 demo 数据直接散落到组件目录中，需要的本地样例放到 `contracts/demo_payloads/` 或 `data/demos/`
