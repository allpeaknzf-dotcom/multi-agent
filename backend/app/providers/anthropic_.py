"""Anthropic（Claude）Provider，使用官方 SDK。"""
from __future__ import annotations

import inspect

from anthropic import AsyncAnthropic
from anthropic.resources.messages import AsyncMessages

from .base import BaseProvider, ChatMessage, ProviderError, ProviderResult

# anthropic SDK 1.0 移除了 temperature 参数：动态检测，避免传参报错
_ACCEPTS_TEMPERATURE = "temperature" in inspect.signature(AsyncMessages.create).parameters


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ProviderResult:
        # Anthropic messages 仅接受 user / assistant
        msgs = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        kwargs = {"system": system} if system else {}
        if _ACCEPTS_TEMPERATURE:
            kwargs["temperature"] = temperature

        try:
            resp = await self.client.messages.create(
                model=self.model,
                messages=msgs,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"[{self.model}] {exc}") from exc

        content = "".join(b.text for b in resp.content if b.type == "text")
        usage = resp.usage.model_dump() if resp.usage else {}
        return ProviderResult(content=content, raw=resp.model_dump(), usage=usage)
