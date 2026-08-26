"""Provider 统一接口与异常。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    """对话消息（统一格式）。"""

    role: str  # user / assistant / system
    content: str


@dataclass
class ProviderResult:
    """Provider 返回结果（统一格式）。"""

    content: str
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """Provider 调用失败。"""


class BaseProvider:
    """所有 Provider 的基类。子类必须实现 chat。"""

    name: str = "base"

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ProviderResult:
        raise NotImplementedError
