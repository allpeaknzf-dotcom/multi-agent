#!/usr/bin/env bash
# Multi-agent 启动脚本：双击即可打开应用
# 首次打开若提示无权限，右键 -> 打开 即可
cd "$(dirname "$0")"
echo "正在启动 Multi-agent，请稍候（首次约 10-30 秒）..."
cd frontend
export PATH="$HOME/.cargo/bin:$PATH"
npm run tauri dev
