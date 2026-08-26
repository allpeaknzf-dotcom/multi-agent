"""Provider 工厂：根据 Agent 定义 + 钥匙串中的 Key 构造 Provider 实例。"""
from __future__ import annotations

from ..core import keyring_store
from ..models.entities import Agent
from .anthropic_ import AnthropicProvider
from .base import BaseProvider, ProviderError
from .openai_ import OpenAICompatProvider

PROVIDER_NAMES = {"openai", "anthropic", "volcengine", "openrouter", "ollama"}

# 各 provider 默认 base_url（火山方舟按账号 endpoint 不同，须由用户填写）
DEFAULT_BASE_URLS = {
    "openai": None,
    "volcengine": None,
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}


def build_provider(agent: Agent) -> BaseProvider:
    """按 Agent 定义构造 Provider（Key 从系统钥匙串实时读取）。"""
    provider = agent.provider
    if provider not in PROVIDER_NAMES:
        raise ProviderError(f"未知 provider: {provider}")

    api_key = ""
    if agent.key_ref:
        api_key = keyring_store.get_key(agent.key_ref) or ""
        if not api_key and provider != "ollama":
            # ollama 不需要 key，其余需要
            raise ProviderError(f"Agent「{agent.name}」缺少有效 API Key（引用: {agent.key_ref}）")

    base_url = agent.base_url or DEFAULT_BASE_URLS.get(provider)

    if provider == "anthropic":
        return AnthropicProvider(api_key=api_key, model=agent.model)

    return OpenAICompatProvider(
        api_key=api_key,
        base_url=base_url,
        model=agent.model,
    )
