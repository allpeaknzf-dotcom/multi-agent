"""事件总线：编排引擎 -> WebSocket 前端 的实时推送通道。

各 session 的活跃连接由 ws 端点注册；引擎通过 publish 广播事件。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class EventBus:
    def __init__(self) -> None:
        self._conns: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def register(self, session_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.setdefault(session_id, set()).add(ws)

    async def unregister(self, session_id: int, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._conns.get(session_id)
            if conns and ws in conns:
                conns.discard(ws)
                if not conns:
                    self._conns.pop(session_id, None)

    async def publish(self, session_id: int, event: dict[str, Any]) -> None:
        """向某会话的所有在线连接推送事件。"""
        async with self._lock:
            targets = list(self._conns.get(session_id, set()))
        payload = {"type": event.get("type", "message"), **event}
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                await self.unregister(session_id, ws)


event_bus = EventBus()
