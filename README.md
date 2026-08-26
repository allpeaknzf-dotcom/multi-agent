# Multi-agent · 多 Agent 协作客户端

让多个不同 AI Agent（Claude / Codex / Hermes / 豆包 / 自定义）在同一个"群聊"里共同辩论、学习、分工完成任务，并可选一个 Agent 担任**主理人**负责任务拆解、派活与验收。

## 核心能力

- **项目隔离**：每个项目独立记忆，互不串扰；项目内可建多个会话
- **群聊式会话**：新建会话选择参与 Agent，中途可随时拉 Agent 进群，支持 `@` 指定发言（输入框内输入 `@Agent名` 亦可定向）
- **主理人调度**：指定任一 Agent 为主理人，下达任务后自动完成 `拆解 → 派活 → 并行/串行执行 → 验收 → 汇总`
- **产物导出**：沙箱运行代码自动沉淀「源代码 / 运行输出 / 生成的图片文档」，右侧产物面板可查看、下载到本地
- **项目记忆**：主理人派活完成自动把关键结论沉淀到项目记忆，Agent 对话时自动参考历史结论，可手动编辑
- **多模型接入**：OpenAI / Anthropic / 火山方舟 / OpenRouter / Ollama（预留），Key 加密存系统钥匙串，支持编辑与复制
- **自定义 Agent**：任意定义 Agent 人设 + 模型 + Key，支持从内置模板一键导入
- **代码沙箱验证**：Agent 产出的代码可在隔离环境运行（L1 本地受限进程，L2 Docker 可选），结果回喂 Agent 自我修正

## 技术架构

```
frontend/   Tauri 2 + Vue 3 + Naive UI（桌面壳 + UI）
backend/    Python FastAPI 本地编排服务（随客户端启动，监听 127.0.0.1:8765）
  ├─ engine/      主理人调度状态机 / 消息路由 / 项目记忆 / 事件总线
  ├─ providers/   OpenAI / Anthropic / 火山方舟 / OpenRouter 统一适配层
  ├─ tools/executor/  代码沙箱（L1 本地受限进程 + L2 Docker）
  └─ core/        SQLite 存储 + Keychain 加密
```

## 开发运行

```bash
# 前置：Node 20+ / Python 3.13+ / Rust（rustup）/ uv

# 启动后端（仅后端，用于接口调试）
cd backend && uv run uvicorn app.main:app --port 8765

# 启动完整应用（自动拉起后端 + 前端，需 Rust 编译一次）
cd frontend && npm run tauri dev
```

## 打包分发（Mac .dmg）

```bash
# 1. 打包后端为独立可执行（sidecar，供 app 内嵌启动）
cd backend && .venv/bin/pyinstaller --noconfirm --clean --onefile --name multiagent-backend \
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on --collect-all anthropic --collect-all openai \
  entry_backend.py
# 复制为 sidecar（注意目标三元组后缀与 CPU 架构一致）
cp dist/multiagent-backend ../frontend/src-tauri/binaries/multiagent-backend-aarch64-apple-darwin

# 2. 打包桌面应用（产出 .app + .dmg）
cd ../frontend && npm run tauri build
# 产物位于 src-tauri/target/release/bundle/dmg/ 与 macos/
```

> 打包后的 .app 首次启动会自动拉起内嵌后端并等待就绪（日志见 `~/.multi-agent/backend.log`），随后打开主窗口；若 8765 端口已有后端在运行则直接复用。

## 里程碑

### M1（已完成）
- [x] 项目 / 会话 / Agent / Key 数据模型与 API
- [x] 多 Provider 统一接入（OpenAI / Anthropic / 火山方舟 / OpenRouter / Ollama 预留）
- [x] 群聊会话：@ 指定、拉人进群、主理人指定与切换
- [x] 主理人调度：任务拆解 → 派活 → 验收（可多轮重做）→ 汇总
- [x] 代码沙箱：Python / Node / Shell 隔离运行，结果回喂
- [x] 前端：项目列表 / 项目详情 / 群聊界面 / Agent 管理 / Key 管理

### M2（已完成）
- [x] 产物导出：沙箱运行自动沉淀产物，右侧面板查看 / 下载
- [x] 项目记忆：派活结论自动沉淀，可查看 / 编辑，Agent 对话自动参考
- [x] `@` 强化：输入框内 `@Agent名` 文本定向
- [x] 体验优化：Key 编辑/复制、项目与会话归档/恢复/删除、界面优化
- [x] Mac .dmg 打包分发（后端 sidecar 随 app 启动）

### 待推进
- [ ] 图片 / 视频产物（二期）
- [ ] Docker 沙箱增强
- [ ] 更多 Agent 模板 / 平台

## 安全说明

- **API Key**：加密存储于系统钥匙串，不落明文
- **代码沙箱**：默认 L1 进程级隔离（资源限制 + 超时 + 独立工作目录），**非绝对沙箱**；需更强隔离时在会话中启用 Docker（L2，默认禁网 + 只读挂载）
