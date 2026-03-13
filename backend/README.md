# Backend

本目录用于存放后端 API 与核查流水线实现。

当前仅预留实现骨架，用于让后端、检索、测试线程在一致目录下并行推进。

## 目录边界

- `app/api/`
  - 路由与接口编排入口
- `app/core/`
  - 配置、日志、错误处理等基础设施
- `app/models/`
  - 后端内部模型或由 `contracts/` 派生的结构
- `app/services/`
  - 输入标准化、claim、verdict、report 等业务服务
- `app/providers/`
  - Kimi、检索、URL 抽取等外部能力接入
- `app/repositories/`
  - 缓存、文件读取、持久化访问层
- `tests/`
  - pytest、case 驱动回归和 smoke test

## 并行协作约束

- API 基础链路与检索链路都在 `backend/`，但具体 owner 仍按 task 区分
- 前后端共享协议不在这里直接拍脑袋定义，统一以 `contracts/` 为准
- 开发期测试数据优先从 `data/evals/` 或根目录 `evals/` 读取，不在服务目录随手复制
