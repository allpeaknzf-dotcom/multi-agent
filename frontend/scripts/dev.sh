#!/usr/bin/env bash
# 开发模式：同时启动本地编排后端 + 前端 Vite dev server
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"          # frontend/
BACKEND="$(cd "$ROOT/../backend" && pwd)"          # backend/

echo "[dev] 启动本地编排服务 (127.0.0.1:8765) ..."
cd "$BACKEND"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8765 &
BACKEND_PID=$!

# 优雅退出：Ctrl+C 时一起停
trap "kill $BACKEND_PID 2>/dev/null || true; exit 0" INT TERM EXIT

echo "[dev] 启动前端 dev server (localhost:1420) ..."
cd "$ROOT"
npm run dev
