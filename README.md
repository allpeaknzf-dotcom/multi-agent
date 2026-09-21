# Multi-agent · 多 Agent 协作客户端

让多个不同 AI Agent 在同一个"群聊"里共同协作完成任务，并可选一个 Agent 担任**主理人**负责任务拆解、派活与验收。默认**主理人前台收口**：简单问题主理人直接答，复杂任务它在后台拆活派给其他成员，最后由主理人汇总告诉你。

---

## 核心能力

### 对话与协作
- **主理人前台收口**：有主理人的会话，默认只有主理人回复；简单问题它直接答，复杂任务它自动 `拆解 → 派活 → 验收 → 汇总`，其他成员的协作过程不直接刷屏
- **群聊式会话**：新建会话选择参与 Agent，中途可随时拉 Agent 进群，支持 `@Agent名` 定向发给单个 Agent
- **主理人调度**：指定任一 Agent 为主理人，下达任务后自动完成 `拆解 → 派活 → 并行/串行执行 → 验收 → 汇总`
- **项目隔离**：每个项目独立记忆，互不串扰；项目可绑定本地文件夹，所有产物落盘到该目录；项目内可建多个会话
- **项目记忆**：主理人派活完成自动把关键结论沉淀到项目记忆，Agent 对话时自动参考历史结论，可手动编辑

### 附件上传与 AI 解析
- **对话附件上传**：输入区 📎 按钮多选文件/图片（最多 10 个），先在待发栏预览/删除，点发送才真正上传
- **图片附件**：对话气泡直接显示缩略图，点击放大预览；多模态 base64 传给视觉模型，AI 能"看见"图内容
- **视频附件**：对话气泡显示文件卡片，点击弹窗内嵌播放器
- **PDF 附件**：新标签页原生 PDF 查看器打开；AI 侧前 3 页转 PNG + 全文文字提取，扫描版发票也能读
- **Office 文档**：docx/xlsx/pptx 用 LibreOffice 转 PDF 新标签页预览；AI 侧提取段落/表格文字
- **文本类文件**：md/txt/py/json/csv/html 等直接读内容进对话，AI 直接看到

### 产物与预览
- **产物导出**：沙箱运行代码自动沉淀「源代码 / 运行输出 / 生成的图片文档」，右侧产物面板**只显示当前对话产生的产物**（按会话隔离）
- **图片/视频产物预览**：查看弹窗内嵌 `<img>`/`<video>`，不再只显示文本
- **下载接口**：图片/视频/PDF 返回 `Content-Disposition: inline`，浏览器内嵌渲染；其他类型返回 `attachment` 触发下载

### 多模型与 Agent
- **多模型接入**：OpenAI / Anthropic / 火山方舟 / OpenRouter / Ollama（预留），Key 加密存系统钥匙串
- **自定义 Agent**：任意定义 Agent 人设 + 模型 + Key，支持从内置模板一键导入
- **模型空响应自动重试**：推理模型偶发首次返回空内容，自动重试最多 3 次

### 代码沙箱
- **L1 本地沙箱**：独立临时工作目录、资源限制、超时清理，Python / Node / Shell
- **L2 Docker 沙箱**（可选）：禁网 + 内存/CPU 限制 + 可写挂载回读产物，无 Docker 自动回退 L1

---

## 技术架构

```
frontend/   Tauri 2 + Vue 3 + Naive UI（桌面壳 + UI）
backend/    Python FastAPI 本地编排服务（随客户端启动，监听 127.0.0.1:8765）
  ├─ engine/      主理人调度状态机 / 消息路由 / 项目记忆 / 事件总线 / 上下文构建
  ├─ providers/   OpenAI / Anthropic / 火山方舟 / OpenRouter 统一适配层（支持多模态）
  ├─ tools/executor/  代码沙箱（L1 本地受限进程 + L2 Docker）
  └─ core/        SQLite 存储 + Keychain 加密
```

---

## 开发运行

```bash
# 前置：Node 20+ / Python 3.13+ / Rust（rustup）/ uv / LibreOffice / poppler

# 1. 初始化后端依赖（首次或环境变化后）
cd backend && uv sync

# 2. 安装文本解析依赖（PDF/docx/xlsx/图片）
cd backend && uv pip install pypdf python-docx openpyxl
# macOS 转 PDF 页图：brew install poppler
# Office 转 PDF 预览：brew install --cask libreoffice（或系统已有）

# 3. 启动后端（127.0.0.1:8765）
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765

# 4. 启动前端（另开终端，:5199）
cd frontend && npm run dev -- --port 5199

# 完整桌面应用（自动拉起后端 + 前端，需 Rust 编译一次）
cd frontend && npm run tauri dev
```

