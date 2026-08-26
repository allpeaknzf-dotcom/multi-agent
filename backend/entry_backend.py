"""PyInstaller 打包入口：直接以 app 对象启动 uvicorn，保证依赖被完整追踪。

打包命令示例：
    .venv/bin/pyinstaller --noconfirm --clean --onefile --name multiagent-backend \
        --hidden-import uvicorn.logging \
        --hidden-import uvicorn.loops.auto \
        --hidden-import uvicorn.protocols.http.auto \
        --hidden-import uvicorn.protocols.websockets.auto \
        --hidden-import uvicorn.lifespan.on \
        --collect-all anthropic --collect-all openai \
        entry_backend.py
"""
from __future__ import annotations

import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    port = int(os.environ.get("MULTIAGENT_PORT", "8765"))
    host = os.environ.get("MULTIAGENT_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")

