# Backend

本目录现在承载一个可启动的 FastAPI 基础链路，覆盖：

- `GET /api/v1/health`
- `POST /api/v1/analyze`
- 统一配置、日志、错误响应
- mock 版 `input_normalizer / claim_extractor / verdict_engine / report_builder`

## 详细实现记录

- 详细记录见 `backend/docs/api-foundation-implementation-record.md`
- 内容包括：实现范围、文件职责、主链路编排、规则细节、测试方法、验证结果、已知边界和后续接手建议

## 目录边界

- `app/api/`
  - 路由与接口编排入口
- `app/core/`
  - 配置、日志、错误处理等基础设施
- `app/models/`
  - 当前后端内部 schema
- `app/services/`
  - 输入标准化、claim、verdict、timeline、report 编排
- `tests/`
  - pytest、smoke test、主链路回归测试
- `docs/`
  - 实现记录、交接文档、设计补充说明

## 本地运行

1. `python -m pip install -r backend/requirements-dev.txt`
2. `uvicorn backend.app.main:app --reload`
3. 访问 `http://127.0.0.1:8000/docs`

## 当前实现边界

- 还未接入真实检索与 Kimi provider，分析结果来自规则与 mock 数据
- 共享协议仍以 `contracts/` 为准，后续 schema 冻结后需要再对齐字段
- 测试数据优先读取根目录 `evals/minimal_v1/`
