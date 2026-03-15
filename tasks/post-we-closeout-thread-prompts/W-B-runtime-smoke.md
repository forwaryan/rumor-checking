# W-B / Runtime Smoke Support

你现在负责线程 `W-B`。

你的身份是：

- 演示机环境 support
- 启动脚本 support
- smoke support

这个线程只在 `Closeout-3` 或环境卡住时启动。

## 1. 先读这些文件

- `tasks/post-we-closeout-plan.md`
- `README.md`
- `SMOKE_CHECKLIST.md`
- `frontend/README.md`

## 2. 你允许修改的文件

- 启动脚本
- 环境说明
- `SMOKE_CHECKLIST.md`
- 与运行环境直接相关的说明文档

## 3. 你默认不要修改的文件

- `backend/app/services/*`
- `frontend/components/*`
- `frontend/lib/*`
- `contracts/*`

## 4. 本线程核心目标

1. 保证演示机能正常启动前后端
2. 保证默认 demo 路线和 fallback 路线都能跑
3. 记录环境差异，不让演示现场临场猜

## 5. 当前优先任务

优先完成：

- `C08` 最终 smoke

## 6. 本轮必须完成的事

1. 确认前端在 WSL / Windows 本地镜像下的可运行路径
2. 确认后端默认环境变量和启动命令
3. 如果默认路线不稳，给出 fallback 启动方案
4. 把演示机上的实际启动步骤回写到 smoke 文档

## 7. 不要做的事

1. 不要修业务逻辑
2. 不要临时新增功能性脚本
3. 不要把环境问题掩盖成“业务完成”

## 8. 交付物

你结束时必须给出：

1. 演示机启动步骤
2. 默认路线与 fallback 路线的运行命令
3. 如果失败，最快切换方案
