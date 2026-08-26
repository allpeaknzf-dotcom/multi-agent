"""OpenAI 兼容 Provider。

覆盖：OpenAI 官方、OpenRouter、火山方舟（Volcengine Ark）、Ollama。
四者都提供 OpenAI 兼容的 /chat/completions 接口，仅 base_url / model 不同。
"""
from __future__ import annotations

from openai import AsyncOpenAI

from .base import BaseProvider, ChatMessage, ProviderError, ProviderResult


class OpenAICompatProvider(BaseProvider):
    name = "openai-compat"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        model: str = "gpt-4o",
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ProviderResult:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend({"role": m.role, "content": m.content} for m in messages)

        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001  统一包装
            raise ProviderError(f"[{self.model}] {exc}") from exc

        content = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage else {}
        return ProviderResult(content=content, raw=resp.model_dump(), usage=usage)
