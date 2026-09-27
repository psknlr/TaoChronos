"""The model providers the web client offers, derived from the harness's own presets.

The browser calls a provider directly with the user's key when the provider allows it (CORS), or through the local
server's proxy (``taochronos serve``), which forwards only to the hosts listed here.  MiniMax on the mainland platform,
with MiniMax-M3, is the default.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ..plugins.models.openai_compat import PRESETS

LABELS = {
    "minimax": "MiniMax（国内站）", "minimax-global": "MiniMax（国际站）", "openai": "OpenAI", "anthropic": "Anthropic Claude",
    "deepseek": "DeepSeek", "qwen": "通义千问（DashScope）", "moonshot": "Kimi（Moonshot）", "zhipu": "智谱 GLM",
    "siliconflow": "硅基流动", "ark": "火山方舟（豆包）", "openrouter": "OpenRouter", "poe": "Poe", "grok": "xAI Grok",
    "gemini": "Google Gemini（兼容接口）", "litellm-proxy": "LiteLLM 代理", "local": "本地 vLLM", "ollama": "Ollama（本机）",
}
ORDER = ["minimax", "minimax-global", "deepseek", "qwen", "moonshot", "zhipu", "siliconflow", "ark", "openrouter", "poe",
         "openai", "anthropic", "gemini", "grok", "litellm-proxy", "ollama", "local"]
# what the web client needs to know beyond the harness presets
EXTRA = {
    "minimax": {"default_model": "MiniMax-M3", "reasoning": "reasoning_details", "vision": True, "stream_usage": True,
                "note": "在 MiniMax 开放平台控制台创建 API Key；默认模型 MiniMax-M3（1M 上下文，自适应思考）"},
    "minimax-global": {"default_model": "MiniMax-M3", "reasoning": "reasoning_details", "vision": True, "stream_usage": True},
    "deepseek": {"default_model": "deepseek-chat", "reasoning": "reasoning_content", "stream_usage": True},
    "openai": {"stream_usage": True, "vision": True},
    "qwen": {"stream_usage": True},
    "openrouter": {"stream_usage": True, "reasoning": "reasoning_details"},
    "poe": {"default_model": "claude-sonnet-4.6"},
    "anthropic": {"format": "anthropic", "base_url": "https://api.anthropic.com/v1", "api_key_env": "ANTHROPIC_API_KEY",
                  "default_model": "claude-opus-5", "examples": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
                  "reasoning": "thinking", "vision": True, "note": "经官方 SDK 调用；Opus 5 默认启用服务端拒答回退（fallbacks）"},
    "ollama": {"base_url": "http://localhost:11434/v1", "api_key_env": None, "key_optional": True},
    "local": {"key_optional": True},
    "litellm-proxy": {"key_optional": True},
}


def web_providers() -> list[dict[str, Any]]:
    """The provider list of the web client's settings (``providers.json``)."""
    out = []
    for pid in ORDER:
        preset = {**PRESETS.get(pid, {}), **EXTRA.get(pid, {})}
        if not preset.get("base_url"):
            continue
        out.append({
            "id": pid,
            "label": LABELS.get(pid, pid),
            "format": preset.get("format", "openai"),
            "base_url": preset["base_url"],
            "key_env": preset.get("api_key_env"),
            "key_optional": bool(preset.get("key_optional") or preset.get("api_key_env") is None),
            "max_tokens_param": preset.get("max_tokens_param", "max_tokens"),
            "extra_body": preset.get("extra_body") or {},
            "examples": list(preset.get("examples") or []),
            "default_model": preset.get("default_model") or (preset.get("examples") or [""])[0],
            "reasoning": preset.get("reasoning"),
            "vision": bool(preset.get("vision")),
            "stream_usage": bool(preset.get("stream_usage")),
            "note": preset.get("note", ""),
        })
    return out


def proxy_hosts() -> set[tuple[str, str, int]]:
    """(scheme, host, port) the local server may forward model requests to."""
    hosts = set()
    for p in web_providers():
        parts = urlsplit(p["base_url"])
        hosts.add((parts.scheme, parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80)))
    return hosts


def key_env_for(host: str) -> str | None:
    for p in web_providers():
        if urlsplit(p["base_url"]).hostname == host:
            return p.get("key_env")
    return None
