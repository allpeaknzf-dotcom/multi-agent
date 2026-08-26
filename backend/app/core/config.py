"""Multi-agent 全局配置。"""
from __future__ import annotations

import os
from pathlib import Path

# 应用数据目录：优先读环境变量（Tauri 打包后可覆盖为 AppData 目录），默认 ~/.multi-agent
APP_DATA_DIR = Path(
    os.environ.get("MULTIAGENT_DATA_DIR", str(Path.home() / ".multi-agent"))
)
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = APP_DATA_DIR / "multiagent.db"
ARTIFACT_DIR = APP_DATA_DIR / "artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# 本地编排服务监听地址（仅本机）
SERVICE_HOST = os.environ.get("MULTIAGENT_HOST", "127.0.0.1")
SERVICE_PORT = int(os.environ.get("MULTIAGENT_PORT", "8765"))

# 沙箱默认参数
SANDBOX_TIMEOUT = int(os.environ.get("MULTIAGENT_SANDBOX_TIMEOUT", "60"))
SANDBOX_ENABLE_NETWORK = os.environ.get("MULTIAGENT_SANDBOX_NETWORK", "0") == "1"

# 主理人默认验收重做上限
DEFAULT_MAX_ROUNDS = int(os.environ.get("MULTIAGENT_MAX_ROUNDS", "3"))
