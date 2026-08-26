#!/usr/bin/env bash
# 构建模式：先打前端产物，再由 tauri 打包（后端侧车打包留到 M2）
set -e
cd "$(dirname "$0")/.."
npm run build
