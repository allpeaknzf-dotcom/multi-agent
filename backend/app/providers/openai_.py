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

        # 推理模型偶发首次返回空 content，最多重试 3 次
        last_exc: Exception | None = None
        resp = None
        for attempt in range(3):
            try:
                resp = await self.client.chat.completions.create(
                    model=self.model,
                    messages=msgs,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001  统一包装
                last_exc = exc
                continue
            content = resp.choices[0].message.content or ""
            if content.strip():
                break
            # 空内容：若是被 max_tokens 截断则不再重试
            if resp.choices[0].finish_reason == "length" or attempt == 2:
                break

        if resp is None and last_exc:
            raise ProviderError(f"[{self.model}] {last_exc}") from last_exc

        content = (resp.choices[0].message.content or "") if resp else ""
        usage = resp.usage.model_dump() if resp and resp.usage else {}
        return ProviderResult(content=content, raw=resp.model_dump() if resp else {}, usage=usage)