> **数据与产物目录**：
> - SQLite 数据库：`~/.multi-agent/multiagent.db`
> - 项目产物（含上传附件）：`~/Multi-agent/{项目名}/`
> - 上传附件：`~/Multi-agent/{项目名}/上传附件/`

---

## 打包分发（Mac .dmg）

```bash
# 1. 打包后端为独立可执行（sidecar，供 app 内嵌启动）
cd backend && .venv/bin/pyinstaller --noconfirm --clean --onefile --name multiagent-backend \
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on --collect-all anthropic --collect-all openai \
  --collect-all pypdf --collect-all docx --collect-all openpyxl \
  entry_backend.py
# 复制为 sidecar（注意目标三元组后缀与 CPU 架构一致）
cp dist/multiagent-backend ../frontend/src-tauri/binaries/multiagent-backend-aarch64-apple-darwin

# 2. 打包桌面应用（产出 .app + .dmg）
cd ../frontend && npm run tauri build
# 产物位于 src-tauri/target/release/bundle/dmg/ 与 macos/
```

> 打包后的 .app 首次启动会自动拉起内嵌后端并等待就绪（日志见 `~/.multi-agent/backend.log`），随后打开主窗口；若 8765 端口已有后端在运行则直接复用。

---

## 附件类型支持矩阵

| 类型 | 对话气泡显示 | 点击预览 | AI 能读到 |
|---|---|---|---|
| png / jpg / gif / webp | 缩略图 | 弹窗放大 | ✅ 多模态看图 |
| mp4 / webm / mov | 文件卡片 | 弹窗播放器 | ❌ 暂不支持 |
| PDF | 文件卡片 | 新标签页原生查看 | ✅ 前 3 页转图 + 全文文字 |
| docx | 文件卡片 | 后端转 PDF 新标签页 | ✅ 段落文字 |
| xlsx | 文件卡片 | 后端转 PDF 新标签页 | ✅ 表格内容（前 5 sheet × 50 行） |
| pptx | 文件卡片 | 后端转 PDF 新标签页 | ❌ 暂不支持 |
| txt / md / py / json / csv / html 等 | 文件卡片 | 弹窗显示文本 | ✅ 直接读内容 |
| zip / exe / dmg 等二进制 | 文件卡片 | 仅下载 | ❌ 无文本内容 |

---

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

### M3（已完成）
- [x] 项目绑定本地文件夹（folder_path），新对话输入即建项目
- [x] 对话附件上传：📎 收集式待发栏（最多 10 个、可删除、发送才上传）
- [x] 产物按对话隔离：右侧面板只显示当前会话产生的产物
- [x] 模型空响应自动重试（推理模型偶发空返回不再存空气泡）
- [x] 图片 / 视频产物预览：查看弹窗内嵌 `<img>`/`<video>`
- [x] Docker 沙箱（L2）：禁网 + 资源限制 + 可写挂载回读产物
- [x] 侧边栏交互优化：新建项目入口、历史对话管理、图标精简
- [x] **主理人前台收口**：默认只有主理人回复，复杂任务自动派活后汇总
- [x] **附件多模态**：图片 base64 进 context，AI 真"看见"图内容
- [x] **PDF 转图**：前 3 页转 PNG 传给视觉模型，扫描版 PDF 也能读
- [x] **文件内容提取**：txt/docx/xlsx/pdf 自动提取文字进对话
- [x] **Office 文档预览**：LibreOffice 转 PDF 新标签页查看
- [x] **Content-Disposition 修复**：图片/视频/PDF inline 内嵌，其他 attachment 下载

### 待推进
- [ ] 更多 Agent 模板 / 平台
- [ ] PDF 按需翻页（用户说"看第 X 页"时临时转图）
- [ ] docx 内嵌图片提取
- [ ] 视频抽帧识别

---

## 安全说明

- **API Key**：加密存储于系统钥匙串，不落明文
- **代码沙箱**：默认 L1 进程级隔离（资源限制 + 超时 + 独立工作目录），**非绝对沙箱**；需更强隔离时启用 Docker（L2，禁网 + 内存/CPU 限制）
- **附件上传**：落盘到项目 `上传附件/` 目录，仅本项目可见；AI 读取时自动截断到 8000 字避免 context 爆炸
