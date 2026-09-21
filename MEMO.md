# 改进备忘录

> 记录用户提出的待改进需求（2026-09-20 记录），供后续开发排期参考。

## 1. 对话支持上传文件、图片等

- **状态**：✅ 已实现（2026-09-20）
- **实现**：前端 SessionView 输入区「📎」按钮（支持多选，**收集式**：先进入待发栏显示文件名/大小/删除按钮，最多 10 个，点「发送」才真正上传发出）→ `POST /api/sessions/{id}/upload` → 附件保存到对话产物目录 `上传附件/`（同名自动加序号）→ 登记 Artifact（图片识别为 image，其余为 other）→ 自动插入上下文消息「📎 上传了附件：xxx / 文件路径：...」供 Agent 读取
- **涉及**：`backend/app/api/routes.py`、`backend/app/engine/manager.py`、`frontend/src/views/SessionView.vue`、`frontend/src/api/client.ts`、`pyproject.toml`（+python-multipart）

## 2. 对话中的产物只显示该对话产生的

- **状态**：✅ 已验证（2026-09-20）
- **实现**：产物面板按 `session_id` 过滤展示
  - `GET /api/sessions/{id}/artifact-folders` → `manager.list_artifact_folders()` 已 `filter(Artifact.session_id == session_id)`
  - `GET /api/sessions/{id}/artifacts` → 已 `filter_by(session_id=session_id)`
  - 前端 `SessionView.loadArtifacts()` 只调用当前会话的接口，按返回的 folders 渲染
- **验证**：浏览器对照实测三个会话各自只显示自己的产物——会话1（项目1）→「历史产物」；会话2（项目1）→「上传附件」；会话3（项目2）→「2026-09-18/运行测试」；无跨会话串扰
- **备注**：磁盘文件按项目目录存放（`~/Multi-agent/{项目}/`，同项目多对话共享磁盘），但产物面板按对话过滤展示，互不串扰

---

- 记录时间：2026-09-20
- 相关文件：`backend/app/api/routes.py`、`backend/app/engine/manager.py`、`frontend/src/views/SessionView.vue`
